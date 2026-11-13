"""
Implementación PostgreSQL (Neon DB) de OfertaRepository.
Vive en la capa de infraestructura y utiliza psycopg2 para insertar en
las tablas `productos` e `historial_precios` definidas en db/migrations/001_init.sql.
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal

import psycopg2
from dotenv import load_dotenv

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.repositories.oferta_repository import OfertaRepository

load_dotenv()

logger = logging.getLogger(__name__)


class PostgresOfertaRepository(OfertaRepository):
    """Repositorio PostgreSQL para persistir OfertaLocal en Neon DB."""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = (database_url or os.getenv("DATABASE_URL") or "").strip()
        if not self._database_url:
            raise ValueError(
                "No se encontró DATABASE_URL. Configura tu archivo .env con la URL de conexión de Neon DB."
            )

    def _get_connection(self):
        return psycopg2.connect(self._database_url)

    @staticmethod
    def _asegurar_tienda(cursor, nombre_tienda: str) -> tuple[str, bool, Decimal]:
        """Obtiene (o crea si no existe) el registro de la tienda en la tabla `tiendas`."""
        slug = nombre_tienda.strip().lower().replace(" ", "-")
        cursor.execute(
            """
            INSERT INTO tiendas (slug, nombre, pais, tipo, url_base, envio_gratis_default, tarifa_envio_local_gtq, moneda_nativa)
            VALUES (%s, %s, 'GT', 'local', 'https://www.kemik.gt', FALSE, 35.00, 'GTQ')
            ON CONFLICT (slug) DO UPDATE
                SET updated_at = NOW()
            RETURNING id, envio_gratis_default, tarifa_envio_local_gtq;
            """,
            (slug, nombre_tienda.strip()),
        )
        row = cursor.fetchone()
        return str(row[0]), bool(row[1]), Decimal(str(row[2]))

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
    def _upsert_producto(
        cursor, oferta: OfertaLocal, categoria_id: str
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

        # Inferir marca básica si está en el título (ej. Logitech)
        marca = "Logitech" if "logitech" in oferta.titulo.lower() else None

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

    def guardar_ofertas(
        self, ofertas: list[OfertaLocal], categoria_slug: str = "tecnologia"
    ) -> int:
        if not ofertas:
            return 0

        insertados = 0
        conn = self._get_connection()
        try:
            with conn:
                with conn.cursor() as cursor:
                    categoria_id = self._asegurar_categoria(cursor, categoria_slug)
                    cache_tiendas: dict[str, tuple[str, bool, Decimal]] = {}

                    for oferta in ofertas:
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

                        precio_nativo = Decimal(str(oferta.precio_gtq))
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
                "Neon DB: Se guardaron exitosamente %d ofertas en `productos` e `historial_precios`.",
                insertados,
            )
            return insertados
        finally:
            conn.close()
