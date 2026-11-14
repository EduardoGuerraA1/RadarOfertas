"""
Implementación concreta de BaseScraper para La Curacao Guatemala (lacuracaonline.com/guatemala).
Especializada en Línea Blanca, Electrodomésticos, Pantallas Smart TV, Cómputo y Smartphones.

Arquitectura técnica de La Curacao Guatemala (`https://www.lacuracaonline.com/guatemala`):
  - Plataforma: Adobe Commerce (Magento 2) + Adobe LiveSearch GraphQL (`https://catalog-service.adobe.io/graphql`).
  - Cabeceras de contexto Guatemala:
      * `Magento-Environment-Id`: `b0453fee-9cca-41d9-930c-0a94fd84b9bd`
      * `Magento-Website-Code`: `lco_guatemala_w`
      * `Magento-Store-Code`: `lco_guatemala_s`
      * `Magento-Store-View-Code`: `lco_guatemala_sv`
      * `x-api-key`: `2999e5a23078490096b15ef87ccc499c`
  - Respaldo secundario: Tarjetas HTML de Magento 2 en `/guatemala/catalogsearch/result/?q={query}`.
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

from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

LACURACAO_BASE_URL = "https://www.lacuracaonline.com/guatemala/"
LACURACAO_LIVESEARCH_URL = "https://catalog-service.adobe.io/graphql"
LACURACAO_SEARCH_HTML_TEMPLATE = (
    "https://www.lacuracaonline.com/guatemala/catalogsearch/result/?q={query}"
)

LACURACAO_HEADERS_ADOBE: dict[str, str] = {
    "Magento-Environment-Id": "b0453fee-9cca-41d9-930c-0a94fd84b9bd",
    "Magento-Website-Code": "lco_guatemala_w",
    "Magento-Store-Code": "lco_guatemala_s",
    "Magento-Store-View-Code": "lco_guatemala_sv",
    "Magento-Customer-Group": "b6589fc6ab0dc82cf12099d1c2d40ab994e8410c",
    "x-api-key": "2999e5a23078490096b15ef87ccc499c",
}

_LIVESEARCH_GRAPHQL_QUERY = """
query BuscarProductosLaCuracao($phrase: String!, $pageSize: Int!) {
  productSearch(
    phrase: $phrase,
    page_size: $pageSize,
    filter: [{ attribute: "inStock", eq: "true" }]
  ) {
    items {
      product {
        name
        sku
        canonical_url
        small_image {
          url
        }
        image {
          url
        }
        price_range {
          minimum_price {
            final_price {
              value
              currency
            }
            regular_price {
              value
              currency
            }
          }
        }
      }
      productView {
        name
        sku
        url
        urlKey
        inStock
        images {
          url
        }
      }
    }
  }
}
"""

_PRECIO_REGEX = re.compile(r"[\d,]+(?:\.\d+)?")
REQUEST_TIMEOUT_SECONDS = 12


class LaCuracaoScraper(BaseScraper):
    """
    Scraper asíncrono para La Curacao Guatemala (`lacuracaonline.com/guatemala`).
    Extrae precios oficiales en Quetzales (GTQ) para línea blanca, pantallas y tecnología.
    """

    def __init__(
        self,
        max_resultados: int = 16,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._max_resultados = max_resultados
        self._timeout_s = timeout_s
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

    @staticmethod
    def _normalizar_url_lacuracao(raw_url: str, base_url: str = LACURACAO_BASE_URL) -> str:
        limpia = (raw_url or "").strip()
        if not limpia:
            return ""
        if limpia.startswith("//"):
            return f"https:{limpia}"
        if limpia.startswith(("http://", "https://")):
            return limpia
        return urljoin(base_url, limpia.lstrip("/"))

    @classmethod
    def parsear_respuesta_livesearch(
        cls,
        raw_data: str | dict[str, Any],
        base_url: str = LACURACAO_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Traduce la respuesta de Adobe Commerce LiveSearch (`data.productSearch.items`)
        de La Curacao Guatemala a entidades `OfertaLocal`.
        """
        if isinstance(raw_data, str):
            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                return []
        else:
            payload = raw_data

        if not isinstance(payload, dict):
            return []

        items = (
            ((payload.get("data") or {}).get("productSearch") or {}).get("items")
            or []
        )
        if not isinstance(items, list):
            return []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for entry in items:
            if not isinstance(entry, dict):
                continue
            product = entry.get("product") or {}
            product_view = entry.get("productView") or {}
            if not isinstance(product, dict):
                product = {}
            if not isinstance(product_view, dict):
                product_view = {}

            titulo_raw = (
                product.get("name")
                or product_view.get("name")
                or ""
            )
            titulo = " ".join(str(titulo_raw).split())
            if not titulo:
                continue

            url_raw = (
                product.get("canonical_url")
                or product_view.get("url")
                or product_view.get("urlKey")
                or ""
            )
            url_absoluta = cls._normalizar_url_lacuracao(str(url_raw), base_url=base_url)
            if not url_absoluta or url_absoluta in urls_vistas:
                continue

            # Extraer precio final en GTQ
            min_price = (
                (product.get("price_range") or {}).get("minimum_price") or {}
            )
            final_price_obj = min_price.get("final_price") or {}
            regular_price_obj = min_price.get("regular_price") or {}
            precio_val = (
                final_price_obj.get("value")
                if final_price_obj.get("value") is not None
                else regular_price_obj.get("value")
            )
            if precio_val is None:
                continue

            try:
                precio_gtq = float(precio_val)
            except (ValueError, TypeError):
                continue

            if precio_gtq <= 0:
                continue

            # Extraer imagen
            small_img = (product.get("small_image") or {}).get("url")
            main_img = (product.get("image") or {}).get("url")
            view_imgs = product_view.get("images") or []
            view_img_url = (
                view_imgs[0].get("url")
                if isinstance(view_imgs, list)
                and view_imgs
                and isinstance(view_imgs[0], dict)
                else ""
            )
            imagen_url = cls._normalizar_url_lacuracao(
                str(small_img or main_img or view_img_url or ""),
                base_url=base_url,
            )

            urls_vistas.add(url_absoluta)
            ofertas.append(
                OfertaLocal(
                    tienda="La Curacao",
                    titulo=titulo,
                    precio_gtq=round(precio_gtq, 2),
                    url=url_absoluta,
                    imagen_url=imagen_url,
                )
            )

        return ofertas

    @classmethod
    def parsear_html_busqueda(
        cls, html: str, base_url: str = LACURACAO_BASE_URL
    ) -> list[OfertaLocal]:
        """Respaldo para extraer productos desde HTML Magento de La Curacao."""
        if not html or not html.strip():
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for card in soup.select("li.product-item, div.product-item-info"):
            enlace = card.select_one("a.product-item-link") or card.select_one("a[href]")
            if enlace is None:
                continue
            titulo = " ".join(
                str(enlace.get("title") or enlace.get_text(" ", strip=True)).split()
            )
            href = cls._normalizar_url_lacuracao(
                str(enlace.get("href") or ""), base_url=base_url
            )
            if not titulo or not href or href in urls_vistas:
                continue

            precio_gtq: float | None = None
            nodo_monto = card.select_one("[data-price-amount]")
            if nodo_monto and nodo_monto.get("data-price-amount"):
                try:
                    precio_gtq = float(str(nodo_monto.get("data-price-amount")))
                except ValueError:
                    precio_gtq = None

            if precio_gtq is None:
                nodo_precio = card.select_one(".price")
                if nodo_precio:
                    match = _PRECIO_REGEX.search(nodo_precio.get_text(" ", strip=True))
                    if match:
                        try:
                            precio_gtq = float(match.group(0).replace(",", ""))
                        except ValueError:
                            precio_gtq = None

            if precio_gtq is None or precio_gtq <= 0:
                continue

            img = card.select_one("img.product-image-photo, img[src]")
            imagen_url = (
                cls._normalizar_url_lacuracao(
                    str(img.get("data-src") or img.get("src") or ""),
                    base_url=base_url,
                )
                if img
                else ""
            )

            urls_vistas.add(href)
            ofertas.append(
                OfertaLocal(
                    tienda="La Curacao",
                    titulo=titulo,
                    precio_gtq=round(precio_gtq, 2),
                    url=href,
                    imagen_url=imagen_url,
                )
            )

        return ofertas

    def _consultar_livesearch_sincrono(self, query: str) -> list[OfertaLocal]:
        payload = json.dumps(
            {
                "query": _LIVESEARCH_GRAPHQL_QUERY,
                "variables": {
                    "phrase": query,
                    "pageSize": self._max_resultados,
                },
            }
        ).encode("utf-8")

        headers = {
            **LACURACAO_HEADERS_ADOBE,
            "User-Agent": self._get_random_user_agent(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.lacuracaonline.com",
            "Referer": "https://www.lacuracaonline.com/guatemala/",
        }

        req = urllib.request.Request(
            LACURACAO_LIVESEARCH_URL,
            data=payload,
            headers=headers,
            method="POST",
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self._timeout_s, context=ctx) as resp:
            raw_bytes = resp.read()
            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)
            raw_text = raw_bytes.decode("utf-8", errors="ignore")
            return self.parsear_respuesta_livesearch(raw_text)

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en La Curacao Guatemala y retorna ofertas en Quetzales (GTQ)."""
        termino = query.strip()
        if not termino:
            return []

        logger.info("La Curacao GT: consultando LiveSearch para '%s'...", termino)
        try:
            ofertas = await asyncio.to_thread(
                self._consultar_livesearch_sincrono, termino
            )
            if self._aplicar_filtro_ruido:
                ofertas = filtrar_ofertas_relevantes(ofertas, termino)
            logger.info("La Curacao GT: %d ofertas extraídas correctamente.", len(ofertas))
            return ofertas
        except Exception as error:
            logger.warning("La Curacao GT: fallo controlado en consulta: %s", error)
            return []
