"""
Implementación concreta de BaseScraper para Supermercados La Torre Guatemala (latorre.com.gt).
Foco principal: productos de alta frecuencia de compra y mascotas (comida para perro:
Pedigree, Purina, Dog Chow, etc.).

Arquitectura técnica detectada en Supermercados La Torre Online:
  - Plataforma: VTEX Cloud Commerce (`https://www.latorre.com.gt`).
  - Endpoint REST público (JSON directo en ~150ms, sin bloqueo de Cloudflare):
    `https://www.latorre.com.gt/api/catalog_system/pub/products/search/?ft={query}&_from=0&_to=19`
  - Campos clave por elemento:
    - `productName` + `Contenido Neto` (ej. "Alimento Perro Pequeño Res Pedigree (100gr.)")
    - `link`: URL directa al producto en latorre.com.gt
    - `items[0].images[0].imageUrl`: URL de imagen en CDN VTEX
    - `items[0].sellers[0].commertialOffer.Price`: Precio vigente en Quetzales (GTQ)
"""
from __future__ import annotations

import asyncio
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

logger = logging.getLogger(__name__)

LATORRE_BASE_URL = "https://www.latorre.com.gt/"
LATORRE_SEARCH_API_TEMPLATE = (
    "https://www.latorre.com.gt/api/catalog_system/pub/products/search/"
    "?ft={query}&_from=0&_to=19"
)
REQUEST_TIMEOUT_SECONDS = 25


class SuperScraper(BaseScraper):
    """
    Scraper de supermercado (Supermercados La Torre Guatemala - latorre.com.gt).
    Ideal para comparar productos de consumo masivo y mascotas (ej. Pedigree, Purina).
    """

    def __init__(self) -> None:
        try:
            self._user_agent = UserAgent(
                browsers=["Chrome", "Edge", "Firefox"],
                os=["Windows", "Mac OS X"],
                platforms=["desktop"],
            )
        except Exception:
            self._user_agent = None
            logger.warning(
                "La Torre: No se pudo inicializar fake_useragent, usando UA por defecto."
            )

    def _get_random_user_agent(self) -> str:
        if self._user_agent is not None:
            try:
                return str(self._user_agent.random)
            except Exception as error:
                logger.warning("La Torre: fallo generando UA aleatorio: %s", error)

        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _construir_titulo(producto_vtex: dict[str, Any]) -> str:
        """Combina el nombre del producto con su contenido neto (ej. 100gr, 2kg, 20kg) si existe."""
        nombre = str(producto_vtex.get("productName") or "").strip()
        if not nombre:
            return ""

        contenido_neto = producto_vtex.get("Contenido Neto")
        peso_str = ""
        if isinstance(contenido_neto, list) and contenido_neto:
            peso_str = str(contenido_neto[0] or "").strip()
        elif isinstance(contenido_neto, str):
            peso_str = contenido_neto.strip()

        if peso_str and peso_str.lower() not in nombre.lower():
            return f"{nombre} ({peso_str})"
        return nombre

    @classmethod
    def _mapear_producto_vtex_a_oferta(
        cls, producto_vtex: dict[str, Any]
    ) -> OfertaLocal | None:
        """Traduce un objeto de producto de la API VTEX de La Torre a OfertaLocal."""
        try:
            titulo = cls._construir_titulo(producto_vtex)
            link_raw = str(producto_vtex.get("link") or "").strip()
            if not titulo or not link_raw:
                return None

            url_absoluta = urljoin(LATORRE_BASE_URL, link_raw)

            items = producto_vtex.get("items") or []
            if not isinstance(items, list) or not items:
                return None

            primer_item = items[0] if isinstance(items[0], dict) else {}

            # Extraer imagen principal
            imagenes = primer_item.get("images") or []
            imagen_url = ""
            if isinstance(imagenes, list) and imagenes and isinstance(imagenes[0], dict):
                imagen_url = str(imagenes[0].get("imageUrl") or "").strip()

            # Extraer oferta comercial del vendedor principal
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
                tienda="La Torre",
                titulo=titulo,
                precio_gtq=precio_gtq,
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("La Torre: fallo mapeando producto VTEX: %s", error)
            return None

    @classmethod
    def parsear_respuesta_vtex(cls, raw_json: str | list[dict[str, Any]]) -> list[OfertaLocal]:
        """Convierte el JSON devuelto por la API VTEX de La Torre en una lista de OfertaLocal."""
        if isinstance(raw_json, str):
            if not raw_json.strip():
                return []
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError as error:
                logger.warning("La Torre: JSON inválido en respuesta VTEX: %s", error)
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
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "application/json",
            "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT_SECONDS, context=ctx
            ) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError:
            ctx_permisivo = ssl._create_unverified_context()
            with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT_SECONDS, context=ctx_permisivo
            ) as resp:
                return resp.read().decode("utf-8", errors="ignore")

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Supermercados La Torre (latorre.com.gt) y retorna ofertas."""
        url_api = LATORRE_SEARCH_API_TEMPLATE.format(query=quote(query.strip()))
        logger.info("La Torre: consultando API VTEX '%s'...", url_api)

        try:
            raw_json = await asyncio.to_thread(self._consultar_api_sincrono, url_api)
        except Exception as error:
            logger.error("La Torre: error consultando API VTEX '%s': %s", url_api, error)
            return []

        ofertas = self.parsear_respuesta_vtex(raw_json)
        logger.info("La Torre: %d ofertas extraídas correctamente.", len(ofertas))
        return ofertas


# Alias descriptivo
LaTorreScraper = SuperScraper
