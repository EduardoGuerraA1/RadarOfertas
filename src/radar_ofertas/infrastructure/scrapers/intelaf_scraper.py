"""
Implementación concreta de BaseScraper para Intelaf Guatemala (intelaf.com).
Especializada en Hardware, Componentes de PC, Laptops/Notebooks, Monitores,
Periféricos Gaming y Cómputo en Guatemala.

Arquitectura técnica de Intelaf (`https://www.intelaf.com`):
  - Rutas de catálogo y búsqueda:
      * `/precios_stock_resultado/{slug}` y `/buscar/?q={query}`
      * Detalle de producto: `/precios_stock_detallado/{codigo_sku}`
  - Precios en Quetzales (GTQ):
      * `Precio normal Q...`
      * `Promo ... Q...` o `Beneficio Efectivo / ACH Q...` (se prioriza el mejor precio vigente).
  - Respaldo multicapa:
      1. Extracción desde JSON/API o HTML renderizado de `intelaf.com`.
      2. Navegación opcional con Playwright (`headless`) para resolver retos de Cloudflare.
      3. Catálogo verificado de productos reales de Intelaf Guatemala cuando Cloudflare
         restringe el tráfico desde centros de datos en la nube (Render).
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag
from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_url_producto_directa_valida,
    filtrar_ofertas_relevantes,
)

logger = logging.getLogger(__name__)

INTELAF_BASE_URL = "https://www.intelaf.com/"
INTELAF_SEARCH_URL_TEMPLATE = "https://www.intelaf.com/precios_stock_resultado/{query}"

REQUEST_TIMEOUT_SECONDS = 10
PLAYWRIGHT_TIMEOUT_MS = 12_000

_PRECIO_GTQ_REGEX = re.compile(r"Q\s*([\d,]+(?:\.\d+)?)")


class IntelafScraper(BaseScraper):
    """
    Scraper para extraer ofertas de Intelaf Guatemala (`intelaf.com`),
    referente local en hardware, laptops, componentes de PC y periféricos.
    Tolerancia cero a datos sintéticos (v5.5): solo devuelve productos extraídos en vivo.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        usar_playwright_fallback: bool = False,
        usar_catalogo_respaldo: bool = False,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._headless = headless
        self._timeout_s = timeout_s
        self._usar_playwright_fallback = usar_playwright_fallback
        self._usar_catalogo_respaldo = False
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

    @classmethod
    def parsear_json_productos(
        cls,
        raw_data: str | dict[str, Any] | list[Any],
        base_url: str = INTELAF_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Convierte un arreglo o diccionario JSON de productos de Intelaf
        (`codigo`, `descripcion`/`titulo`, `precio_efectivo`/`precio_normal`) a `OfertaLocal`.
        """
        if isinstance(raw_data, str):
            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                return []
        else:
            payload = raw_data

        items: list[Any] = []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = (
                payload.get("productos")
                or payload.get("items")
                or payload.get("data")
                or []
            )
            if not isinstance(items, list):
                items = []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                codigo = str(
                    item.get("codigo")
                    or item.get("sku")
                    or item.get("id")
                    or ""
                ).strip()
                titulo = " ".join(
                    str(
                        item.get("titulo")
                        or item.get("descripcion")
                        or item.get("nombre")
                        or item.get("name")
                        or ""
                    ).split()
                )
                if not titulo:
                    continue

                precio_val = (
                    item.get("precio_efectivo_gtq")
                    or item.get("precio_promo")
                    or item.get("precio_efectivo")
                    or item.get("precio_normal_gtq")
                    or item.get("precio")
                    or item.get("price")
                )
                if precio_val is None:
                    continue
                precio_gtq = float(str(precio_val).replace(",", "").replace("Q", "").strip())
                if precio_gtq <= 0:
                    continue

                url_raw = str(item.get("url") or "").strip()
                if url_raw:
                    url_absoluta = urljoin(base_url, url_raw)
                elif codigo:
                    url_absoluta = urljoin(
                        base_url, f"precios_stock_detallado/{codigo}"
                    )
                else:
                    continue

                if url_absoluta in urls_vistas:
                    continue

                imagen_raw = str(
                    item.get("imagen_url")
                    or item.get("imagen")
                    or item.get("image")
                    or (f"/images/productos/gran/{codigo}.jpg" if codigo else "")
                ).strip()
                imagen_url = urljoin(base_url, imagen_raw) if imagen_raw else ""

                urls_vistas.add(url_absoluta)
                ofertas.append(
                    OfertaLocal(
                        tienda="Intelaf",
                        titulo=titulo,
                        precio_gtq=round(precio_gtq, 2),
                        url=url_absoluta,
                        imagen_url=imagen_url,
                    )
                )
            except (ValueError, TypeError, AttributeError):
                continue

        return ofertas

    @classmethod
    def _extraer_de_card_html(
        cls, card: Tag, base_url: str = INTELAF_BASE_URL
    ) -> OfertaLocal | None:
        """Extrae una `OfertaLocal` desde una tarjeta HTML de `intelaf.com`."""
        try:
            enlace = (
                card.select_one('a[href*="precios_stock_detallado"]')
                or card.select_one("a[href]")
            )
            if enlace is None:
                return None

            href = str(enlace.get("href") or "").strip()
            if not href:
                return None

            nodo_titulo = (
                card.select_one(".product-title, .descripcion, h2, h3, h4")
                or enlace
            )
            titulo = " ".join(nodo_titulo.get_text(" ", strip=True).split())
            if not titulo:
                return None

            # Buscar todos los precios en Quetzales dentro de la tarjeta y elegir el menor vigente (Promo / Efectivo)
            precios_detectados: list[float] = []
            for match in _PRECIO_GTQ_REGEX.finditer(card.get_text(" ", strip=True)):
                try:
                    valor = float(match.group(1).replace(",", ""))
                    if valor > 0:
                        precios_detectados.append(valor)
                except ValueError:
                    continue

            if not precios_detectados:
                return None

            precio_gtq = min(precios_detectados)

            img = card.select_one("img[src], img[data-src]")
            imagen_url = ""
            if img is not None:
                raw_img = str(img.get("data-src") or img.get("src") or "").strip()
                if raw_img:
                    imagen_url = urljoin(base_url, raw_img)

            return OfertaLocal(
                tienda="Intelaf",
                titulo=titulo,
                precio_gtq=round(precio_gtq, 2),
                url=urljoin(base_url, href),
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError):
            return None

    @classmethod
    def parsear_html_busqueda(
        cls, html: str, base_url: str = INTELAF_BASE_URL
    ) -> list[OfertaLocal]:
        """Analiza el DOM de `intelaf.com/precios_stock_resultado/...` y extrae ofertas."""
        if not html or "Attention Required! | Cloudflare" in html:
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        selectores = (
            "div.product-card, div.card-product, div.producto-item, "
            "article.product, div.col-producto"
        )
        cards = soup.select(selectores)
        if not cards:
            # Buscar contenedores padre de enlaces a precios_stock_detallado
            for a in soup.select('a[href*="precios_stock_detallado"]'):
                parent = a.find_parent(["div", "article", "li"])
                if parent and parent not in cards:
                    cards.append(parent)

        for card in cards:
            oferta = cls._extraer_de_card_html(card, base_url=base_url)
            if oferta is not None and oferta.url not in urls_vistas:
                urls_vistas.add(oferta.url)
                ofertas.append(oferta)

        return ofertas

    def _intentar_http_sincrono(self, url_busqueda: str) -> list[OfertaLocal]:
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url_busqueda, headers=headers, method="GET")
        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(
                req, timeout=self._timeout_s, context=ctx
            ) as resp:
                raw_bytes = resp.read()
                if raw_bytes[:2] == b"\x1f\x8b":
                    raw_bytes = gzip.decompress(raw_bytes)
                html = raw_bytes.decode("utf-8", errors="ignore")
                return self.parsear_html_busqueda(html)
        except Exception:
            return []

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Intelaf Guatemala y retorna únicamente ofertas reales en Quetzales (o [] si falla)."""
        termino = (query or "").strip()
        if not termino:
            return []

        slug_busqueda = quote_plus(termino.lower().replace(" ", "-"))
        url_busqueda = INTELAF_SEARCH_URL_TEMPLATE.format(query=slug_busqueda)
        logger.info("Intelaf GT: consultando '%s'...", url_busqueda)

        ofertas = await asyncio.to_thread(self._intentar_http_sincrono, url_busqueda)
        ofertas = [
            o for o in ofertas
            if es_url_producto_directa_valida(o.url)
        ]

        if self._aplicar_filtro_ruido and ofertas:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)

        return ofertas
