"""
Scraper de Infraestructura para iStore / iShop Guatemala (ishop.gt / istore.gt).
Especializado en dispositivos oficiales de Apple en Guatemala: iPhone, MacBook Air/Pro,
iPad, Apple Watch, AirPods, iMac y Mac mini.
Consume el endpoint JSON nativo de búsqueda predictiva de Shopify (`/search/suggest.json`)
y el catálogo verificado de precios oficiales Apple GT como respaldo ante rate-limiting.
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

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_url_producto_directa_valida,
    filtrar_ofertas_relevantes,
)

logger = logging.getLogger(__name__)


class IStoreScraper(BaseScraper):
    """
    Scraper asíncrono para iStore Guatemala (ishop.gt).
    Extrae dispositivos oficiales Apple y accesorios originales en Quetzales (GTQ)
    consultando el endpoint en vivo `/search/suggest.json` de Shopify sin listas estáticas (v5.5).
    """

    BASE_URL = "https://ishop.gt"
    NOMBRE_TIENDA = "iStore"

    def __init__(self, timeout_s: int = 12) -> None:
        self.timeout_s = timeout_s

    @staticmethod
    def _limpiar_precio(valor: Any) -> Decimal | None:
        if valor is None:
            return None
        texto = str(valor).strip()
        if not texto:
            return None
        limpio = re.sub(r"[^\d.,]", "", texto)
        if not limpio:
            return None
        if "," in limpio and "." in limpio:
            if limpio.rfind(",") > limpio.rfind("."):
                limpio = limpio.replace(".", "").replace(",", ".")
            else:
                limpio = limpio.replace(",", "")
        elif "," in limpio:
            partes = limpio.split(",")
            if len(partes[-1]) == 2:
                limpio = "".join(partes[:-1]) + "." + partes[-1]
            else:
                limpio = "".join(partes)
        try:
            dec = Decimal(limpio)
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    def _absolutizar_url(self, url_relativa_o_abs: str) -> str:
        url = (url_relativa_o_abs or "").strip()
        if not url:
            return ""
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http://") or url.startswith("https://"):
            return url
        url_limpia = url.split("?")[0]
        return urllib.parse.urljoin(self.BASE_URL, url_limpia)

    def parsear_respuesta_shopify(self, data: dict[str, Any]) -> list[OfertaLocal]:
        """
        Convierte el JSON de `/search/suggest.json` de iShop/iStore GT en entidades `OfertaLocal`.
        """
        productos = (
            data.get("resources", {}).get("results", {}).get("products", [])
            if isinstance(data, dict)
            else []
        )
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for prod in productos:
            if not isinstance(prod, dict):
                continue
            titulo = str(prod.get("title") or "").strip()
            precio_raw = prod.get("price") or prod.get("price_min")
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None:
                continue

            url = self._absolutizar_url(str(prod.get("url") or ""))
            if not es_url_producto_directa_valida(url) or url in urls_vistas:
                continue
            urls_vistas.add(url)

            imagen = str(prod.get("image") or prod.get("featured_image", {}).get("url") or "").strip()
            imagen_abs = self._absolutizar_url(imagen) if imagen else ""

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url,
                    imagen_url=imagen_abs,
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def _consultar_api_sync(self, termino: str) -> list[OfertaLocal]:
        params = urllib.parse.urlencode(
            {
                "q": termino,
                "resources[type]": "product",
                "resources[limit]": "12",
            }
        )
        url = f"{self.BASE_URL}/search/suggest.json?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return self.parsear_respuesta_shopify(payload)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino:
            return []

        try:
            ofertas_api = await asyncio.to_thread(self._consultar_api_sync, termino)
        except Exception as error:
            logger.debug("iStore GT API no disponible (%s).", error)
            return []

        ofertas_filtradas = filtrar_ofertas_relevantes(ofertas_api, termino)
        logger.info("iStore GT ('%s'): %d ofertas reales extraídas.", termino, len(ofertas_filtradas))
        return ofertas_filtradas
