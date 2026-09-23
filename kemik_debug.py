"""
Script temporal de diagnóstico para Kemik.
Objetivo único: pasar Cloudflare y volcar el HTML final renderizado a un archivo local.
No parsea ni busca selectores de productos.

Requiere:
    pip install playwright fake-useragent
    playwright install chromium
"""
import asyncio
import logging
import random

from fake_useragent import UserAgent
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kemik_debug")

KEMIK_BASE_URL = "https://www.kemik.gt/"
KEMIK_SEARCH_URL = "https://www.kemik.gt/?s=teclado&post_type=product"
NAVIGATION_TIMEOUT_MS = 30_000
OUTPUT_FILE = "kemik_debug.html"


def _get_random_user_agent() -> str:
    """Replica la lógica de UA del scraper original, con el mismo fallback."""
    try:
        ua = UserAgent(
            browsers=["Chrome", "Edge", "Firefox"],
            os=["Windows", "Mac OS X"],
            platforms=["desktop"],
        )
        return str(ua.random)
    except Exception as error:
        logger.warning("fake_useragent falló (%s), usando UA por defecto.", error)
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )


async def volcar_html_kemik() -> None:
    user_agent = _get_random_user_agent()

    async with async_playwright() as playwright:
        # headless=False ayuda a veces con Cloudflare; cambia a True si tu entorno lo soporta igual.
        browser = await playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=user_agent,
            locale="es-GT",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "es-GT,es;q=0.9,en;q=0.8"},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        page = await context.new_page()

        try:
            logger.info("Cargando página principal para resolver Cloudflare...")
            await page.goto(
                KEMIK_BASE_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
            )
            await page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.sleep(random.uniform(2.0, 3.0))

            logger.info("Navegando directamente a la URL de búsqueda...")
            await page.goto(
                KEMIK_SEARCH_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
            )
            await page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            html = await page.content()

            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write(html)

            logger.info("HTML volcado exitosamente en '%s' (%d caracteres).", OUTPUT_FILE, len(html))

        except PlaywrightTimeoutError as error:
            logger.error("Timeout de navegación con Playwright: %s", error)
        except PlaywrightError as error:
            logger.error("Error de Playwright: %s", error)
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    asyncio.run(volcar_html_kemik())