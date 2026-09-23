"""
Script de diagnóstico v2 para Kemik.
Corrige la URL de búsqueda (ya no es WooCommerce con ?s=...&post_type=product,
sino una ruta propia /search?query=...) y además intenta extraer el JSON de
productos embebido en el payload de React Server Components (Next.js) para
inspeccionar su estructura real.

Genera 3 archivos:
  - kemik_debug_search.html   -> HTML completo renderizado
  - kemik_debug_products.json -> bloque de productos extraído del payload RSC (si se encuentra)
  - kemik_debug_report.txt    -> resumen legible del diagnóstico

Requiere:
    pip install playwright fake-useragent
    playwright install chromium
"""
import asyncio
import json
import logging
import random
import re

from fake_useragent import UserAgent
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kemik_debug_v2")

KEMIK_BASE_URL = "https://www.kemik.gt/"
KEMIK_SEARCH_URL = "https://www.kemik.gt/search?query=teclado"
NAVIGATION_TIMEOUT_MS = 30_000

OUTPUT_HTML_FILE = "kemik_debug_search.html"
OUTPUT_JSON_FILE = "kemik_debug_products.json"
OUTPUT_REPORT_FILE = "kemik_debug_report.txt"


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


def _extraer_chunks_next_flight(html: str) -> str:
    """
    Next.js empuja los datos de React Server Components (RSC) al cliente via
    self.__next_f.push([1, "..."]) dentro de <script>. Ahí vive el JSON real
    de productos, no en el DOM como <li class="product">.
    Esta función concatena todos esos fragmentos en un solo string.
    """
    patron = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)
    piezas = []
    for match in patron.finditer(html):
        crudo = match.group(1)
        try:
            decodificado = json.loads(f'"{crudo}"')
        except json.JSONDecodeError:
            decodificado = crudo
        piezas.append(decodificado)
    return "".join(piezas)


def _extraer_json_balanceado(texto: str, indice_inicio: int) -> str | None:
    """Dada una posición donde empieza '{' o '[', devuelve el substring
    balanceado (respetando strings y escapes) hasta su cierre correspondiente."""
    profundidad = 0
    dentro_string = False
    escapando = False
    for i in range(indice_inicio, len(texto)):
        ch = texto[i]
        if dentro_string:
            if escapando:
                escapando = False
            elif ch == "\\":
                escapando = True
            elif ch == '"':
                dentro_string = False
            continue
        if ch == '"':
            dentro_string = True
        elif ch in "{[":
            profundidad += 1
        elif ch in "}]":
            profundidad -= 1
            if profundidad == 0:
                return texto[indice_inicio:i + 1]
    return None


def _buscar_bloques_productos(texto_concatenado: str) -> list:
    """Busca todas las apariciones de '"products":[' y extrae cada arreglo balanceado."""
    bloques = []
    for match in re.finditer(r'"products":', texto_concatenado):
        idx_corchete = texto_concatenado.find("[", match.end())
        if idx_corchete == -1:
            continue
        bloque = _extraer_json_balanceado(texto_concatenado, idx_corchete)
        if bloque:
            try:
                data = json.loads(bloque)
                if isinstance(data, list) and data:
                    bloques.append(data)
            except json.JSONDecodeError:
                continue
    return bloques


async def diagnosticar_kemik() -> None:
    user_agent = _get_random_user_agent()
    reporte: list[str] = []

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

            logger.info("Navegando a la URL de búsqueda corregida: %s", KEMIK_SEARCH_URL)
            await page.goto(KEMIK_SEARCH_URL, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            await asyncio.sleep(random.uniform(1.5, 2.5))

            html = await page.content()

            with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("HTML volcado en '%s' (%d caracteres).", OUTPUT_HTML_FILE, len(html))

            reporte.append(f"URL final tras navegación: {page.url}")
            reporte.append(f"Título de la página: {await page.title()}")

            # --- Conteo de selectores candidatos, para comparar enfoques ---
            selectores_candidatos = {
                "ul.products li.product (WooCommerce viejo)": "ul.products li.product",
                "div.product-small (WooCommerce viejo)": "div.product-small",
                "[class*='product']": "[class*='product']",
                "article": "article",
                "a[href]": "a[href]",
            }
            for nombre, selector in selectores_candidatos.items():
                try:
                    count = await page.locator(selector).count()
                except PlaywrightError:
                    count = -1
                reporte.append(f"Selector '{nombre}' -> {count} coincidencias")

            # --- Extracción del payload RSC embebido (donde vive el JSON real) ---
            texto_concatenado = _extraer_chunks_next_flight(html)
            bloques_productos = _buscar_bloques_productos(texto_concatenado)

            if bloques_productos:
                mejor_bloque = max(bloques_productos, key=len)
                with open(OUTPUT_JSON_FILE, "w", encoding="utf-8") as f:
                    json.dump(mejor_bloque, f, ensure_ascii=False, indent=2)
                reporte.append(
                    f"\nSe encontraron {len(bloques_productos)} bloques 'products' en el payload RSC."
                )
                reporte.append(
                    f"El bloque más grande tiene {len(mejor_bloque)} productos "
                    f"y se guardó en '{OUTPUT_JSON_FILE}'."
                )
                if mejor_bloque:
                    reporte.append("\nEjemplo del primer producto encontrado:")
                    reporte.append(json.dumps(mejor_bloque[0], ensure_ascii=False, indent=2)[:1500])
            else:
                reporte.append(
                    "\nNo se encontraron bloques 'products' en el payload RSC. "
                    "Puede que 'teclado' no tenga resultados, o que la clave JSON sea otra "
                    "(revisa kemik_debug_search.html manualmente)."
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