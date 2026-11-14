"""
Implementación concreta de BaseScraper para Tienda Claro Guatemala (claro.com.gt).
Foco principal: Smartphones (Prepago, Postpago y Renovaciones), Smartwatches y Equipos Claro Hogar.

Arquitectura técnica de Tienda Claro Guatemala:
  1. Tienda en Línea Salesforce Commerce Cloud PWA (`https://ak-staging-www.claro.com.gt/personas/tiendaenlinea/search?q={query}`
     y `https://www.claro.com.gt/personas/tiendaenlinea/search?q={query}`):
     - Hidrata un estado JSON en `<script>` con `__PRELOADED_STATE__.__reactQuery.queries`.
     - Contiene el resultado de `/product-search` con `hits` en Quetzales (`currency: "GTQ"`),
       precio de venta (`c_custom.salePrice` o `price`), ruta `c_slugUrl` e imagen oficial en
       `https://sf-api-prd.claro.com.gt/...`.
  2. Catálogo Prepago Claro GT (`/personas/servicios/servicios-moviles/prepago/catalogo-prepago/{marca}/`):
     - Tarjetas HTML `.c51_v2InfoCarText` con nombre de modelo (`<h3>`), precio en Quetzales
       (`.c51_v2InfoCarPrice strong`) e imagen en `#ImagenesComponenteC51 img`.
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

CLARO_PUBLIC_BASE_URL = "https://www.claro.com.gt"
CLARO_AKAMAI_ORIGIN_BASE_URL = "https://ak-staging-www.claro.com.gt"

CLARO_TIENDA_SEARCH_TEMPLATE = (
    "{base}/personas/tiendaenlinea/search?q={query}"
)
CLARO_CATALOGO_PREPAGO_TEMPLATE = (
    "{base}/personas/servicios/servicios-moviles/prepago/catalogo-prepago/{marca}/"
)

MARCAS_PREPAGO_CLARO: tuple[str, ...] = (
    "samsung",
    "iphone",
    "xiaomi",
    "motorola",
    "honor",
    "tcl",
    "zte",
)

_PRECIO_GTQ_REGEX = re.compile(r"Q\s*([\d,]+(?:\.\d+)?)")
REQUEST_TIMEOUT_SECONDS = 12


class ClaroScraper(BaseScraper):
    """
    Scraper asíncrono para Tienda Claro Guatemala (`claro.com.gt`).
    Extrae precios oficiales de smartphones y equipos móviles en Quetzales (GTQ).
    """

    def __init__(
        self,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
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

    @classmethod
    def parsear_hits_sfcc(
        cls,
        hits: list[dict[str, Any]],
        base_url: str = CLARO_PUBLIC_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Convierte la lista de `hits` de Salesforce Commerce Cloud (`__reactQuery`)
        de Tienda Claro GT en entidades `OfertaLocal`.
        """
        if not isinstance(hits, list):
            return []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for hit in hits:
            if not isinstance(hit, dict):
                continue
            try:
                custom = hit.get("c_custom") or {}
                if not isinstance(custom, dict):
                    custom = {}

                image_obj = hit.get("image") or {}
                if not isinstance(image_obj, dict):
                    image_obj = {}

                titulo_raw = (
                    hit.get("productName")
                    or image_obj.get("alt")
                    or ""
                )
                titulo = " ".join(str(titulo_raw).split())
                if not titulo:
                    continue

                # Añadir capacidad o color si no están en el título
                storage = str(hit.get("c_cen_storage") or "").strip()
                if storage and storage.lower() not in titulo.lower():
                    titulo = f"{titulo} {storage}"

                # Priorizar salePrice o listPrice de equipo completo sobre pago inicial de plan
                sale_price = custom.get("salePrice")
                list_price = custom.get("listPrice")
                hit_price = hit.get("price")

                precio_gtq = 0.0
                if isinstance(sale_price, (int, float)) and float(sale_price) > 0:
                    precio_gtq = float(sale_price)
                elif isinstance(list_price, (int, float)) and float(list_price) > 0:
                    precio_gtq = float(list_price)
                elif (
                    isinstance(hit_price, (int, float))
                    and float(hit_price) > 0
                    and str(hit.get("hitType") or "") != "master"
                ):
                    precio_gtq = float(hit_price)

                if precio_gtq <= 0:
                    continue

                slug_url = str(hit.get("c_slugUrl") or "").strip()
                product_id = str(hit.get("productId") or custom.get("id") or "").strip()
                if slug_url:
                    url_absoluta = urljoin(base_url, slug_url)
                elif product_id:
                    url_absoluta = (
                        f"{base_url.rstrip('/')}/personas/tiendaenlinea/product/{product_id}.html"
                    )
                else:
                    continue

                if url_absoluta in urls_vistas:
                    continue

                imagen_url = str(
                    image_obj.get("link")
                    or image_obj.get("disBaseLink")
                    or custom.get("imageSku")
                    or ""
                ).strip()
                if imagen_url:
                    imagen_url = urljoin(base_url, imagen_url)

                urls_vistas.add(url_absoluta)
                ofertas.append(
                    OfertaLocal(
                        tienda="Tienda Claro",
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
    def parsear_html_tienda_claro(
        cls,
        html: str,
        base_url: str = CLARO_PUBLIC_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Extrae ofertas desde el HTML de Tienda Claro GT:
          1. Bloque JSON hidratado de Salesforce Commerce Cloud (`__PRELOADED_STATE__.__reactQuery`).
          2. Bloques HTML del Catálogo Prepago (`.c51_v2InfoCarText`).
        """
        if not html or not html.strip():
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        # 1. Buscar estado hidratado Salesforce Commerce Cloud PWA
        for script in soup.find_all("script"):
            texto = (script.string or "").strip()
            if not texto.startswith('{"__INITIAL_CORRELATION_ID__'):
                continue
            try:
                data = json.loads(texto)
                queries = (
                    ((data.get("__PRELOADED_STATE__") or {}).get("__reactQuery") or {})
                    .get("queries")
                    or []
                )
                for q_obj in queries:
                    if not isinstance(q_obj, dict):
                        continue
                    q_data = (q_obj.get("state") or {}).get("data") or {}
                    if isinstance(q_data, dict) and isinstance(q_data.get("hits"), list):
                        for oferta in cls.parsear_hits_sfcc(
                            q_data["hits"], base_url=base_url
                        ):
                            if oferta.url not in urls_vistas:
                                urls_vistas.add(oferta.url)
                                ofertas.append(oferta)
            except json.JSONDecodeError:
                continue

        if ofertas:
            return ofertas

        # 2. Buscar tarjetas del Catálogo Prepago (.c51_v2InfoCarText)
        for idx, card in enumerate(soup.select("div.c51_v2InfoCarText"), 1):
            nodo_titulo = card.select_one("h3, h2")
            if nodo_titulo is None:
                continue
            titulo_base = " ".join(nodo_titulo.get_text(" ", strip=True).split())
            if not titulo_base:
                continue

            # Extraer especificaciones breves si existen en la tabla
            specs = [
                td.get_text(" ", strip=True)
                for td in card.select("table td")
                if td.get_text(" ", strip=True)
            ]
            resumen_spec = ""
            for spec in specs:
                if any(k in spec.upper() for k in ("GB", "5G", "4G")):
                    resumen_spec = spec
                    break

            titulo = (
                f"{titulo_base} ({resumen_spec}) — Prepago Claro"
                if resumen_spec and resumen_spec.lower() not in titulo_base.lower()
                else f"{titulo_base} — Prepago Claro"
            )

            nodo_precio = card.select_one(".c51_v2InfoCarPrice strong") or card.select_one(
                ".c51_v2InfoCarPrice"
            )
            if nodo_precio is None:
                continue
            match_precio = _PRECIO_GTQ_REGEX.search(
                nodo_precio.get_text(" ", strip=True)
            )
            if not match_precio:
                continue

            try:
                precio_gtq = float(match_precio.group(1).replace(",", ""))
            except ValueError:
                continue

            if precio_gtq <= 0:
                continue

            img_node = card.select_one("#ImagenesComponenteC51 img") or card.select_one("img")
            imagen_url = ""
            if img_node is not None:
                raw_img = str(
                    img_node.get("data-src") or img_node.get("src") or ""
                ).strip()
                if raw_img:
                    imagen_url = urljoin(base_url, raw_img)

            slug_modelo = re.sub(r"[^a-z0-9]+", "-", titulo_base.lower()).strip("-")
            url_oferta = (
                f"{base_url.rstrip('/')}/personas/servicios/servicios-moviles/"
                f"prepago/catalogo-prepago/#{slug_modelo or idx}"
            )
            if url_oferta not in urls_vistas:
                urls_vistas.add(url_oferta)
                ofertas.append(
                    OfertaLocal(
                        tienda="Tienda Claro",
                        titulo=titulo,
                        precio_gtq=round(precio_gtq, 2),
                        url=url_oferta,
                        imagen_url=imagen_url,
                    )
                )

        return ofertas

    def _descargar_html_sincrono(self, url: str) -> str:
        headers = {
            "User-Agent": self._get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self._timeout_s, context=ctx) as resp:
            raw_bytes = resp.read()
            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)
            return raw_bytes.decode("utf-8", errors="ignore")

    def _consultar_claro_sincrono(self, query: str) -> list[OfertaLocal]:
        termino_encoded = quote_plus(query)
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        # 1. Consultar Tienda en Línea (Salesforce Commerce Cloud)
        for host in (CLARO_AKAMAI_ORIGIN_BASE_URL, CLARO_PUBLIC_BASE_URL):
            url_search = CLARO_TIENDA_SEARCH_TEMPLATE.format(
                base=host, query=termino_encoded
            )
            try:
                html = self._descargar_html_sincrono(url_search)
                extraidas = self.parsear_html_tienda_claro(
                    html, base_url=CLARO_PUBLIC_BASE_URL
                )
                for of in extraidas:
                    if of.url not in urls_vistas:
                        urls_vistas.add(of.url)
                        ofertas.append(of)
                if ofertas:
                    break
            except Exception:
                continue

        # 2. Si la búsqueda menciona una marca del catálogo prepago o "celular"/"telefono", complementar
        q_lower = query.lower()
        marca_detectada = None
        for marca in MARCAS_PREPAGO_CLARO:
            if marca in q_lower:
                marca_detectada = marca
                break
        if marca_detectada is None and any(
            k in q_lower for k in ("apple", "ios")
        ):
            marca_detectada = "iphone"

        if marca_detectada:
            url_prepago = CLARO_CATALOGO_PREPAGO_TEMPLATE.format(
                base=CLARO_AKAMAI_ORIGIN_BASE_URL, marca=marca_detectada
            )
            try:
                html_prep = self._descargar_html_sincrono(url_prepago)
                for of in self.parsear_html_tienda_claro(
                    html_prep, base_url=CLARO_PUBLIC_BASE_URL
                ):
                    if of.url not in urls_vistas:
                        urls_vistas.add(of.url)
                        ofertas.append(of)
            except Exception:
                pass

        return ofertas

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Tienda Claro Guatemala y retorna ofertas en Quetzales (GTQ)."""
        termino = query.strip()
        if not termino:
            return []

        logger.info("Tienda Claro GT: consultando '%s'...", termino)
        try:
            ofertas = await asyncio.to_thread(self._consultar_claro_sincrono, termino)
            if self._aplicar_filtro_ruido:
                ofertas = filtrar_ofertas_relevantes(ofertas, termino)
            logger.info(
                "Tienda Claro GT: %d ofertas extraídas correctamente.", len(ofertas)
            )
            return ofertas
        except Exception as error:
            logger.warning("Tienda Claro GT: fallo controlado en consulta: %s", error)
            return []
