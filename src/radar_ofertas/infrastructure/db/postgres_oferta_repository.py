"""
Implementación PostgreSQL (Neon DB) de OfertaRepository.
Vive en la capa de infraestructura y utiliza psycopg2 (puerto 5432) con
fallback automático al endpoint nativo SQL-over-HTTPS de Neon (puerto 443)
cuando un firewall o proxy bloquea conexiones TCP directas al puerto 5432.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.repositories.oferta_repository import OfertaRepository
from radar_ofertas.domain.services.filtro_relevancia import (
    extraer_especificaciones_y_gama,
    filtrar_dicts_relevantes,
)

load_dotenv()

logger = logging.getLogger(__name__)


class _NeonHttpCursor:
    """Cursor compatible con DB-API 2.0 que ejecuta SQL sobre el endpoint HTTPS de Neon (/sql)."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        host = urlparse(database_url).hostname
        if not host:
            raise ValueError("DATABASE_URL no contiene un hostname válido para Neon DB.")
        self._endpoint = f"https://{host}/sql"
        self._rows: list[tuple] = []
        self._idx = 0

    def __enter__(self) -> _NeonHttpCursor:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    @staticmethod
    def _convertir_placeholders(query: str) -> str:
        """Convierte marcadores %s de psycopg2 a $1, $2, ... requeridos por Neon HTTP SQL."""
        partes = query.split("%s")
        if len(partes) == 1:
            return query
        resultado = [partes[0]]
        for i, parte in enumerate(partes[1:], 1):
            resultado.append(f"${i}{parte}")
        return "".join(resultado)

    @staticmethod
    def _serializar_param(valor: object) -> object:
        if isinstance(valor, Decimal):
            return str(valor)
        return valor

    def execute(self, query: str, params: tuple | list = ()) -> None:
        sql_parametrizado = self._convertir_placeholders(query)
        params_serializados = [self._serializar_param(p) for p in params]
        payload = json.dumps(
            {"query": sql_parametrizado, "params": params_serializados}
        ).encode("utf-8")

        req = urllib.request.Request(
            self._endpoint,
            data=payload,
            headers={
                "Neon-Connection-String": self._database_url,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        fields = [f["name"] for f in data.get("fields", [])]
        raw_rows = data.get("rows", [])
        self._rows = [
            tuple(row.get(col) for col in fields) if isinstance(row, dict) else tuple(row)
            for row in raw_rows
        ]
        self._idx = 0

    def fetchone(self) -> tuple | None:
        if self._idx < len(self._rows):
            fila = self._rows[self._idx]
            self._idx += 1
            return fila
        return None

    def fetchall(self) -> list[tuple]:
        restantes = self._rows[self._idx :]
        self._idx = len(self._rows)
        return restantes


class _NeonHttpConnection:
    """Conexión ligera sobre HTTPS para Neon Serverless cuando el puerto 5432 está bloqueado."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def __enter__(self) -> _NeonHttpConnection:
        return self
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def cursor(self) -> _NeonHttpCursor:
        return _NeonHttpCursor(self._database_url)

    def close(self) -> None:
        pass


class PostgresOfertaRepository(OfertaRepository):
    """Repositorio PostgreSQL para persistir y consultar OfertaLocal en Neon DB."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = (database_url or os.getenv("DATABASE_URL") or "").strip()
        if not self._database_url:
            raise ValueError(
                "No se encontró DATABASE_URL. Configura tu archivo .env con la URL de conexión de Neon DB."
            )

    def _get_connection(self):
        try:
            return psycopg2.connect(self._database_url, connect_timeout=3)
        except psycopg2.OperationalError as error:
            if "neon.tech" in self._database_url:
                logger.info(
                    "Puerto 5432 restringido (%s); usando endpoint SQL-over-HTTPS de Neon (puerto 443).",
                    str(error).splitlines()[0],
                )
                return _NeonHttpConnection(self._database_url)
            raise

    @staticmethod
    def _normalizar_slug_tienda(nombre_tienda: str) -> str:
        reemplazos = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
        limpio = nombre_tienda.strip().translate(reemplazos).lower()
        slug = "-".join(limpio.split())
        if slug == "tecnofacil":
            return "tecno-facil"
        return slug

    @classmethod
    def _asegurar_tienda(cls, cursor, nombre_tienda: str) -> tuple[str, bool, Decimal]:
        """Obtiene (o crea si no existe) el registro de la tienda en la tabla `tiendas`."""
        slug = cls._normalizar_slug_tienda(nombre_tienda)
        urls_conocidas = {
            "kemik": "https://www.kemik.gt",
            "pacifiko": "https://www.pacifiko.com",
            "la-torre": "https://www.latorre.com.gt",
            "tiendas-max": "https://www.max.com.gt",
            "tecno-facil": "https://www.tecnofacil.com.gt",
            "tecnofacil": "https://www.tecnofacil.com.gt",
            "la-curacao": "https://www.lacuracaonline.com/guatemala",
            "tropigas": "https://www.almacenestropigas.com/guatemala",
            "tienda-claro": "https://www.claro.com.gt",
            "tienda-tigo": "https://tienda.tigo.com.gt",
            "office-depot": "https://www.officedepot.com.gt",
            "intelaf": "https://www.intelaf.com",
            "cemaco": "https://www.cemaco.com",
            "epa": "https://gt.epaenlinea.com",
            "novex": "https://www.novex.com.gt",
            "walmart": "https://www.walmart.com.gt",
            "paiz": "https://www.paiz.com.gt",
            "maxi-despensa": "https://www.maxidespensa.com.gt",
            "siman": "https://gt.siman.com",
            "elektra": "https://www.elektra.com.gt",
            "ishop": "https://ishop.gt",
            "istore": "https://ishop.gt",
            "pricesmart": "https://www.pricesmart.com/en-GT",
        }
        url_base = urls_conocidas.get(slug, f"https://www.{slug}.com")
        cursor.execute(
            """
            INSERT INTO tiendas (slug, nombre, pais, tipo, url_base, envio_gratis_default, tarifa_envio_local_gtq, moneda_nativa)
            VALUES (%s, %s, 'GT', 'local', %s, FALSE, 35.00, 'GTQ')
            ON CONFLICT (slug) DO UPDATE
                SET updated_at = NOW()
            RETURNING id, envio_gratis_default, tarifa_envio_local_gtq;
            """,
            (slug, nombre_tienda.strip(), url_base),
        )
        row = cursor.fetchone()
        envio_gratis = row[1] if isinstance(row[1], bool) else str(row[1]).lower() == "true"
        return str(row[0]), envio_gratis, Decimal(str(row[2]))

    @staticmethod
    def _asegurar_categoria(cursor, categoria_slug: str) -> str:
        """Obtiene (o crea si no existe) la categoría en la tabla `categorias`."""
        nombre_default = categoria_slug.replace("-", " ").title()
        cursor.execute(
            """
            INSERT INTO categorias (slug, nombre, dai_porcentaje)
            VALUES (%s, %s, 5.00)
            ON CONFLICT (slug) DO UPDATE
                SET activo = TRUE
            RETURNING id;
            """,
            (categoria_slug, nombre_default),
        )
        row = cursor.fetchone()
        return str(row[0])

    @staticmethod
    def clasificar_categoria_ui(titulo: str, tienda_slug: str = "") -> str:
        """
        Clasifica cualquier producto en una de las 5 Categorías Principales de tecHunter v4.0:
          - 'computo'        -> 💻 Cómputo y Laptops
          - 'smartphones'    -> 📱 Smartphones
          - 'hogar'          -> 🧊 Línea Blanca y Hogar
          - 'herramientas'   -> 🔧 Herramientas
          - 'super-mascotas' -> 🧺 Supermercado y Mascotas
        """
        t = (titulo or "").lower()
        s = (tienda_slug or "").lower()

        if any(
            k in t
            for k in (
                "pedigree",
                "purina",
                "dog chow",
                "pro plan",
                "beneful",
                "whiskas",
                "croqueta",
                "perro",
                "gato",
                "mascota",
                "alimento para",
                "ruccan",
                "supermercado",
                "despensa",
            )
        ) or s == "la-torre":
            return "super-mascotas"

        if any(
            k in t
            for k in (
                "taladro",
                "barreno",
                "esmeriladora",
                "martillo",
                "destornillador",
                "sierra",
                "lijadora",
                "llave ",
                "herramienta",
                "truper",
                "pretul",
                "dewalt",
                "makita",
                "stanley",
                "bosch",
                "black+decker",
                "black and decker",
                "black & decker",
                "emtop",
                "compresor",
                "soldadora",
                "rotomartillo",
                "atornillador",
                "hidrolavadora",
                "karcher",
                "kärcher",
            )
        ) or s in {"epa", "novex"}:
            return "herramientas"

        if any(
            k in t
            for k in (
                "celular",
                "smartphone",
                "iphone",
                "galaxy a",
                "galaxy s",
                "galaxy z",
                "redmi",
                "poco ",
                "motorola",
                "moto g",
                "honor ",
                "prepago claro",
                "prepago tigo",
                "postpago",
                "galaxy watch",
                "apple watch",
                "smartwatch",
            )
        ) or s in {"tienda-claro", "tienda-tigo"}:
            return "smartphones"

        if any(
            k in t
            for k in (
                "laptop",
                "notebook",
                "portatil",
                "portátil",
                "macbook",
                "imac",
                "mac mini",
                "workstation",
                "computadora",
                "monitor",
                "ultragear",
                "odyssey",
                "rtx",
                "geforce",
                "radeon",
                "ryzen",
                "intel core",
                "ssd",
                "nvme",
                "ddr4",
                "ddr5",
                "teclado",
                "mouse",
                "volante",
                "g29",
                "logitech",
                "impresora",
                "ecotank",
                "smart tank",
                "router",
                "playstation",
                "ps5",
                "xbox",
                "nintendo",
                "ipad",
                "tablet",
            )
        ) or s in {"intelaf", "office-depot"}:
            return "computo"

        if any(
            k in t
            for k in (
                "refrigeradora",
                "frigobar",
                "lavadora",
                "secadora",
                "estufa",
                "microondas",
                "licuadora",
                "cafetera",
                "freidora",
                "ventilador",
                "aire acondicionado",
                "aspiradora",
                "plancha",
                "horno",
                "smart tv",
                "televisor",
                "pulgadas",
                "led ",
                "qled",
                "oled",
                "cristal",
                "crystal",
                "soundbar",
                "sistema de sonido",
                "barra de sonido",
                "mabe",
                "whirlpool",
                "frigidaire",
                "oster",
                "hamilton beach",
                "hogar",
            )
        ) or s == "tropigas":
            return "hogar"

        return "computo"

    @staticmethod
    def _inferir_marca(titulo: str) -> str | None:
        titulo_lower = titulo.lower()
        marcas_conocidas = [
            "Logitech",
            "Pedigree",
            "Purina",
            "Dog Chow",
            "Pro Plan",
            "Beneful",
            "Whiskas",
            "Ruccan",
            "Redragon",
            "Razer",
            "Sony",
            "PlayStation",
            "Samsung",
            "Apple",
            "iPhone",
            "iPad",
            "MacBook",
            "Nintendo",
            "LG",
            "Whirlpool",
            "Mabe",
            "Frigidaire",
            "Oster",
            "Hamilton Beach",
            "Bosch",
            "Truper",
            "Pretul",
            "Stanley",
            "DeWalt",
            "Makita",
            "Black+Decker",
            "Black & Decker",
            "Black And Decker",
            "Emtop",
            "Xiaomi",
            "Redmi",
            "Motorola",
            "Honor",
            "Hisense",
            "TCL",
            "Asus",
            "Lenovo",
            "HP",
            "Dell",
            "Acer",
            "MSI",
            "RCA",
            "Garmin",
            "JBL",
            "Bose",
        ]
        for marca in marcas_conocidas:
            if marca.lower() in titulo_lower:
                if "black" in marca.lower():
                    return "Black+Decker"
                if marca in {"iPhone", "iPad", "MacBook"}:
                    return "Apple"
                if marca == "Redmi":
                    return "Xiaomi"
                if marca == "PlayStation":
                    return "Sony"
                return marca
        return None

    @classmethod
    def _upsert_producto(
        cls, cursor, oferta: OfertaLocal, categoria_id: str
    ) -> str:
        """
        Busca un producto existente por `url_canonica` o por `nombre` (case-insensitive).
        Si existe, actualiza imagen y fecha; si no existe, lo inserta en `productos`.
        Retorna el UUID (`id`) del producto.
        """
        cursor.execute(
            """
            SELECT id
            FROM productos
            WHERE url_canonica = %s OR LOWER(nombre) = LOWER(%s)
            LIMIT 1;
            """,
            (oferta.url, oferta.titulo),
        )
        existente = cursor.fetchone()

        if existente:
            producto_id = str(existente[0])
            cursor.execute(
                """
                UPDATE productos
                SET imagen_url = COALESCE(NULLIF(%s, ''), imagen_url),
                    url_canonica = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (oferta.imagen_url, oferta.url, producto_id),
            )
            return producto_id

        marca = cls._inferir_marca(oferta.titulo)

        cursor.execute(
            """
            INSERT INTO productos (
                nombre,
                marca,
                categoria_id,
                imagen_url,
                url_canonica
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                oferta.titulo,
                marca,
                categoria_id,
                oferta.imagen_url or None,
                oferta.url,
            ),
        )
        nuevo = cursor.fetchone()
        return str(nuevo[0])

    @staticmethod
    def _obtener_ultimo_precio_registrado(
        cursor, producto_id: str, tienda_id: str
    ) -> Decimal | None:
        """
        Consulta el último `precio_nativo` registrado en `historial_precios`
        para la combinación `(producto_id, tienda_id)`.
        """
        cursor.execute(
            """
            SELECT precio_nativo
            FROM historial_precios
            WHERE producto_id = %s AND tienda_id = %s
            ORDER BY scraped_at DESC
            LIMIT 1;
            """,
            (producto_id, tienda_id),
        )
        fila = cursor.fetchone()
        if not fila or fila[0] is None:
            return None
        return Decimal(str(fila[0])).quantize(Decimal("0.01"))

    def guardar_ofertas(
        self, ofertas: list[OfertaLocal], categoria_slug: str = "tecnologia"
    ) -> int:
        """
        Persiste productos en `productos` e inserta un nuevo registro en
        `historial_precios` ÚNICAMENTE si el precio actual es válido (> 0) y cambió
        respecto al último precio registrado para esa tienda y producto.
        """
        if not ofertas:
            return 0

        insertados = 0
        omitidos_sin_cambio = 0
        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cursor:
                    categoria_id = self._asegurar_categoria(cursor, categoria_slug)
                    cache_tiendas: dict[str, tuple[str, bool, Decimal]] = {}

                    for oferta in ofertas:
                        if (
                            oferta.precio_gtq <= 0
                            or getattr(oferta, "estado_precio_membresia", "publico")
                            == "oculto_requiere_login"
                        ):
                            omitidos_sin_cambio += 1
                            continue

                        if oferta.tienda not in cache_tiendas:
                            cache_tiendas[oferta.tienda] = self._asegurar_tienda(
                                cursor, oferta.tienda
                            )
                        tienda_id, envio_gratis, tarifa_envio = cache_tiendas[
                            oferta.tienda
                        ]

                        producto_id = self._upsert_producto(
                            cursor, oferta, categoria_id
                        )

                        precio_nativo = Decimal(str(oferta.precio_gtq)).quantize(
                            Decimal("0.01")
                        )

                        ultimo_precio = self._obtener_ultimo_precio_registrado(
                            cursor, producto_id, tienda_id
                        )
                        if ultimo_precio is not None and ultimo_precio == precio_nativo:
                            omitidos_sin_cambio += 1
                            continue

                        costo_envio = Decimal("0.00") if envio_gratis else tarifa_envio
                        costo_real_gtq = precio_nativo + costo_envio

                        cursor.execute(
                            """
                            INSERT INTO historial_precios (
                                producto_id,
                                tienda_id,
                                precio_nativo,
                                moneda,
                                envio_gratis,
                                costo_envio_gtq,
                                costo_real_gtq,
                                url_oferta,
                                disponibilidad
                            )
                            VALUES (%s, %s, %s, 'GTQ', %s, %s, %s, %s, 'in_stock');
                            """,
                            (
                                producto_id,
                                tienda_id,
                                precio_nativo,
                                envio_gratis,
                                costo_envio,
                                costo_real_gtq,
                                oferta.url,
                            ),
                        )
                        insertados += 1

            logger.info(
                "Neon DB: %d nuevos precios insertados en `historial_precios` (%d omitidos sin variación de precio).",
                insertados,
                omitidos_sin_cambio,
            )
            return insertados
        finally:
            conn.close()

    def buscar_ofertas_comparadas(
        self, query: str = "", tienda_slug: str = "", categoria_ui: str = ""
    ) -> list[dict[str, Any]]:
        """
        Obtiene la última oferta por (producto, tienda) desde Neon DB,
        filtrando por palabras clave, tienda opcional, categoría UI opcional
        y el Filtro Inteligente Anti-Ruido, ordenadas por precio ascendente.
        """
        tokens = [t.strip() for t in query.strip().split() if t.strip()]
        tienda_limpia = tienda_slug.strip().lower()
        if tienda_limpia == "tecnofacil":
            tienda_limpia = "tecno-facil"
        categoria_limpia = categoria_ui.strip().lower()

        condiciones = ["p.activo = TRUE", "t.activo = TRUE"]
        params: list[Any] = []

        if tienda_limpia in {
            "kemik",
            "pacifiko",
            "la-torre",
            "tiendas-max",
            "tecno-facil",
            "tecnofacil",
            "la-curacao",
            "tropigas",
            "tienda-claro",
            "tienda-tigo",
            "office-depot",
            "intelaf",
            "cemaco",
            "epa",
            "novex",
            "walmart",
            "paiz",
            "maxi-despensa",
            "siman",
            "elektra",
            "ishop",
            "istore",
            "pricesmart",
        }:
            if tienda_limpia == "tecno-facil":
                condiciones.append("t.slug IN (%s, %s)")
                params.extend(["tecno-facil", "tecnofacil"])
            elif tienda_limpia in {"istore", "ishop"}:
                condiciones.append("t.slug IN (%s, %s)")
                params.extend(["istore", "ishop"])
            else:
                condiciones.append("t.slug = %s")
                params.append(tienda_limpia)

        for token in tokens:
            patron = f"%{token}%"
            condiciones.append("(p.nombre ILIKE %s OR COALESCE(p.marca, '') ILIKE %s)")
            params.extend([patron, patron])

        where_clause = " AND ".join(condiciones)

        sql = f"""
            SELECT *
            FROM (
                SELECT DISTINCT ON (hp.producto_id, hp.tienda_id)
                    p.id AS producto_id,
                    p.nombre AS titulo,
                    COALESCE(p.marca, '') AS marca,
                    COALESCE(p.imagen_url, '') AS imagen_url,
                    t.slug AS tienda_slug,
                    t.nombre AS tienda,
                    hp.precio_nativo AS precio_gtq,
                    hp.costo_envio_gtq AS costo_envio_gtq,
                    hp.costo_real_gtq AS costo_real_gtq,
                    hp.url_oferta AS url,
                    hp.scraped_at AS scraped_at
                FROM historial_precios hp
                JOIN productos p ON p.id = hp.producto_id
                JOIN tiendas t ON t.id = hp.tienda_id
                WHERE {where_clause}
                ORDER BY hp.producto_id, hp.tienda_id, hp.scraped_at DESC
            ) ultimas
            ORDER BY ultimas.precio_gtq ASC, ultimas.costo_real_gtq ASC;
        """

        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    filas = cursor.fetchall()
        finally:
            conn.close()

        resultados: list[dict[str, Any]] = []
        for fila in filas:
            titulo_str = str(fila[1])
            slug_tienda_str = str(fila[4])
            if slug_tienda_str == "tecnofacil":
                slug_tienda_str = "tecno-facil"
            precio_float = float(fila[6])
            cat_ui = self.clasificar_categoria_ui(titulo_str, slug_tienda_str)
            meta_modelo = extraer_especificaciones_y_gama(
                titulo_str, precio_gtq=precio_float, categoria_ui=cat_ui
            )
            marca_str = str(fila[2] or "") or (self._inferir_marca(titulo_str) or "Oficial GT")
            resultados.append(
                {
                    "producto_id": str(fila[0]),
                    "titulo": titulo_str,
                    "marca": marca_str,
                    "imagen_url": str(fila[3] or ""),
                    "tienda_slug": slug_tienda_str,
                    "tienda": str(fila[5]),
                    "precio_gtq": precio_float,
                    "costo_envio_gtq": float(fila[7]),
                    "costo_real_gtq": float(fila[8]),
                    "url": str(fila[9]),
                    "scraped_at": str(fila[10]),
                    "categoria_ui": cat_ui,
                    "requiere_membresia": slug_tienda_str == "pricesmart",
                    "gama": meta_modelo["gama"],
                    "gama_slug": meta_modelo["gama_slug"],
                    "chips_especificaciones": meta_modelo["chips_especificaciones"],
                    "clave_modelo": meta_modelo["clave_modelo"],
                }
            )

        filtrados = filtrar_dicts_relevantes(resultados, query)
        if categoria_limpia in {
            "computo",
            "smartphones",
            "hogar",
            "herramientas",
            "super-mascotas",
        }:
            return [o for o in filtrados if o.get("categoria_ui") == categoria_limpia]
        return filtrados

