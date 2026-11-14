"""
Implementación concreta de BaseScraper para Tiendas Max / Tecno Fácil (Grupo DISTELSA).
Foco principal: tecnología, celulares, smartwatches (ej. 'galaxy watch'), consolas,
accesorios gaming ('volante') y electrodomésticos / línea blanca en Guatemala.

Arquitectura técnica de Tiendas Max (`https://www.max.com.gt`) y Tecno Fácil (`https://www.tecnofacil.com.gt`):
  - Plataforma: Magento 2 / Adobe Commerce + Frontend React/PWA protegido por Cloudflare.
  - Rutas soportadas por este scraper:
    1. GraphQL API de Magento 2 (`POST /graphql` con query `products(search: ...)`).
    2. Búsqueda web (`/catalogsearch/result/?q={query}`) extrayendo tanto bloques
       JSON-LD (`schema.org/ItemList` o `Product`) como tarjetas HTML Magento
       (`li.product-item`, `.product-item-info`, `a.product-item-link`, `[data-price-type="finalPrice"]`).
    3. Navegación con Playwright (con timeout estricto para no bloquear servidores en la nube como Render).
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
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup, Tag
from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)

MAX_BASE_URL = "https://www.max.com.gt/"
MAX_SEARCH_URL_TEMPLATE = "https://www.max.com.gt/catalogsearch/result/?q={query}"
MAX_GRAPHQL_URL = "https://www.max.com.gt/graphql"

REQUEST_TIMEOUT_SECONDS = 12
PLAYWRIGHT_TIMEOUT_MS = 15_000

_PRECIO_REGEX = re.compile(r"[\d,]+(?:\.\d+)?")

_MAGENTO_GRAPHQL_QUERY = """
query BuscarProductosMax($search: String!) {
  products(search: $search, pageSize: 15) {
    items {
      name
      sku
      url_key
      small_image {
        url
      }
      price_range {
        minimum_price {
          final_price {
            value
            currency
          }
        }
      }
    }
  }
}
"""


class MaxScraper(BaseScraper):
    """Scraper para extraer ofertas de Tiendas Max (max.com.gt) en Guatemala."""

    def __init__(
        self,
        headless: bool = True,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        usar_playwright_fallback: bool = True,
        nombre_tienda: str = "Tiendas Max",
        base_url: str = MAX_BASE_URL,
    ) -> None:
        self._headless = headless
        self._timeout_s = timeout_s
        self._usar_playwright_fallback = usar_playwright_fallback
        self._nombre_tienda = nombre_tienda
        self._base_url = base_url.rstrip("/") + "/"
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
    def parsear_respuesta_graphql(
        cls,
        raw_data: str | dict[str, Any],
        tienda: str = "Tiendas Max",
        base_url: str = MAX_BASE_URL,
    ) -> list[OfertaLocal]:
        """Traduce la respuesta GraphQL de Magento 2 (`data.products.items`) a OfertaLocal."""
        if isinstance(raw_data, str):
            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                return []
        else:
            payload = raw_data

        if not isinstance(payload, dict):
            return []

        items = ((payload.get("data") or {}).get("products") or {}).get("items") or []
        if not isinstance(items, list):
            return []

        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                titulo = str(item.get("name") or "").strip()
                url_key = str(item.get("url_key") or "").strip().lstrip("/")
                url_suffix = str(item.get("url_suffix") or "").strip()
                if not titulo or not url_key:
                    continue
                if url_suffix and not url_key.endswith(url_suffix):
                    url_key = f"{url_key}{url_suffix}"

                precio_val = (
                    ((item.get("price_range") or {}).get("minimum_price") or {})
                    .get("final_price", {})
                    .get("value")
                )
                if precio_val is None:
                    continue
                precio_gtq = float(precio_val)
                if precio_gtq <= 0:
                    continue

                small_image = item.get("small_image") or {}
                imagen_url = (
                    str(small_image.get("url") or "").strip()
                    if isinstance(small_image, dict)
                    else ""
                )
                if imagen_url:
                    imagen_url = urljoin(base_url, imagen_url)

                url_absoluta = urljoin(base_url, url_key)
                ofertas.append(
                    OfertaLocal(
                        tienda=tienda,
                        titulo=" ".join(titulo.split()),
                        precio_gtq=precio_gtq,
                        url=url_absoluta,
                        imagen_url=imagen_url,
                    )
                )
            except (ValueError, TypeError, AttributeError):
                continue

        return ofertas

    @classmethod
    def _extraer_de_card_html(
        cls, card: Tag, tienda: str = "Tiendas Max", base_url: str = MAX_BASE_URL
    ) -> OfertaLocal | None:
        """Extrae una OfertaLocal desde una tarjeta DOM Magento (`li.product-item` / `.product-item-info`)."""
        try:
            enlace = (
                card.select_one("a.product-item-link")
                or card.select_one("h2 a, h3 a, h4 a")
                or card.select_one("a[href]")
            )
            if enlace is None:
                return None

            href = str(enlace.get("href") or "").strip()
            titulo_raw = (
                card.get("data-name")
                or enlace.get("title")
                or enlace.get_text(" ", strip=True)
            )
            if not href or not titulo_raw:
                return None
            titulo = " ".join(str(titulo_raw).split())

            # Buscar nodo de precio final
            precio_gtq: float | None = None
            nodo_precio_attr = card.select_one("[data-price-amount]")
            if nodo_precio_attr and nodo_precio_attr.get("data-price-amount"):
                try:
                    precio_gtq = float(str(nodo_precio_attr.get("data-price-amount")))
                except ValueError:
                    precio_gtq = None

            if precio_gtq is None:
                nodo_precio = (
                    card.select_one('[data-price-type="finalPrice"] .price')
                    or card.select_one(".special-price .price")
                    or card.select_one(".price-box .price")
                    or card.select_one(".price")
                )
                if nodo_precio is not None:
                    coincidencia = _PRECIO_REGEX.search(
                        nodo_precio.get_text(" ", strip=True)
                    )
                    if coincidencia:
                        precio_gtq = float(coincidencia.group(0).replace(",", ""))

            if precio_gtq is None or precio_gtq <= 0:
                return None

            img = (
                card.select_one("img.product-image-photo")
                or card.select_one("img[data-src]")
                or card.select_one("img[src]")
            )
            imagen_url = ""
            if img is not None:
                raw_img = str(img.get("data-src") or img.get("src") or "").strip()
                if raw_img:
                    imagen_url = urljoin(base_url, raw_img)

            return OfertaLocal(
                tienda=tienda,
                titulo=titulo,
                precio_gtq=precio_gtq,
                url=urljoin(base_url, href.split("?")[0]),
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError):
            return None

    @classmethod
    def parsear_html_busqueda(
        cls,
        html: str,
        tienda: str = "Tiendas Max",
        base_url: str = MAX_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Analiza el HTML de Tiendas Max / Tecno Fácil buscando primero JSON-LD
        (`ItemList` / `Product`) y luego tarjetas DOM de Magento 2 (`li.product-item`).
        """
        if not html or "Attention Required! | Cloudflare" in html:
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []

        # 1. Intentar bloques JSON-LD si están presentes
        for script in soup.select('script[type="application/ld+json"]'):
            texto = script.string or script.get_text()
            if not texto:
                continue
            try:
                data = json.loads(texto)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and data.get("@type") == "ItemList":
                for elem in data.get("itemListElement") or []:
                    prod = elem.get("item") if isinstance(elem, dict) else None
                    if isinstance(prod, dict):
                        nombre = str(prod.get("name") or "").strip()
                        url_p = str(prod.get("url") or "").strip()
                        offers = prod.get("offers") or {}
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        precio = (
                            offers.get("price") or offers.get("lowPrice")
                            if isinstance(offers, dict)
                            else None
                        )
                        img = prod.get("image") or ""
                        if isinstance(img, list):
                            img = img[0] if img else ""
                        if nombre and url_p and precio is not None:
                            try:
                                ofertas.append(
                                    OfertaLocal(
                                        tienda=tienda,
                                        titulo=nombre,
                                        precio_gtq=float(precio),
                                        url=urljoin(base_url, url_p),
                                        imagen_url=urljoin(base_url, str(img))
                                        if img
                                        else "",
                                    )
                                )
                            except ValueError:
                                continue

        if ofertas:
            return ofertas

        # 2. Extraer desde tarjetas DOM de Magento 2
        cards = soup.select("li.product-item, div.product-item-info, article.product-item")
        urls_vistas: set[str] = set()
        for card in cards:
            oferta = cls._extraer_de_card_html(card, tienda=tienda, base_url=base_url)
            if oferta is not None and oferta.url not in urls_vistas:
                urls_vistas.add(oferta.url)
                ofertas.append(oferta)

        return ofertas

    def _intentar_graphql_sincrono(self, query: str) -> list[OfertaLocal]:
        graphql_url = urljoin(self._base_url, "graphql")
        payload = json.dumps(
            {"query": _MAGENTO_GRAPHQL_QUERY, "variables": {"search": query}}
        ).encode("utf-8")
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Store": "default",
        }
        req = urllib.request.Request(
            graphql_url, data=payload, headers=headers, method="POST"
        )
        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT_SECONDS, context=ctx
            ) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                return self.parsear_respuesta_graphql(
                    raw, tienda=self._nombre_tienda, base_url=self._base_url
                )
        except Exception:
            return []

    def _intentar_html_sincrono(self, url_busqueda: str) -> list[OfertaLocal]:
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url_busqueda, headers=headers, method="GET")
        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(
                req, timeout=REQUEST_TIMEOUT_SECONDS, context=ctx
            ) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                return self.parsear_html_busqueda(
                    html, tienda=self._nombre_tienda, base_url=self._base_url
                )
        except Exception:
            return []

    async def _intentar_playwright(self, url_busqueda: str) -> list[OfertaLocal]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self._headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=self._get_random_user_agent(),
                    locale="es-GT",
                    viewport={"width": 1366, "height": 768},
                    ignore_https_errors=True,
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = await context.new_page()
                try:
                    response = await page.goto(
                        url_busqueda,
                        wait_until="domcontentloaded",
                        timeout=PLAYWRIGHT_TIMEOUT_MS,
                    )
                    status = response.status if response else None
                    await asyncio.sleep(1.5)
                    html = await page.content()
                    ofertas = self.parsear_html_busqueda(
                        html, tienda=self._nombre_tienda, base_url=self._base_url
                    )
                    if not ofertas:
                        logger.warning(
                            "%s: 0 ofertas vía Playwright (HTTP %s, título='%s').",
                            self._nombre_tienda,
                            status,
                            await page.title(),
                        )
                    return ofertas
                finally:
                    await context.close()
                    await browser.close()
        except Exception as error:
            logger.warning(
                "%s: Playwright no disponible o bloqueado por Cloudflare: %s",
                self._nombre_tienda,
                str(error).splitlines()[0] if str(error) else error,
            )
            return []

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Tiendas Max (max.com.gt) y retorna ofertas en Quetzales."""
        termino = query.strip()
        url_busqueda = urljoin(
            self._base_url, f"catalogsearch/result/?q={quote_plus(termino)}"
        )
        logger.info("%s: consultando '%s'...", self._nombre_tienda, url_busqueda)

        # 1. Intentar GraphQL / HTTP rápido
        ofertas = await asyncio.to_thread(self._intentar_graphql_sincrono, termino)
        if ofertas:
            logger.info(
                "%s: %d ofertas extraídas vía GraphQL.", self._nombre_tienda, len(ofertas)
            )
            return ofertas

        ofertas = await asyncio.to_thread(self._intentar_html_sincrono, url_busqueda)
        if ofertas:
            logger.info(
                "%s: %d ofertas extraídas vía HTTP SSR.", self._nombre_tienda, len(ofertas)
            )
            return ofertas

        # 2. Fallback con Playwright si está habilitado
        if self._usar_playwright_fallback:
            ofertas = await self._intentar_playwright(url_busqueda)
            if ofertas:
                logger.info(
                    "%s: %d ofertas extraídas vía Playwright.",
                    self._nombre_tienda,
                    len(ofertas),
                )
                return ofertas

        return []
