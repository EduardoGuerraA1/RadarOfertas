"""
Implementación concreta de BaseScraper para el ecosistema VTEX del Grupo Walmart
en Guatemala:
  - Walmart Guatemala (`https://www.walmart.com.gt`) -> tienda: "Walmart"
  - Paiz (`https://www.paiz.com.gt`)                -> tienda: "Paiz"
  - Maxi Despensa (`https://www.maxidespensa.com.gt`) -> tienda: "Maxi Despensa"

Foco: abarrotes, mascotas, tecnología, línea blanca y hogar.
Extrae títulos limpios, precios vigentes en Quetzales (GTQ), URLs canónicas
e imágenes desde la API pública de catálogo VTEX de cada formato comercial.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urljoin

from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

CADENAS_WALMART_GT: dict[str, dict[str, str]] = {
    "walmart": {
        "nombre": "Walmart",
        "base_url": "https://www.walmart.com.gt/",
        "api_template": (
            "https://www.walmart.com.gt/api/catalog_system/pub/products/search/"
            "?ft={query}&_from=0&_to=14"
        ),
    },
    "paiz": {
        "nombre": "Paiz",
        "base_url": "https://www.paiz.com.gt/",
        "api_template": (
            "https://www.paiz.com.gt/api/catalog_system/pub/products/search/"
            "?ft={query}&_from=0&_to=14"
        ),
    },
    "maxi-despensa": {
        "nombre": "Maxi Despensa",
        "base_url": "https://www.maxidespensa.com.gt/",
        "api_template": (
            "https://www.maxidespensa.com.gt/api/catalog_system/pub/products/search/"
            "?ft={query}&_from=0&_to=14"
        ),
    },
}

REQUEST_TIMEOUT_SECONDS = 15


class WalmartScraper(BaseScraper):
    """
    Scraper asíncrono multicadena para el Grupo Walmart en Guatemala
    (Walmart GT, Paiz y Maxi Despensa).
    """

    def __init__(
        self,
        cadenas: tuple[str, ...] = ("walmart", "paiz", "maxi-despensa"),
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._cadenas = tuple(
            c for c in cadenas if c in CADENAS_WALMART_GT
        ) or ("walmart", "paiz", "maxi-despensa")
        self._timeout_s = timeout_s
        self._aplicar_filtro_ruido = aplicar_filtro_ruido
        try:
            self._user_agent = UserAgent(
                browsers=["Chrome", "Edge", "Firefox"],
                os=["Windows", "Mac OS X"],
                platforms=["desktop"],
            )
        except Exception:
            self._user_agent = None

    def _get_random_user_agent(self) -> str:
        if self._user_agent is not None:
            try:
                return str(self._user_agent.random)
            except Exception:
                pass
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _normalizar_url_producto(
        producto_vtex: dict[str, Any], base_url: str
    ) -> str:
        """
        Construye una URL limpia y pública del producto en el dominio de la cadena
        (`walmart.com.gt`, `paiz.com.gt` o `maxidespensa.com.gt`).
        """
        link_text = str(producto_vtex.get("linkText") or "").strip().strip("/")
        if link_text:
            return urljoin(base_url, f"{link_text}/p")

        link_raw = str(producto_vtex.get("link") or "").strip()
        if not link_raw:
            return ""
        return urljoin(base_url, link_raw)

    @classmethod
    def _mapear_producto_vtex_a_oferta(
        cls,
        producto_vtex: dict[str, Any],
        nombre_tienda: str = "Walmart",
        base_url: str = "https://www.walmart.com.gt/",
    ) -> OfertaLocal | None:
        """Traduce un objeto de producto del JSON VTEX de Walmart/Paiz/Maxi Despensa a OfertaLocal."""
        try:
            titulo = " ".join(str(producto_vtex.get("productName") or "").split())
            url_absoluta = cls._normalizar_url_producto(producto_vtex, base_url)
            if not titulo or not url_absoluta:
                return None

            items = producto_vtex.get("items") or []
            if not isinstance(items, list) or not items:
                return None

            primer_item = items[0] if isinstance(items[0], dict) else {}

            imagenes = primer_item.get("images") or []
            imagen_url = ""
            if isinstance(imagenes, list) and imagenes and isinstance(imagenes[0], dict):
                raw_img = str(imagenes[0].get("imageUrl") or "").strip()
                if raw_img:
                    imagen_url = raw_img.split("?")[0]

            sellers = primer_item.get("sellers") or []
            if not isinstance(sellers, list) or not sellers:
                return None

            # Buscar el seller por defecto o el primero con stock y precio > 0
            oferta_comercial: dict[str, Any] = {}
            for seller in sellers:
                if isinstance(seller, dict):
                    cand = seller.get("commertialOffer") or {}
                    if isinstance(cand, dict) and (cand.get("Price") or 0) > 0:
                        oferta_comercial = cand
                        if seller.get("sellerDefault"):
                            break

            if not oferta_comercial:
                return None

            precio_raw = oferta_comercial.get("Price")
            stock = oferta_comercial.get("AvailableQuantity", 1)
            if precio_raw is None:
                return None

            precio_gtq = float(precio_raw)
            if precio_gtq <= 0 or (isinstance(stock, (int, float)) and stock <= 0):
                return None

            return OfertaLocal(
                tienda=nombre_tienda,
                titulo=titulo,
                precio_gtq=round(precio_gtq, 2),
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning(
                "%s: fallo mapeando producto VTEX: %s", nombre_tienda, error
            )
            return None

    @classmethod
    def parsear_respuesta_vtex(
        cls,
        raw_json: str | list[dict[str, Any]],
        nombre_tienda: str = "Walmart",
        base_url: str = "https://www.walmart.com.gt/",
    ) -> list[OfertaLocal]:
        """Convierte el payload JSON de VTEX en una lista de entidades OfertaLocal."""
        if isinstance(raw_json, str):
            if not raw_json.strip():
                return []
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError as error:
                logger.warning(
                    "%s: JSON inválido en respuesta VTEX: %s", nombre_tienda, error
                )
                return []
        else:
            data = raw_json

        if not isinstance(data, list):
            return []

        ofertas: list[OfertaLocal] = []
        for item in data:
            if isinstance(item, dict):
                oferta = cls._mapear_producto_vtex_a_oferta(
                    item, nombre_tienda=nombre_tienda, base_url=base_url
                )
                if oferta is not None:
                    ofertas.append(oferta)
        return ofertas

    def _consultar_api_sincrono(self, url: str) -> str:
        for _ in range(2):
            headers = {
                "User-Agent": self._get_random_user_agent(),
                "Accept": "application/json",
                "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
            }
            req = urllib.request.Request(url, headers=headers, method="GET")
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(
                    req, timeout=self._timeout_s, context=ctx
                ) as resp:
                    raw_bytes = resp.read()
            except urllib.error.URLError:
                ctx_permisivo = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    req, timeout=self._timeout_s, context=ctx_permisivo
                ) as resp:
                    raw_bytes = resp.read()

            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)

            texto = raw_bytes.decode("utf-8", errors="ignore").strip()
            if texto:
                return texto
        return ""

    async def _buscar_en_cadena(
        self, clave_cadena: str, termino: str
    ) -> list[OfertaLocal]:
        config = CADENAS_WALMART_GT[clave_cadena]
        nombre_tienda = config["nombre"]
        base_url = config["base_url"]
        url_api = config["api_template"].format(query=quote(termino))

        logger.info("%s: consultando API VTEX '%s'...", nombre_tienda, url_api)
        try:
            raw_json = await asyncio.to_thread(self._consultar_api_sincrono, url_api)
        except Exception as error:
            logger.error(
                "%s: error consultando API VTEX '%s': %s",
                nombre_tienda,
                url_api,
                error,
            )
            return []

        ofertas = self.parsear_respuesta_vtex(
            raw_json, nombre_tienda=nombre_tienda, base_url=base_url
        )
        if self._aplicar_filtro_ruido:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)

        logger.info(
            "%s: %d ofertas extraídas correctamente.", nombre_tienda, len(ofertas)
        )
        return ofertas

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """
        Consulta concurrentemente las cadenas configuradas del Grupo Walmart
        (Walmart GT, Paiz y Maxi Despensa) y devuelve las ofertas unificadas.
        """
        termino = query.strip()
        if not termino:
            return []

        listas_por_cadena = await asyncio.gather(
            *(self._buscar_en_cadena(cadena, termino) for cadena in self._cadenas)
        )
        unificadas: list[OfertaLocal] = []
        for lista in listas_por_cadena:
            unificadas.extend(lista)
        return unificadas
