"""
Scraper y Estrategia de Membresía Mayorista para PriceSmart Guatemala
(`https://www.pricesmart.com/en-GT` y `https://www.pricesmart.com/es-gt`).

Arquitectura Técnica y Reglas de Negocio (Mayoreo en Guatemala):
----------------------------------------------------------------
1. Motor de Búsqueda en Vivo (Bloomreach Discovery API):
   - Endpoint: `https://core.dxpapi.com/api/v1/core/`
   - Parámetros de Guatemala:
       * `account_id`: `7024`
       * `domain_key`: `pricesmart_bloomreach_io_es`
       * `view_id`: `GT`
   - El campo `price_GT` viene expresado en centavos de Quetzal (`centAmount / 100`,
     ej. `219995.0` -> `Q2,199.95`), acompañado de `availability_GT` e `inventory_GT`.

2. Casuística de Precios de Membresía:
   - Caso A (`exclusivo_socios`): El precio en Quetzales (GTQ) es visible (`precio_gtq > 0`),
     pero requiere membresía activa de PriceSmart. Se etiqueta con `requiere_membresia=True`
     y `estado_precio_membresia="exclusivo_socios"`.
   - Caso B (`oculto_requiere_login`): En artículos donde el portal exige iniciar sesión
     de socio para revelar el precio (`precio <= 0` o `hidePrice=True`), el scraper jamás
     inyecta `Q0.00` en el ranking general para no distorsionar la insignia de "Mejor Precio".
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

PRICESMART_GT_BASE_URL = "https://www.pricesmart.com/en-GT/"
PRICESMART_SEARCH_TEMPLATE = "https://www.pricesmart.com/en-GT/search?q={query}"
PRICESMART_BLOOMREACH_API_URL = "https://core.dxpapi.com/api/v1/core/"

PRICESMART_BLOOMREACH_ACCOUNT_ID = "7024"
PRICESMART_BLOOMREACH_DOMAIN_KEY = "pricesmart_bloomreach_io_es"
PRICESMART_BLOOMREACH_VIEW_ID = "GT"
PRICESMART_BLOOMREACH_FL = (
    "pid,title,brand,price,price_GT,availability_GT,inventory_GT,"
    "thumb_image,slug,skuid,master_sku,sign_price_GT,saving_amount_GT"
)

_PRECIO_GTQ_REGEX = re.compile(r"[\d,]+(?:\.\d+)?")
REQUEST_TIMEOUT_SECONDS = 12


class PriceSmartScraper(BaseScraper):
    """
    Scraper asíncrono para PriceSmart Guatemala (`pricesmart.com/en-GT` y `/es-gt`).
    Extrae artículos de mayoreo con etiqueta de socio (`requiere_membresia=True`)
    desde la API Bloomreach Discovery de Guatemala y protege el ranking cuando
    un artículo requiere inicio de sesión para mostrar su precio.
    """

    def __init__(
        self,
        max_resultados: int = 15,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        incluir_precios_ocultos: bool = False,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._max_resultados = max_resultados
        self._timeout_s = timeout_s
        self._incluir_precios_ocultos = incluir_precios_ocultos
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
    def parsear_item_mayorista(
        cls,
        item: dict[str, Any],
        incluir_precios_ocultos: bool = False,
        base_url: str = PRICESMART_GT_BASE_URL,
    ) -> OfertaLocal | None:
        """
        Traduce un registro de producto de PriceSmart GT (proveniente de Bloomreach
        Discovery `core.dxpapi.com`, `__NEXT_DATA__` o JSON-LD) a una entidad
        `OfertaLocal` con etiqueta de membresía (`requiere_membresia=True`).
        """
        try:
            # Verificar disponibilidad en Guatemala si vienen banderas de Bloomreach
            avail_gt = str(item.get("availability_GT") or "true").strip().lower()
            inv_gt = str(item.get("inventory_GT") or "in stock").strip().lower()
            if avail_gt == "false" or inv_gt == "out of stock":
                return None

            titulo = " ".join(
                str(
                    item.get("title")
                    or item.get("name")
                    or item.get("productName")
                    or ""
                ).split()
            )
            pid = str(item.get("pid") or item.get("master_sku") or "").strip()
            slug = str(item.get("slug") or "").strip().strip("/")
            url_raw = str(item.get("url") or item.get("pdpUrl") or "").strip()

            if not titulo:
                return None

            if slug and pid and (not url_raw or "/site/cr/" in url_raw):
                url_absoluta = f"https://www.pricesmart.com/en-GT/product/{slug}/{pid}"
            elif slug and not url_raw:
                url_absoluta = urljoin(base_url, f"product/{slug}")
            elif url_raw:
                url_absoluta = urljoin(base_url, url_raw)
            else:
                return None

            imagen_raw = (
                item.get("thumb_image")
                or item.get("image")
                or item.get("imageUrl")
                or item.get("thumbnail")
                or ""
            )
            if isinstance(imagen_raw, list):
                imagen_raw = imagen_raw[0] if imagen_raw else ""
            imagen_url = (
                urljoin(base_url, str(imagen_raw).strip()) if imagen_raw else ""
            )

            requiere_login = bool(
                item.get("hidePrice")
                or item.get("memberOnlyPriceHidden")
                or item.get("requiresMemberLogin")
            )

            precio_gtq = 0.0
            if not requiere_login:
                # 1. Campo nativo centAmount de Bloomreach Guatemala (`price_GT`)
                if item.get("price_GT") is not None:
                    raw_cent = float(item["price_GT"])
                    precio_gtq = raw_cent / 100.0 if raw_cent > 0 else 0.0
                else:
                    # 2. Campos directos en Quetzales (`price_gtq`, `memberPrice`, `price`, `salePrice`)
                    precio_raw = (
                        item.get("price_gtq")
                        or item.get("memberPrice")
                        or item.get("price")
                        or item.get("salePrice")
                    )
                    if precio_raw is not None:
                        if isinstance(precio_raw, (int, float)):
                            precio_gtq = float(precio_raw)
                        else:
                            coincidencia = _PRECIO_GTQ_REGEX.search(str(precio_raw))
                            if coincidencia:
                                precio_gtq = float(
                                    coincidencia.group(0).replace(",", "")
                                )

            if precio_gtq <= 0 or requiere_login:
                if not incluir_precios_ocultos:
                    logger.debug(
                        "PriceSmart GT: omitiendo '%s' del ranking numérico (requiere login de socio para ver precio).",
                        titulo,
                    )
                    return None
                return OfertaLocal(
                    tienda="PriceSmart",
                    titulo=titulo,
                    precio_gtq=0.0,
                    url=url_absoluta,
                    imagen_url=imagen_url,
                    requiere_membresia=True,
                    estado_precio_membresia="oculto_requiere_login",
                )

            return OfertaLocal(
                tienda="PriceSmart",
                titulo=titulo,
                precio_gtq=round(precio_gtq, 2),
                url=url_absoluta,
                imagen_url=imagen_url,
                requiere_membresia=True,
                estado_precio_membresia="exclusivo_socios",
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning(
                "PriceSmart GT: fallo mapeando producto mayorista: %s", error
            )
            return None

    @classmethod
    def parsear_respuesta_bloomreach(
        cls,
        raw_data: str | dict[str, Any],
        incluir_precios_ocultos: bool = False,
        base_url: str = PRICESMART_GT_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON de Bloomreach Discovery (`response.docs`)
        de PriceSmart Guatemala en una lista de `OfertaLocal`.
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

        docs = (payload.get("response") or {}).get("docs") or []
        if not isinstance(docs, list):
            return []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            oferta = cls.parsear_item_mayorista(
                doc,
                incluir_precios_ocultos=incluir_precios_ocultos,
                base_url=base_url,
            )
            if oferta is not None and oferta.url not in urls_vistas:
                urls_vistas.add(oferta.url)
                ofertas.append(oferta)

        return ofertas

    @classmethod
    def parsear_html_o_next_data(
        cls,
        html: str,
        incluir_precios_ocultos: bool = False,
        base_url: str = PRICESMART_GT_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Extrae ofertas desde `__NEXT_DATA__` o HTML de PriceSmart GT, garantizando
        que ningún producto con precio oculto por membresía contamine el ranking con `Q0.00`.
        """
        if not html or not html.strip():
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []

        script_next = soup.select_one("script#__NEXT_DATA__")
        if script_next and script_next.string:
            try:
                data = json.loads(script_next.string)
                page_props = (data.get("props") or {}).get("pageProps") or {}
                productos_raw = (
                    page_props.get("products")
                    or page_props.get("searchResults")
                    or []
                )
                if isinstance(productos_raw, list):
                    for item in productos_raw:
                        if isinstance(item, dict):
                            oferta = cls.parsear_item_mayorista(
                                item,
                                incluir_precios_ocultos=incluir_precios_ocultos,
                                base_url=base_url,
                            )
                            if oferta is not None:
                                ofertas.append(oferta)
            except json.JSONDecodeError:
                pass

        return ofertas

    def _consultar_bloomreach_sincrono(self, query: str) -> list[OfertaLocal]:
        params = urllib.parse.urlencode(
            {
                "account_id": PRICESMART_BLOOMREACH_ACCOUNT_ID,
                "domain_key": PRICESMART_BLOOMREACH_DOMAIN_KEY,
                "view_id": PRICESMART_BLOOMREACH_VIEW_ID,
                "request_type": "search",
                "search_type": "keyword",
                "q": query,
                "rows": str(self._max_resultados),
                "start": "0",
                "fl": PRICESMART_BLOOMREACH_FL,
                "_br_uid_2": "uid=7024123456:v=12.0:ts=1700000000:hc=1",
                "url": PRICESMART_SEARCH_TEMPLATE.format(query=quote_plus(query)),
                "ref_url": PRICESMART_GT_BASE_URL,
                "request_id": "1700000000000",
            }
        )
        url_api = f"{PRICESMART_BLOOMREACH_API_URL}?{params}"
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "application/json",
            "Origin": "https://www.pricesmart.com",
            "Referer": "https://www.pricesmart.com/en-GT/",
        }
        req = urllib.request.Request(url_api, headers=headers, method="GET")
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self._timeout_s, context=ctx) as resp:
            raw_bytes = resp.read()
            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)
            raw_text = raw_bytes.decode("utf-8", errors="ignore")
            return self.parsear_respuesta_bloomreach(
                raw_text,
                incluir_precios_ocultos=self._incluir_precios_ocultos,
            )

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """
        Consulta el catálogo de mayoreo de PriceSmart Guatemala (`pricesmart.com/en-GT`)
        y retorna ofertas etiquetadas con `requiere_membresia=True`.
        """
        termino = query.strip()
        if not termino:
            return []

        url_busqueda = PRICESMART_SEARCH_TEMPLATE.format(query=quote_plus(termino))
        logger.info(
            "PriceSmart GT (Mayoreo): consultando club '%s'...",
            url_busqueda,
        )
        try:
            ofertas = await asyncio.to_thread(
                self._consultar_bloomreach_sincrono, termino
            )
            if self._aplicar_filtro_ruido and ofertas:
                ofertas = filtrar_ofertas_relevantes(ofertas, termino)
            logger.info(
                "PriceSmart GT: %d ofertas de socio extraídas correctamente.",
                len(ofertas),
            )
            return ofertas
        except Exception as error:
            logger.warning(
                "PriceSmart GT: fallo controlado en consulta mayorista: %s", error
            )
            return []
