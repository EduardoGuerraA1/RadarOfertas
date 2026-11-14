"""
Implementación concreta de BaseScraper para Cemaco Guatemala (cemaco.com).
Foco principal: herramientas, ferretería, hogar, blancos y artículos generales.

Arquitectura técnica detectada en Cemaco:
  - Plataforma: VTEX Cloud Commerce (`https://www.cemaco.com`).
  - Endpoint REST público (JSON directo sin bloqueo de Cloudflare):
    `https://www.cemaco.com/api/catalog_system/pub/products/search/?ft={query}&_from=0&_to=19`
  - Particularidad del catálogo de Cemaco:
    Algunos nombres y URLs incluyen prefijos internos de ERP como `<VF>#` o `#`
    (ej. `<VF>#TALADRO PERCUTOR 18V...`), los cuales se limpian automáticamente
    en `_limpiar_titulo` y `_limpiar_url` para mantener datos limpios en Neon DB.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urljoin

from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)

CEMACO_BASE_URL = "https://www.cemaco.com/"
CEMACO_SEARCH_API_TEMPLATE = (
    "https://www.cemaco.com/api/catalog_system/pub/products/search/"
    "?ft={query}&_from=0&_to=19"
)
REQUEST_TIMEOUT_SECONDS = 20

_PREFIJOS_ERP_REGEX = re.compile(r"^(?:<[^>]+>|#|\s)+")


class CemacoScraper(BaseScraper):
    """Scraper asíncrono para extraer ofertas de cemaco.com en Guatemala."""

    def __init__(self, timeout_s: int = REQUEST_TIMEOUT_SECONDS) -> None:
        self._timeout_s = timeout_s
        try:
            self._user_agent = UserAgent(
                browsers=["Chrome", "Edge", "Firefox"],
                os=["Windows", "Mac OS X"],
                platforms=["desktop"],
            )
        except Exception:
            self._user_agent = None
            logger.warning(
                "Cemaco: No se pudo inicializar fake_useragent, usando UA por defecto."
            )

    def _get_random_user_agent(self) -> str:
        if self._user_agent is not None:
            try:
                return str(self._user_agent.random)
            except Exception as error:
                logger.warning("Cemaco: fallo generando UA aleatorio: %s", error)

        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _limpiar_titulo(nombre_crudo: str) -> str:
        """Elimina prefijos internos de ERP (como `<VF>#` o `#`) y normaliza espacios."""
        limpio = _PREFIJOS_ERP_REGEX.sub("", nombre_crudo or "")
        return " ".join(limpio.split())

    @staticmethod
    def _limpiar_url(link_crudo: str) -> str:
        """Normaliza la URL del producto en cemaco.com removiendo etiquetas `<vf>` si existen."""
        limpio = (link_crudo or "").strip().replace("<vf>", "").replace("<VF>", "")
        return urljoin(CEMACO_BASE_URL, limpio)

    @classmethod
    def _mapear_producto_vtex_a_oferta(
        cls, producto_vtex: dict[str, Any]
    ) -> OfertaLocal | None:
        """Traduce un producto del JSON VTEX de Cemaco a una entidad OfertaLocal."""
        try:
            titulo = cls._limpiar_titulo(str(producto_vtex.get("productName") or ""))
            link_raw = str(producto_vtex.get("link") or "").strip()
            if not titulo or not link_raw:
                return None

            url_absoluta = cls._limpiar_url(link_raw)

            items = producto_vtex.get("items") or []
            if not isinstance(items, list) or not items:
                return None

            primer_item = items[0] if isinstance(items[0], dict) else {}

            imagenes = primer_item.get("images") or []
            imagen_url = ""
            if isinstance(imagenes, list) and imagenes and isinstance(imagenes[0], dict):
                imagen_url = str(imagenes[0].get("imageUrl") or "").strip()

            sellers = primer_item.get("sellers") or []
            if not isinstance(sellers, list) or not sellers:
                return None
            primer_seller = sellers[0] if isinstance(sellers[0], dict) else {}
            oferta_comercial = primer_seller.get("commertialOffer") or {}
            if not isinstance(oferta_comercial, dict):
                return None

            precio_raw = oferta_comercial.get("Price")
            stock = oferta_comercial.get("AvailableQuantity", 1)
            if precio_raw is None:
                return None

            precio_gtq = float(precio_raw)
            if precio_gtq <= 0 or (isinstance(stock, (int, float)) and stock <= 0):
                return None

            return OfertaLocal(
                tienda="Cemaco",
                titulo=titulo,
                precio_gtq=precio_gtq,
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("Cemaco: fallo mapeando producto VTEX: %s", error)
            return None

    @classmethod
    def parsear_respuesta_vtex(
        cls, raw_json: str | list[dict[str, Any]]
    ) -> list[OfertaLocal]:
        """Convierte el payload JSON de Cemaco VTEX en una lista de OfertaLocal."""
        if isinstance(raw_json, str):
            if not raw_json.strip():
                return []
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError as error:
                logger.warning("Cemaco: JSON inválido en respuesta VTEX: %s", error)
                return []
        else:
            data = raw_json

        if not isinstance(data, list):
            return []

        ofertas: list[OfertaLocal] = []
        for item in data:
            if isinstance(item, dict):
                oferta = cls._mapear_producto_vtex_a_oferta(item)
                if oferta is not None:
                    ofertas.append(oferta)
        return ofertas

    def _consultar_api_sincrono(self, url: str) -> str:
        import gzip

        for intento in range(2):
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

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Cemaco (cemaco.com) y retorna las ofertas encontradas."""
        url_api = CEMACO_SEARCH_API_TEMPLATE.format(query=quote(query.strip()))
        logger.info("Cemaco: consultando API VTEX '%s'...", url_api)

        try:
            raw_json = await asyncio.to_thread(self._consultar_api_sincrono, url_api)
        except Exception as error:
            logger.error("Cemaco: error consultando API VTEX '%s': %s", url_api, error)
            return []

        ofertas = self.parsear_respuesta_vtex(raw_json)
        logger.info("Cemaco: %d ofertas extraídas correctamente.", len(ofertas))
        return ofertas
