"""
Implementación concreta de BaseScraper para la tienda Kemik (kemik.gt).
Capa de infraestructura: aquí SÍ viven los detalles técnicos (Playwright, UA rotation).

IMPORTANTE (actualización): Kemik migró de WooCommerce a una app Next.js/React.
Ya no existen selectores CSS tipo "ul.products li.product" en el DOM. La forma
estable de extraer resultados de búsqueda es leer el bloque JSON-LD
(schema.org/ItemList) que Kemik expone para SEO en cada página de resultados,
en vez de parsear el HTML con BeautifulSoup.

Requiere:
    pip install playwright fake-useragent
    playwright install chromium
"""
import asyncio
import json
import logging
import random
from urllib.parse import quote, urljoin

from fake_useragent import UserAgent
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)

KEMIK_BASE_URL = "https://www.kemik.gt/"
# Ruta real de búsqueda de Kemik (confirmada por diagnóstico): NO es WooCommerce.
KEMIK_SEARCH_URL_TEMPLATE = "https://www.kemik.gt/search?query={query}"

NAVIGATION_TIMEOUT_MS = 30_000
NETWORKIDLE_TIMEOUT_MS = 12_000


class KemikScraper(BaseScraper):
    """Scraper para extraer productos del buscador de kemik.gt (Next.js + Cloudflare)."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        try:
            self._user_agent = UserAgent(
                browsers=["Chrome", "Edge", "Firefox"],
                os=["Windows", "Mac OS X"],
                platforms=["desktop"],
            )
        except Exception:
            self._user_agent = None
            logger.warning(
                "No se pudo inicializar fake_useragent, usando UA por defecto."
            )

    def _get_random_user_agent(self) -> str:
        """Genera un User-Agent real y aleatorio para la sesión de Playwright."""
        if self._user_agent is not None:
            try:
                return str(self._user_agent.random)
            except Exception as error:
                logger.warning("fake_useragent falló al generar UA aleatorio: %s", error)

        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    @staticmethod
    async def _extraer_item_list_json_ld(page) -> list[dict]:
        """
        Lee todos los <script type="application/ld+json"> de la página y
        devuelve los items del primero que sea de tipo ItemList (el que
        Kemik usa para listar resultados de búsqueda/categoría).
        """
        try:
            scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
        except PlaywrightError as error:
            logger.warning("No se pudieron leer los bloques JSON-LD: %s", error)
            return []

        for crudo in scripts:
            try:
                data = json.loads(crudo)
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict) and data.get("@type") == "ItemList":
                item_list = data.get("itemListElement", [])
                return [
                    elemento["item"]
                    for elemento in item_list
                    if isinstance(elemento, dict) and "item" in elemento
                ]

        return []

    @staticmethod
    def _normalizar_imagen(imagen_raw: object) -> str:
        """Extrae una URL de imagen válida desde un string, lista u objeto ImageObject."""
        url_img = ""
        if isinstance(imagen_raw, str):
            url_img = imagen_raw.strip()
        elif isinstance(imagen_raw, list) and imagen_raw:
            primero = imagen_raw[0]
            if isinstance(primero, str):
                url_img = primero.strip()
            elif isinstance(primero, dict):
                url_img = str(primero.get("url") or primero.get("contentUrl") or "").strip()
        elif isinstance(imagen_raw, dict):
            url_img = str(imagen_raw.get("url") or imagen_raw.get("contentUrl") or "").strip()

        if url_img:
            return urljoin(KEMIK_BASE_URL, url_img)
        return ""

    @classmethod
    def _mapear_producto_ld_a_oferta(cls, producto_ld: dict) -> OfertaLocal | None:
        """Traduce un objeto Product (schema.org) del JSON-LD a OfertaLocal."""
        try:
            titulo = producto_ld.get("name")
            url_raw = producto_ld.get("url")
            if not titulo or not url_raw:
                return None

            url_absoluta = urljoin(KEMIK_BASE_URL, str(url_raw).strip())

            offers = producto_ld.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            precio_raw = offers.get("price") if isinstance(offers, dict) else None
            if precio_raw is None and isinstance(offers, dict):
                precio_raw = offers.get("lowPrice")
            if precio_raw is None:
                return None
            precio_gtq = float(precio_raw)

            imagen_url = cls._normalizar_imagen(producto_ld.get("image"))

            return OfertaLocal(
                tienda="Kemik",
                titulo=str(titulo).strip(),
                precio_gtq=precio_gtq,
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("Fallo mapeando un producto de Kemik desde JSON-LD: %s", error)
            return None

    async def _obtener_ofertas_busqueda(self, query: str) -> list[OfertaLocal]:
        """
        Usa Playwright para:
          1. Cargar la home de Kemik y dejar que Cloudflare resuelva la cookie de sesión.
          2. Navegar a la ruta real de búsqueda: /search?query=<término>.
          3. Extraer y parsear el bloque JSON-LD (ItemList) con los resultados.
        Retorna la lista de ofertas, o [] si algo falla.
        """
        url_busqueda = KEMIK_SEARCH_URL_TEMPLATE.format(query=quote(query))
        user_agent = self._get_random_user_agent()
        ofertas: list[OfertaLocal] = []

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self._headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=user_agent,
                locale="es-GT",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": "es-GT,es;q=0.9,en;q=0.8"},
                ignore_https_errors=True,
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )

            page = await context.new_page()

            try:
                logger.info("Kemik: cargando página principal para resolver Cloudflare...")
                await page.goto(
                    KEMIK_BASE_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    logger.debug("Kemik: networkidle en home excedió tiempo; continuando con DOM cargado.")
                await asyncio.sleep(random.uniform(2.0, 3.0))

                logger.info("Kemik: navegando a la búsqueda '%s'...", url_busqueda)
                response = await page.goto(
                    url_busqueda, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                )
                status_code = response.status if response else None
                try:
                    await page.locator('script[type="application/ld+json"]').first.wait_for(
                        state="attached", timeout=NETWORKIDLE_TIMEOUT_MS
                    )
                except PlaywrightTimeoutError:
                    logger.debug("Kemik: espera de script JSON-LD agotada; intentando lectura directa.")
                await asyncio.sleep(random.uniform(1.0, 2.0))

                productos_ld = await self._extraer_item_list_json_ld(page)
                if not productos_ld:
                    titulo_pagina = await page.title()
                    logger.warning(
                        "Kemik: 0 productos en JSON-LD (HTTP %s, título='%s'). "
                        "Posible bloqueo/challenge de Cloudflare o búsqueda sin resultados.",
                        status_code,
                        titulo_pagina,
                    )
                else:
                    logger.info("Kemik: %d productos encontrados en JSON-LD.", len(productos_ld))

                for producto_ld in productos_ld:
                    oferta = self._mapear_producto_ld_a_oferta(producto_ld)
                    if oferta is not None:
                        ofertas.append(oferta)

                return ofertas

            except PlaywrightTimeoutError as error:
                logger.error("Kemik: timeout de navegación con Playwright: %s", error)
                return ofertas
            except PlaywrightError as error:
                logger.error("Kemik: error de Playwright consultando Kemik: %s", error)
                return ofertas
            finally:
                await context.close()
                await browser.close()

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en kemik.gt y retorna las ofertas encontradas."""
        return await self._obtener_ofertas_busqueda(query)