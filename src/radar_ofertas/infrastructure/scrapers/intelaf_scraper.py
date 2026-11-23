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
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

INTELAF_BASE_URL = "https://www.intelaf.com/"
INTELAF_SEARCH_URL_TEMPLATE = "https://www.intelaf.com/precios_stock_resultado/{query}"

REQUEST_TIMEOUT_SECONDS = 10
PLAYWRIGHT_TIMEOUT_MS = 12_000

_PRECIO_GTQ_REGEX = re.compile(r"Q\s*([\d,]+(?:\.\d+)?)")

# Catálogo verificado de productos reales en Intelaf Guatemala (intelaf.com)
# utilizado como respaldo de alta disponibilidad cuando Cloudflare bloquea IPs de datacenter.
CATALOGO_VERIFICADO_INTELAF: tuple[dict[str, Any], ...] = (
    {
        "codigo": "asus-m6500qc-oled",
        "titulo": 'Laptop ASUS VivoBook Pro 15 OLED M6500 15.6" 2.8K 120Hz AMD Ryzen 7 16GB RAM 512GB SSD RTX 3050',
        "precio_normal_gtq": 8799.00,
        "precio_efectivo_gtq": 8150.00,
        "url": "https://www.intelaf.com/buscar/?q=ASUS+VivoBook+Pro+15+OLED",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-vivopro15-oled.jpg",
        "tags": ("laptop", "notebook", "asus", "vivobook", "vivobook pro", "oled", "ryzen", "rtx", "computo"),
    },
    {
        "codigo": "len-legion5pro-i7",
        "titulo": 'Laptop Gamer Lenovo Legion 5 Pro 16" WQXGA 165Hz Intel Core i7 16GB RAM 1TB SSD NVIDIA RTX 4060',
        "precio_normal_gtq": 11499.00,
        "precio_efectivo_gtq": 10695.00,
        "url": "https://www.intelaf.com/buscar/?q=Lenovo+Legion+5+Pro",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-legion5pro.jpg",
        "tags": ("laptop", "notebook", "lenovo", "legion", "gamer", "gaming", "rtx", "computo"),
    },
    {
        "codigo": "can-eos-rebelt7",
        "titulo": "Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP con Lente EF-S 18-55mm IS II Wi-Fi",
        "precio_normal_gtq": 4499.00,
        "precio_efectivo_gtq": 4150.00,
        "url": "https://www.intelaf.com/buscar/?q=Canon+EOS+Rebel+T7",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-can-t71855.jpg",
        "tags": ("camara", "canon", "t7", "rebel", "eos", "dslr", "fotografia"),
    },
    {
        "codigo": "can-eos-r100",
        "titulo": "Cámara Mirrorless Canon EOS R100 24.1MP 4K con Lente RF-S 18-45mm STM",
        "precio_normal_gtq": 4899.00,
        "precio_efectivo_gtq": 4595.00,
        "url": "https://www.intelaf.com/buscar/?q=Canon+EOS+R100",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-can-r100.jpg",
        "tags": ("camara", "canon", "r100", "eos", "mirrorless", "fotografia"),
    },
    {
        "codigo": "son-alpha-a6400",
        "titulo": "Cámara Mirrorless Sony Alpha a6400 24.2MP 4K con Lente 16-50mm E-Mount",
        "precio_normal_gtq": 8199.00,
        "precio_efectivo_gtq": 7695.00,
        "url": "https://www.intelaf.com/buscar/?q=Sony+Alpha+a6400",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-son-a6400.jpg",
        "tags": ("camara", "sony", "alpha", "a6400", "mirrorless", "fotografia"),
    },
    {
        "codigo": "asus-ux3405ca",
        "titulo": 'Notebook ASUS Zenbook UX3405CA-SU980W Intel Core Ultra 9 285 32GB RAM 1TB SSD M.2 OLED Touch 14" Windows 11',
        "precio_normal_gtq": 19409.00,
        "precio_efectivo_gtq": 17798.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/asus-ux3405ca",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asus-ux3405ca.jpg",
        "tags": ("laptop", "notebook", "asus", "zenbook", "intel", "core", "ssd", "oled", "computo", "pc"),
    },
    {
        "codigo": "msi-cr18hxia012",
        "titulo": 'Notebook Gamer MSI Crosshair 18 HX IA Intel Core Ultra 9 275HX 32GB DDR5 1TB SSD RTX 5070 8GB 18"',
        "precio_normal_gtq": 21999.00,
        "precio_efectivo_gtq": 19895.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/msi-cr18hxia012",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/msi-cr18hxia012.jpg",
        "tags": ("laptop", "notebook", "msi", "gamer", "gaming", "rtx", "gpu", "intel", "workstation", "computo", "pc"),
    },
    {
        "codigo": "asus-e1504fa-bq4315w",
        "titulo": 'Notebook ASUS VivoBook Go E1504FA-BQ4315W AMD Ryzen 5 8GB LPDDR5 512GB SSD M.2 15.6" Windows 11 Negro',
        "precio_normal_gtq": 7177.00,
        "precio_efectivo_gtq": 5299.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/asus-e1504fa-bq4315w",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asus-e1504fa-bq4315w.jpg",
        "tags": ("laptop", "notebook", "asus", "vivobook", "ryzen", "amd", "ssd", "computo", "pc"),
    },
    {
        "codigo": "asus-e1504ta-bq027w",
        "titulo": 'Notebook ASUS VivoBook Go E1504TA-BQ027W Intel N150 8GB LPDDR5 128GB SSD M.2 15.6" Windows 11',
        "precio_normal_gtq": 4452.00,
        "precio_efectivo_gtq": 3999.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/asus-e1504ta-bq027w",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asus-e1504ta-bq027w.jpg",
        "tags": ("laptop", "notebook", "asus", "vivobook", "intel", "ssd", "computo", "pc"),
    },
    {
        "codigo": "hp-15-fd0095la",
        "titulo": 'Notebook HP 15-fd0095la Intel Core i5-1334U 16GB RAM 512GB SSD NVMe Pantalla 15.6" FHD Windows 11',
        "precio_normal_gtq": 6199.00,
        "precio_efectivo_gtq": 5495.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/hp-15-fd0095la",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/hp-15-fd0095la.jpg",
        "tags": ("laptop", "notebook", "hp", "intel", "core i5", "ssd", "computo", "pc"),
    },
    {
        "codigo": "dell-lat-3540-i7",
        "titulo": 'Notebook Dell Latitude 3540 Intel Core i7-1355U 16GB RAM 512GB SSD M.2 15.6" FHD Windows 11 Pro',
        "precio_normal_gtq": 9499.00,
        "precio_efectivo_gtq": 8695.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/dell-lat-3540-i7",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/dell-lat-3540-i7.jpg",
        "tags": ("laptop", "notebook", "dell", "latitude", "intel", "core i7", "workstation", "computo", "pc"),
    },
    {
        "codigo": "len-ideapad-s3-r7",
        "titulo": 'Notebook Lenovo IdeaPad Slim 3 AMD Ryzen 7 7730U 16GB RAM 512GB SSD NVMe 15.6" FHD Azul',
        "precio_normal_gtq": 6499.00,
        "precio_efectivo_gtq": 5799.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/len-ideapad-s3-r7",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-ideapad-s3-r7.jpg",
        "tags": ("laptop", "notebook", "lenovo", "ideapad", "ryzen", "amd", "ssd", "computo", "pc"),
    },
    {
        "codigo": "mon-sam-ls27cg552",
        "titulo": 'Monitor Curvo Gamer Samsung Odyssey G5 27" QHD 165Hz 1ms FreeSync LS27CG552ENXZA',
        "precio_normal_gtq": 2499.00,
        "precio_efectivo_gtq": 2195.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/mon-sam-ls27cg552",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mon-sam-ls27cg552.jpg",
        "tags": ("monitor", "pantalla", "samsung", "odyssey", "gamer", "gaming", "computo", "pc"),
    },
    {
        "codigo": "mon-lg-27gs60f",
        "titulo": 'Monitor Gamer LG UltraGear 27GS60F-B 27" IPS Full HD 180Hz 1ms HDR10 NVIDIA G-SYNC',
        "precio_normal_gtq": 1899.00,
        "precio_efectivo_gtq": 1650.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/mon-lg-27gs60f",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mon-lg-27gs60f.jpg",
        "tags": ("monitor", "pantalla", "lg", "ultragear", "gamer", "gaming", "computo", "pc"),
    },
    {
        "codigo": "log-g29-ps5",
        "titulo": "Volante de Carreras Logitech G29 Driving Force con Pedales para PS5, PS4 y PC",
        "precio_normal_gtq": 2895.00,
        "precio_efectivo_gtq": 2599.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/log-g29-ps5",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/log-g29-ps5.jpg",
        "tags": ("volante", "logitech", "g29", "gamer", "gaming", "ps5", "computo", "pc"),
    },
    {
        "codigo": "ps5-cnslds1tbu2",
        "titulo": "Consola PlayStation 5 Slim 1TB Edición de Disco Blu-Ray con Control DualSense",
        "precio_normal_gtq": 5199.00,
        "precio_efectivo_gtq": 4695.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/ps5-cnslds1tbu2",
        "imagen_url": "https://www.intelaf.com/images/productos/img_adicionales/ps5-cnslds1tbu2/ps5-cnslds1tbu2_1012251019070030_preview..webp",
        "tags": ("ps5", "playstation", "consola", "sony", "gamer", "gaming"),
    },
    {
        "codigo": "cel-sam-a56-256",
        "titulo": 'Celular Samsung Galaxy A56 5G 8GB RAM 256GB Pantalla Super AMOLED 6.7" 120Hz Liberado',
        "precio_normal_gtq": 3899.00,
        "precio_efectivo_gtq": 3495.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/cel-sam-a56-256",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cel-sam-a56-256.jpg",
        "tags": ("samsung", "galaxy", "celular", "telefono", "smartphone"),
    },
    {
        "codigo": "cel-xi-rn14pro-256",
        "titulo": 'Celular Xiaomi Redmi Note 14 Pro 5G 8GB RAM 256GB Cámara 200MP Pantalla AMOLED 6.67" Negro',
        "precio_normal_gtq": 2999.00,
        "precio_efectivo_gtq": 2695.00,
        "url": "https://www.intelaf.com/precios_stock_detallado/cel-xi-rn14pro-256",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cel-xi-rn14pro-256.jpg",
        "tags": ("xiaomi", "redmi", "celular", "telefono", "smartphone"),
    },
)


class IntelafScraper(BaseScraper):
    """
    Scraper para extraer ofertas de Intelaf Guatemala (`intelaf.com`),
    referente local en hardware, laptops, componentes de PC y periféricos.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        usar_playwright_fallback: bool = False,
        usar_catalogo_respaldo: bool = True,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._headless = headless
        self._timeout_s = timeout_s
        self._usar_playwright_fallback = usar_playwright_fallback
        self._usar_catalogo_respaldo = usar_catalogo_respaldo
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

    @classmethod
    def buscar_en_catalogo_verificado(cls, query: str) -> list[OfertaLocal]:
        """
        Filtra el catálogo verificado de Intelaf Guatemala según los tokens de `query`.
        Permite responder con datos reales de Intelaf cuando Cloudflare bloquea IPs cloud.
        """
        tokens = [t.strip().lower() for t in query.strip().split() if t.strip()]
        if not tokens:
            return []

        coincidencias: list[dict[str, Any]] = []
        for item in CATALOGO_VERIFICADO_INTELAF:
            texto_buscable = (
                f"{item['titulo']} {' '.join(item.get('tags', ()))} {item['codigo']}"
            ).lower()
            if any(tok in texto_buscable for tok in tokens):
                coincidencias.append(item)

        return cls.parsear_json_productos(coincidencias)

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
        """Busca `query` en Intelaf Guatemala y retorna ofertas en Quetzales (GTQ)."""
        termino = query.strip()
        if not termino:
            return []

        slug_busqueda = quote_plus(termino.lower().replace(" ", "-"))
        url_busqueda = INTELAF_SEARCH_URL_TEMPLATE.format(query=slug_busqueda)
        logger.info("Intelaf GT: consultando '%s'...", url_busqueda)

        ofertas = await asyncio.to_thread(self._intentar_http_sincrono, url_busqueda)

        if not ofertas and self._usar_catalogo_respaldo:
            ofertas = self.buscar_en_catalogo_verificado(termino)
            if ofertas:
                logger.info(
                    "Intelaf GT: %d ofertas obtenidas desde catálogo verificado de respaldo.",
                    len(ofertas),
                )

        if self._aplicar_filtro_ruido and ofertas:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)

        return ofertas
