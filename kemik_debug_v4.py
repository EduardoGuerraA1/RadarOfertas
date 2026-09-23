"""
Script de diagnóstico v4 para Kemik - página de resultados de búsqueda.
Ya no intenta parsear el payload interno de React (self.__next_f.push),
sino el bloque JSON-LD estándar (schema.org/ItemList) que Kemik expone
para SEO. Es la fuente más estable y ya trae precio, sku, url e imagen.

Genera:
  - kemik_debug_search.html    -> HTML completo renderizado
  - kemik_debug_products.json  -> productos extraídos del bloque JSON-LD
  - kemik_debug_report.txt     -> resumen legible del diagnóstico

Requiere:
    pip install playwright fake-useragent
    playwright install chromium
"""
import asyncio
import json
import logging
import random

from fake_useragent import UserAgent
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kemik_debug_v4")

KEMIK_BASE_URL = "https://www.kemik.gt/"
KEMIK_SEARCH_URL_TEMPLATE = "https://www.kemik.gt/search?query={query}"
NAVIGATION_TIMEOUT_MS = 30_000

OUTPUT_HTML_FILE = "kemik_debug_search.html"
OUTPUT_JSON_FILE = "kemik_debug_products.json"
OUTPUT_REPORT_FILE = "kemik_debug_report.txt"

QUERY = "teclado"


def _get_random_user_agent() -> str:
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


async def _extraer_json_ld_item_list(page) -> list[dict]:
    """
    Extrae TODOS los <script type="application/ld+json"> de la página,
    parsea cada uno y devuelve la lista de items del primero que sea
    de tipo ItemList (que es el que usa Kemik para listar resultados
    de búsqueda / categoría).
    """
    scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
    logger.info("Se encontraron %d bloques JSON-LD en la página.", len(scripts))

    for crudo in scripts:
        try:
            data = json.loads(crudo)
        except json.JSONDecodeError as error:
            logger.warning("Un bloque JSON-LD no se pudo parsear: %s", error)
            continue

        if isinstance(data, dict) and data.get("@type") == "ItemList":
            item_list = data.get("itemListElement", [])
            # Cada elemento es {"@type": "ListItem", "position": N, "item": {...Product...}}
            productos = [
                elemento["item"]
                for elemento in item_list
                if isinstance(elemento, dict) and "item" in elemento
            ]
            return productos

    return []


def _mapear_a_oferta_local(producto_ld: dict) -> dict:
    """
    Traduce un objeto Product (schema.org) del JSON-LD a los campos
    que espera OfertaLocal en el scraper real. Referencia para reescribir
    _extraer_un_producto sin BeautifulSoup.
    """
    offers = producto_ld.get("offers", {}) or {}
    return {
        "tienda": "Kemik",
        "titulo": producto_ld.get("name"),
        "precio_gtq": offers.get("price"),
        "url": producto_ld.get("url"),
        "imagen_url": producto_ld.get("image"),
        # Extras útiles que no están en OfertaLocal pero podrían servir después:
        "sku": producto_ld.get("sku"),
        "marca": (producto_ld.get("brand") or {}).get("name"),
        "disponibilidad": offers.get("availability"),
    }


async def diagnosticar_kemik() -> None:
    user_agent = _get_random_user_agent()
    reporte: list[str] = []
    url_busqueda = KEMIK_SEARCH_URL_TEMPLATE.format(query=QUERY)

    async with async_playwright() as playwright:
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
            await page.goto(KEMIK_BASE_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.sleep(random.uniform(2.0, 3.0))

            logger.info("Navegando a la URL de búsqueda: %s", url_busqueda)
            await page.goto(url_busqueda, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            html = await page.content()
            with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("HTML volcado en '%s' (%d caracteres).", OUTPUT_HTML_FILE, len(html))

            reporte.append(f"URL final tras navegación: {page.url}")
            reporte.append(f"Título de la página: {await page.title()}")

            productos_ld = await _extraer_json_ld_item_list(page)
            reporte.append(f"\nProductos encontrados en JSON-LD (ItemList): {len(productos_ld)}")

            if productos_ld:
                # Guardamos tanto el JSON-LD crudo como la versión ya mapeada a OfertaLocal
                ofertas_mapeadas = [_mapear_a_oferta_local(p) for p in productos_ld]
                with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump(
                        {"crudo_json_ld": productos_ld, "mapeado_oferta_local": ofertas_mapeadas},
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
                reporte.append(f"Guardados en '{OUTPUT_JSON_FILE}'.")

                reporte.append("\nPrimeros 3 productos mapeados a OfertaLocal:")
                for oferta in ofertas_mapeadas[:3]:
                    reporte.append(json.dumps(oferta, ensure_ascii=False, indent=2))
            else:
                reporte.append(
                    "\nNo se encontró ningún bloque JSON-LD de tipo ItemList. "
                    "Revisa manualmente 'kemik_debug_search.html' buscando "
                    "'application/ld+json' para confirmar si cambió el formato."
                )

        except PlaywrightTimeoutError as error:
            reporte.append(f"Timeout de navegación con Playwright: {error}")
            logger.error("Timeout: %s", error)
        except PlaywrightError as error:
            reporte.append(f"Error de Playwright: {error}")
            logger.error("Error de Playwright: %s", error)
        finally:
            await context.close()
            await browser.close()

    reporte_texto = "\n".join(reporte)
    with open(OUTPUT_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(reporte_texto)

    print("\n" + "=" * 70)
    print("REPORTE DE DIAGNÓSTICO KEMIK")
    print("=" * 70)
    print(reporte_texto)
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(diagnosticar_kemik())