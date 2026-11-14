"""
Scrapers de Tiendas Oficiales y Distribuidores Autorizados de Electrónica en Guatemala:
  1. Siman Guatemala (`https://gt.siman.com`) -> tienda: "Siman"
     Distribuidor oficial autorizado de Samsung, LG, Apple, Sony, Whirlpool, Mabe, HP y Lenovo.
  2. Elektra Guatemala (`https://www.elektra.com.gt`) -> tienda: "Elektra"
     Distribuidor oficial autorizado de Samsung, LG, Xiaomi, Motorola, TCL, Hisense e Italika.
  3. iShop Guatemala (`https://ishop.gt`) -> tienda: "iShop"
     Apple Premium Reseller oficial y distribuidor autorizado de electrónica en Guatemala.

Captura precios oficiales en Quetzales (GTQ) de smartphones, pantallas (Smart TVs OLED/QLED),
cómputo y línea blanca (refrigeradoras, lavadoras, microondas) aplicando el Filtro Anti-Ruido.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urljoin

from fake_useragent import UserAgent

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

DISTRIBUIDORES_VTEX_OFICIALES: dict[str, dict[str, str]] = {
    "siman": {
        "nombre": "Siman",
        "base_url": "https://gt.siman.com/",
        "api_template": (
            "https://gt.siman.com/api/catalog_system/pub/products/search/"
            "?ft={query}&_from=0&_to=14"
        ),
    },
    "elektra": {
        "nombre": "Elektra",
        "base_url": "https://www.elektra.com.gt/",
        "api_template": (
            "https://www.elektra.com.gt/api/catalog_system/pub/products/search/"
            "?ft={query}&_from=0&_to=14"
        ),
    },
}

ISHOP_GT_BASE_URL = "https://ishop.gt/"
ISHOP_SUGGEST_API_TEMPLATE = (
    "https://ishop.gt/search/suggest.json"
    "?q={query}&resources%5Btype%5D=product&resources%5Blimit%5D=10"
)

REQUEST_TIMEOUT_SECONDS = 14


class TiendasOficialesScraper(BaseScraper):
    """
    Scraper multicadena para distribuidores oficiales de electrónica y línea blanca
    en Guatemala (Siman GT, Elektra GT e iShop GT).
    """

    def __init__(
        self,
        incluir_siman: bool = True,
        incluir_elektra: bool = True,
        incluir_ishop: bool = True,
        timeout_s: int = REQUEST_TIMEOUT_SECONDS,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._incluir_siman = incluir_siman
        self._incluir_elektra = incluir_elektra
        self._incluir_ishop = incluir_ishop
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
    def _mapear_producto_vtex_oficial(
        cls,
        producto_vtex: dict[str, Any],
        nombre_tienda: str,
        base_url: str,
    ) -> OfertaLocal | None:
        """Convierte un producto VTEX de Siman GT o Elektra GT en OfertaLocal."""
        try:
            titulo = " ".join(str(producto_vtex.get("productName") or "").split())
            link_text = str(producto_vtex.get("linkText") or "").strip().strip("/")
            link_raw = str(producto_vtex.get("link") or "").strip()

            if link_text:
                url_absoluta = urljoin(base_url, f"{link_text}/p")
            elif link_raw:
                url_absoluta = urljoin(base_url, link_raw)
            else:
                return None

            if not titulo or not url_absoluta:
                return None

            items = producto_vtex.get("items") or []
            if not isinstance(items, list) or not items:
                return None

            primer_item = items[0] if isinstance(items[0], dict) else {}

            imagenes = primer_item.get("images") or []
            imagen_url = ""
            if isinstance(imagenes, list) and imagenes and isinstance(imagenes[0], dict):
                raw_img = str(imagenes[0].get("imageUrl") or "").strip()
                if raw_img:
                    imagen_url = raw_img.split("?")[0]

            sellers = primer_item.get("sellers") or []
            if not isinstance(sellers, list) or not sellers:
                return None

            oferta_comercial: dict[str, Any] = {}
            for seller in sellers:
                if isinstance(seller, dict):
                    cand = seller.get("commertialOffer") or {}
                    if isinstance(cand, dict) and (cand.get("Price") or 0) > 0:
                        oferta_comercial = cand
                        if seller.get("sellerDefault"):
                            break

            if not oferta_comercial:
                return None

            precio_raw = oferta_comercial.get("Price")
            stock = oferta_comercial.get("AvailableQuantity", 1)
            if precio_raw is None:
                return None

            precio_gtq = float(precio_raw)
            if precio_gtq <= 0 or (isinstance(stock, (int, float)) and stock <= 0):
                return None

            return OfertaLocal(
                tienda=nombre_tienda,
                titulo=titulo,
                precio_gtq=round(precio_gtq, 2),
                url=url_absoluta,
                imagen_url=imagen_url,
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning(
                "%s: fallo mapeando producto oficial VTEX: %s", nombre_tienda, error
            )
            return None

    @classmethod
    def parsear_respuesta_vtex(
        cls,
        raw_json: str | list[dict[str, Any]],
        nombre_tienda: str = "Siman",
        base_url: str = "https://gt.siman.com/",
    ) -> list[OfertaLocal]:
        """Parsea la lista de productos JSON VTEX de Siman o Elektra."""
        if isinstance(raw_json, str):
            if not raw_json.strip():
                return []
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                return []
        else:
            data = raw_json

        if not isinstance(data, list):
            return []

        ofertas: list[OfertaLocal] = []
        for item in data:
            if isinstance(item, dict):
                oferta = cls._mapear_producto_vtex_oficial(
                    item, nombre_tienda=nombre_tienda, base_url=base_url
                )
                if oferta is not None:
                    ofertas.append(oferta)
        return ofertas

    @classmethod
    def parsear_respuesta_shopify_ishop(
        cls,
        raw_json: str | dict[str, Any],
        nombre_tienda: str = "iShop",
        base_url: str = ISHOP_GT_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON de Shopify Predictive Search (`resources.results.products`)
        de iShop Guatemala en entidades `OfertaLocal`.
        """
        if isinstance(raw_json, str):
            if not raw_json.strip():
                return []
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                return []
        else:
            data = raw_json

        if not isinstance(data, dict):
            return []

        productos = (
            ((data.get("resources") or {}).get("results") or {}).get("products") or []
        )
        if not isinstance(productos, list):
            return []

        ofertas: list[OfertaLocal] = []
        for prod in productos:
            if not isinstance(prod, dict):
                continue
            try:
                if prod.get("available") is False:
                    continue

                titulo = " ".join(str(prod.get("title") or "").split())
                url_raw = str(prod.get("url") or "").strip().split("?")[0]
                precio_raw = prod.get("price")
                if not titulo or not url_raw or precio_raw is None:
                    continue

                precio_gtq = float(str(precio_raw).replace(",", ""))
                if precio_gtq <= 0:
                    continue

                imagen_raw = str(prod.get("image") or "").strip()
                imagen_url = urljoin(base_url, imagen_raw.split("?")[0]) if imagen_raw else ""

                ofertas.append(
                    OfertaLocal(
                        tienda=nombre_tienda,
                        titulo=titulo,
                        precio_gtq=round(precio_gtq, 2),
                        url=urljoin(base_url, url_raw),
                        imagen_url=imagen_url,
                    )
                )
            except (ValueError, TypeError, AttributeError):
                continue

        return ofertas

    def _consultar_json_sincrono(self, url: str) -> str:
        for _ in range(2):
            headers = {
                "User-Agent": self._get_random_user_agent(),
                "Accept": "application/json",
                "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
            }
            req = urllib.request.Request(url, headers=headers, method="GET")
            ctx = ssl.create_default_context()
            try:
                with urllib.request.urlopen(
                    req, timeout=self._timeout_s, context=ctx
                ) as resp:
                    raw_bytes = resp.read()
            except urllib.error.URLError:
                ctx_permisivo = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    req, timeout=self._timeout_s, context=ctx_permisivo
                ) as resp:
                    raw_bytes = resp.read()

            if raw_bytes[:2] == b"\x1f\x8b":
                raw_bytes = gzip.decompress(raw_bytes)

            texto = raw_bytes.decode("utf-8", errors="ignore").strip()
            if texto:
                return texto
        return ""

    async def _buscar_en_vtex_oficial(
        self, clave: str, termino: str
    ) -> list[OfertaLocal]:
        cfg = DISTRIBUIDORES_VTEX_OFICIALES[clave]
        nombre = cfg["nombre"]
        base_url = cfg["base_url"]
        url_api = cfg["api_template"].format(query=quote(termino))

        logger.info("%s (Distribuidor Oficial): consultando '%s'...", nombre, url_api)
        try:
            raw_json = await asyncio.to_thread(self._consultar_json_sincrono, url_api)
        except Exception as error:
            logger.error("%s: error consultando API VTEX: %s", nombre, error)
            return []

        ofertas = self.parsear_respuesta_vtex(
            raw_json, nombre_tienda=nombre, base_url=base_url
        )
        if self._aplicar_filtro_ruido:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)
        logger.info("%s: %d ofertas oficiales extraídas.", nombre, len(ofertas))
        return ofertas

    async def _buscar_en_ishop(self, termino: str) -> list[OfertaLocal]:
        url_api = ISHOP_SUGGEST_API_TEMPLATE.format(query=quote(termino))
        logger.info("iShop GT (Apple Oficial): consultando '%s'...", url_api)
        try:
            raw_json = await asyncio.to_thread(self._consultar_json_sincrono, url_api)
        except Exception as error:
            logger.error("iShop GT: error consultando API Shopify: %s", error)
            return []

        ofertas = self.parsear_respuesta_shopify_ishop(raw_json)
        if self._aplicar_filtro_ruido:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)
        logger.info("iShop GT: %d ofertas oficiales extraídas.", len(ofertas))
        return ofertas

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """
        Consulta concurrentemente Siman GT, Elektra GT e iShop GT para extraer
        precios oficiales de Samsung, LG, Apple, pantallas, smartphones y línea blanca.
        """
        termino = query.strip()
        if not termino:
            return []

        tareas = []
        if self._incluir_siman:
            tareas.append(self._buscar_en_vtex_oficial("siman", termino))
        if self._incluir_elektra:
            tareas.append(self._buscar_en_vtex_oficial("elektra", termino))
        if self._incluir_ishop:
            tareas.append(self._buscar_en_ishop(termino))

        if not tareas:
            return []

        resultados = await asyncio.gather(*tareas)
        unificadas: list[OfertaLocal] = []
        for lista in resultados:
            unificadas.extend(lista)
        return unificadas
