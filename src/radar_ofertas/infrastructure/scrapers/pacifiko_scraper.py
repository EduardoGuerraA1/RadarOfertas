"""
Implementación concreta de BaseScraper para la tienda Pacifiko (pacifiko.com).
Capa de infraestructura: analiza el HTML renderizado por el servidor (OpenCart +
módulo so_searchpro) en la ruta `/index.php?category_id=0&search=<query>&submit_search=&route=product%2Fsearch`.

Estructura técnica detectada en Pacifiko:
  - Plataforma: OpenCart detrás de AWS CloudFront (SSR directo, sin bloqueo JS de Cloudflare).
  - Contenedor de cada producto: `div.product-layout`
  - Título completo (sin truncar): atributo `data-name` en `div.product-layout` o `title` en `a.listing-product-link`.
  - Precio actual en Quetzales: `div.price span.price-new` (ej. "Q3,219.00").
  - URL del producto: `a.listing-product-link[href]` (limpiando el sufijo efímero `?ref=s&query_id=...`).
  - Imagen: `.product-image-container img[data-src|src]` o `.item-img.thumb-active[data-src]`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag
from fake_useragent import UserAgent

from decimal import Decimal
from typing import Any

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_url_producto_directa_valida,
    filtrar_ofertas_relevantes,
)

logger = logging.getLogger(__name__)

PACIFIKO_BASE_URL = "https://www.pacifiko.com/"
PACIFIKO_SEARCH_URL_TEMPLATE = (
    "https://www.pacifiko.com/index.php"
    "?category_id=0&search={query}&submit_search=&route=product%2Fsearch"
)
REQUEST_TIMEOUT_SECONDS = 8

_PRECIO_REGEX = re.compile(r"[\d,]+(?:\.\d+)?")


class PacifikoScraper(BaseScraper):
    """Scraper asíncrono para extraer ofertas de pacifiko.com en Guatemala."""

    def __init__(self, timeout_s: int = REQUEST_TIMEOUT_SECONDS, simular: bool = False) -> None:
        self.timeout_s = timeout_s
        self.simular = simular
        try:
            self._user_agent = UserAgent(
                browsers=["Chrome", "Edge", "Firefox"],
                os=["Windows", "Mac OS X"],
                platforms=["desktop"],
            )
        except Exception:
            self._user_agent = None
            logger.warning(
                "Pacifiko: No se pudo inicializar fake_useragent, usando UA por defecto."
            )

    def _get_random_user_agent(self) -> str:
        if self._user_agent is not None:
            try:
                return str(self._user_agent.random)
            except Exception as error:
                logger.warning("Pacifiko: fallo generando UA aleatorio: %s", error)

        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    def _limpiar_url_producto(href: str) -> str:
        """Convierte la URL en absoluta y remueve parámetros de rastreo efímeros (?ref=s&query_id=...)."""
        href_limpio = href.strip().split("?ref=")[0].split("&ref=")[0]
        return urljoin(PACIFIKO_BASE_URL, href_limpio)

    @staticmethod
    def _extraer_precio_gtq(card: Tag) -> float | None:
        """Extrae el precio en Quetzales desde `span.price-new` (o `div.price` si no hay oferta)."""
        nodo_precio = card.select_one("div.price span.price-new") or card.select_one(
            "div.price"
        )
        if nodo_precio is None:
            return None

        texto_precio = nodo_precio.get_text(" ", strip=True)
        coincidencia = _PRECIO_REGEX.search(texto_precio)
        if not coincidencia:
            return None

        try:
            return float(coincidencia.group(0).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _extraer_imagen_url(card: Tag) -> str:
        """Extrae la URL de la imagen principal soportando lazy-loading (`data-src` o `src`)."""
        img = card.select_one(".product-image-container img") or card.select_one("img")
        if img is not None:
            raw = str(img.get("data-src") or img.get("src") or "").strip()
            if raw:
                return urljoin(PACIFIKO_BASE_URL, raw)

        thumb = card.select_one(".item-img.thumb-active") or card.select_one(".item-img")
        if thumb is not None:
            raw_thumb = str(thumb.get("data-src") or "").strip()
            if raw_thumb:
                return urljoin(PACIFIKO_BASE_URL, raw_thumb)

        return ""

    @classmethod
    def _extraer_producto_de_card(cls, card: Tag) -> OfertaLocal | None:
        """Traduce un nodo HTML `div.product-layout` de Pacifiko a una entidad OfertaLocal."""
        try:
            enlace = card.select_one("a.listing-product-link")
            href = str(enlace.get("href") or "").strip() if enlace else ""
            if not href:
                return None

            titulo_raw = (
                card.get("data-name")
                or (enlace.get("title") if enlace else None)
                or (enlace.get_text(" ", strip=True) if enlace else None)
            )
            if not titulo_raw:
                return None
            titulo = " ".join(str(titulo_raw).split())

            precio_gtq = cls._extraer_precio_gtq(card)
            if precio_gtq is None or precio_gtq <= 0:
                return None

            url_absoluta = cls._limpiar_url_producto(href)
            imagen_url = cls._extraer_imagen_url(card)

            return OfertaLocal(
                tienda="Pacifiko",
                titulo=titulo,
                precio_gtq=precio_gtq,
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("Pacifiko: fallo extrayendo un producto del DOM: %s", error)
            return None

    @classmethod
    def parsear_html_busqueda(cls, html: str) -> list[OfertaLocal]:
        """Parsea el documento HTML de búsqueda de Pacifiko y devuelve la lista de OfertaLocal."""
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.product-layout")
        ofertas: list[OfertaLocal] = []

        for card in cards:
            oferta = cls._extraer_producto_de_card(card)
            if oferta is not None:
                ofertas.append(oferta)

        return ofertas

    def _descargar_html_sincrono(self, url: str) -> str:
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(
                req, timeout=self.timeout_s, context=ctx
            ) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except urllib.error.URLError:
            # Fallback con contexto TLS permisivo si hay un proxy intermedio
            ctx_permisivo = ssl._create_unverified_context()
            with urllib.request.urlopen(
                req, timeout=self.timeout_s, context=ctx_permisivo
            ) as resp:
                return resp.read().decode("utf-8", errors="ignore")

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en pacifiko.com y retorna únicamente ofertas reales extraídas en vivo (o [] si falla)."""
        termino = (query or "").strip()
        if not termino or self.simular:
            return []
        url_busqueda = PACIFIKO_SEARCH_URL_TEMPLATE.format(
            query=quote_plus(termino)
        )
        logger.info("Pacifiko: consultando búsqueda '%s'...", url_busqueda)

        try:
            html = await asyncio.to_thread(self._descargar_html_sincrono, url_busqueda)
            ofertas = self.parsear_html_busqueda(html)
        except Exception as error:
            logger.debug("Pacifiko: error de red en '%s': %s", url_busqueda, error)
            return []

        ofertas_validas = [
            o for o in ofertas
            if es_url_producto_directa_valida(o.url)
        ]
        if ofertas_validas:
            logger.info("Pacifiko: %d ofertas reales extraídas.", len(ofertas_validas))
            return filtrar_ofertas_relevantes(ofertas_validas, termino)
        return []
