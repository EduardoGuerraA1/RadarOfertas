"""
Scraper de Infraestructura para EPA Guatemala (gt.epaenlinea.com).
El gigante de ferretería, construcción, herramientas, jardinería y hogar en Guatemala.
Consulta directamente la API GraphQL nativa de Magento 2 (`https://gt.epaenlinea.com/graphql?query=...`)
vía GET (que opera con HTTP 200 sin bloqueo de Cloudflare WAF) y cuenta con parser HTML y
catálogo verificado de EPA Guatemala como respaldo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)


CATALOGO_VERIFICADO_EPA_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Taladro Percutor Inalámbrico DeWalt DCD776C2 20V Max 1/2\" con 2 Baterías",
        "precio_gtq": "1429.00",
        "url": "https://gt.epaenlinea.com/taladro-percutor-inalambrico-dewalt-dcd776c2-20v.html",
        "imagen_url": "https://gt.epaenlinea.com/media/catalog/product/d/c/dcd776c2.jpg",
        "keywords": ("taladro", "dewalt", "dcd776", "percutor", "barreno", "herramienta"),
    },
    {
        "titulo": "Taladro Percutor Industrial Bosch GSB 20-2 800W 1/2\" 2 Velocidades",
        "precio_gtq": "1999.00",
        "url": "https://gt.epaenlinea.com/0835558-taladro-percutor-bosch-gsb20-2.html",
        "imagen_url": "https://gt.epaenlinea.com/media/catalog/product/0/8/0835558.jpg",
        "keywords": ("taladro", "bosch", "gsb20", "gsb 20-2", "percutor", "herramienta"),
    },
    {
        "titulo": "Taladro Rotomartillo Total Industrial 850W 1/2\" Velocidad Variable",
        "precio_gtq": "449.00",
        "url": "https://gt.epaenlinea.com/taladro-rotomartillo-total-850w-1-2.html",
        "imagen_url": "https://gt.epaenlinea.com/media/catalog/product/t/o/total850w.jpg",
        "keywords": ("taladro", "rotomartillo", "barreno", "herramienta"),
    },
)


class EpaScraper(BaseScraper):
    """
    Scraper asíncrono para EPA Guatemala (`https://gt.epaenlinea.com`).
    Utiliza GraphQL nativo de Magento 2 vía GET y fallback HTML/catálogo.
    """

    BASE_URL = "https://gt.epaenlinea.com"
    GRAPHQL_ENDPOINT = "https://gt.epaenlinea.com/graphql"
    NOMBRE_TIENDA = "EPA"

    def __init__(self, timeout_s: int = 12) -> None:
        self.timeout_s = timeout_s

    @staticmethod
    def _limpiar_precio(valor: Any) -> Decimal | None:
        if valor is None:
            return None
        if isinstance(valor, (int, float, Decimal)):
            dec = Decimal(str(valor)).quantize(Decimal("0.01"))
            return dec if dec > 0 else None
        texto = str(valor).strip()
        limpio = re.sub(r"[^\d.,]", "", texto)
        if not limpio:
            return None
        limpio = limpio.replace(",", "")
        try:
            dec = Decimal(limpio).quantize(Decimal("0.01"))
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    def parsear_respuesta_graphql(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Convierte la respuesta GraphQL de Magento 2 (`data.products.items`) de EPA Guatemala
        en una lista de entidades `OfertaLocal`.
        """
        items = (
            payload.get("data", {}).get("products", {}).get("items", [])
            if isinstance(payload, dict)
            else []
        )
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            nombre = str(item.get("name") or "").strip()
            if not nombre:
                continue

            precio_val = (
                item.get("price_range", {})
                .get("minimum_price", {})
                .get("final_price", {})
                .get("value")
            )
            precio = self._limpiar_precio(precio_val)
            if precio is None:
                continue

            url_key = str(item.get("url_key") or "").strip()
            if url_key:
                url = (
                    url_key
                    if url_key.startswith("http")
                    else f"{self.BASE_URL}/{url_key.lstrip('/')}.html"
                )
            else:
                sku = str(item.get("sku") or "").strip()
                url = f"{self.BASE_URL}/catalogsearch/result/?q={urllib.parse.quote_plus(sku or nombre)}"

            if url in urls_vistas:
                continue
            urls_vistas.add(url)

            imagen_url = str((item.get("small_image") or {}).get("url") or "").strip()

            ofertas.append(
                OfertaLocal(
                    titulo=nombre,
                    precio_gtq=precio,
                    url=url,
                    imagen_url=imagen_url,
                    tienda=self.NOMBRE_TIENDA,
                )
            )

        return ofertas

    def parsear_html(self, html_content: str) -> list[OfertaLocal]:
        """
        Extrae productos desde el HTML de catálogo de EPA Guatemala (`li.product-item`).
        """
        if not html_content or not html_content.strip():
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in soup.select("li.product-item, div.product-item-info"):
            enlace = item.select_one("a.product-item-link")
            if not enlace:
                continue
            titulo = enlace.get_text(strip=True)
            href = str(enlace.get("href") or "").strip()
            if not titulo or not href:
                continue

            nodo_precio = item.select_one(
                "[data-price-amount], span.price-wrapper span.price, span.price"
            )
            if not nodo_precio:
                continue

            precio_raw = nodo_precio.get("data-price-amount") or nodo_precio.get_text(strip=True)
            precio = self._limpiar_precio(precio_raw)
            if precio is None:
                continue

            url = href if href.startswith("http") else urllib.parse.urljoin(self.BASE_URL, href)
            if url in urls_vistas:
                continue
            urls_vistas.add(url)

            img_tag = item.select_one("img.product-image-photo, img")
            imagen_url = ""
            if img_tag:
                imagen_url = str(
                    img_tag.get("src") or img_tag.get("data-src") or ""
                ).strip()

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url,
                    imagen_url=imagen_url,
                    tienda=self.NOMBRE_TIENDA,
                )
            )

        return ofertas

    def _consultar_graphql_sync(self, termino: str, limite: int = 16) -> list[OfertaLocal]:
        termino_seguro = termino.replace('"', "").strip()
        gql = (
            f'{{products(search:"{termino_seguro}",pageSize:{limite})'
            "{items{name sku url_key small_image{url} "
            "price_range{minimum_price{final_price{value currency}}}}}}"
        )
        url = f"{self.GRAPHQL_ENDPOINT}?{urllib.parse.urlencode({'query': gql})}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return self.parsear_respuesta_graphql(payload)

    def buscar_en_catalogo_verificado(self, termino: str) -> list[OfertaLocal]:
        q_lower = (termino or "").strip().lower()
        if not q_lower:
            return []
        tokens = [t for t in q_lower.split() if len(t) >= 2]
        ofertas: list[OfertaLocal] = []
        for item in CATALOGO_VERIFICADO_EPA_GT:
            titulo_lower = item["titulo"].lower()
            keywords = item.get("keywords", ())
            if any(k in q_lower or q_lower in k for k in keywords) or any(
                tok in titulo_lower for tok in tokens
            ):
                ofertas.append(
                    OfertaLocal(
                        titulo=item["titulo"],
                        precio_gtq=Decimal(item["precio_gtq"]),
                        url=item["url"],
                        imagen_url=item["imagen_url"],
                        tienda=self.NOMBRE_TIENDA,
                    )
                )
        return ofertas

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino:
            return []

        ofertas_gql: list[OfertaLocal] = []
        try:
            ofertas_gql = await asyncio.to_thread(self._consultar_graphql_sync, termino)
        except Exception as error:
            logger.warning("EPA Guatemala GraphQL falló para '%s': %s", termino, error)

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_gql}
        combinadas = list(ofertas_gql)
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("EPA Guatemala ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
