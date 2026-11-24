"""
Scraper de Infraestructura para Almacenes Tropigas Guatemala (almacenestropigas.com/guatemala).
Extrae línea blanca (refrigeradoras Mabe/LG/Samsung, estufas de gas de 20\" y 30\", lavadoras),
pantallas Smart TV y smartphones en Quetzales (GTQ).
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
from radar_ofertas.domain.services.filtro_relevancia import (
    es_url_producto_directa_valida,
    filtrar_ofertas_relevantes,
)

logger = logging.getLogger(__name__)


class TropigasScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Almacenes Tropigas Guatemala (`https://www.almacenestropigas.com/guatemala`).
    Consulta en vivo la API VTEX oficial de Almacenes Tropigas GT y HTML sin inventar catálogos estáticos (v5.5).
    """

    BASE_URL = "https://www.almacenestropigas.com/guatemala"
    NOMBRE_TIENDA = "Tropigas"

    def __init__(
        self, timeout_s: int = 10, habilitado: bool = True, simular: bool = False
    ) -> None:
        self.timeout_s = timeout_s
        self.habilitado = habilitado
        self.simular = simular

    @staticmethod
    def _limpiar_precio(valor: Any) -> Decimal | None:
        if valor is None:
            return None
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

    def parsear_respuesta_unicomer(self, payload: dict[str, Any] | list[Any]) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON (API VTEX o Unicomer) de Almacenes Tropigas GT en entidades `OfertaLocal`.
        """
        if isinstance(payload, dict):
            items = payload.get("items", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            # Formato VTEX catalog_system/pub/products/search
            if "productName" in item and isinstance(item.get("items"), list):
                titulo = str(item.get("productName") or "").strip()
                link = str(item.get("link") or "").strip()
                skus = item.get("items") or []
                if not titulo or not link or not skus:
                    continue
                sku0 = skus[0] if isinstance(skus[0], dict) else {}
                imagenes = sku0.get("images") or []
                imagen_url = ""
                if isinstance(imagenes, list) and imagenes and isinstance(imagenes[0], dict):
                    imagen_url = str(imagenes[0].get("imageUrl") or "").strip()
                sellers = sku0.get("sellers") or []
                precio_raw = None
                if isinstance(sellers, list) and sellers and isinstance(sellers[0], dict):
                    comm = sellers[0].get("commertialOffer") or {}
                    if isinstance(comm, dict):
                        precio_raw = comm.get("Price")
                precio = self._limpiar_precio(precio_raw)
                if precio is None or not es_url_producto_directa_valida(link) or link in urls_vistas:
                    continue
                urls_vistas.add(link)
                ofertas.append(
                    OfertaLocal(
                        titulo=titulo,
                        precio_gtq=precio,
                        url=link,
                        imagen_url=imagen_url,
                        tienda=self.NOMBRE_TIENDA,
                    )
                )
                continue

            # Formato diccionario genérico Unicomer
            titulo = str(item.get("name") or "").strip()
            precio_raw = item.get("price") or item.get("final_price")
            url = str(item.get("url") or "").strip()
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None or not url:
                continue
            url_abs = (
                url
                if url.startswith("http")
                else f"{self.BASE_URL}/{url.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_abs) or url_abs in urls_vistas:
                continue
            urls_vistas.add(url_abs)
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_abs,
                    imagen_url=str(item.get("image") or ""),
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def parsear_html(self, html_content: str) -> list[OfertaLocal]:
        if not html_content or not html_content.strip():
            return []
        soup = BeautifulSoup(html_content, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in soup.select("li.product-item, div.product-item-info"):
            enlace = item.select_one("a.product-item-link, a[href]")
            if not enlace:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            nodo_precio = item.select_one("[data-price-amount], span.price")
            if not titulo or not href or not nodo_precio:
                continue
            precio = self._limpiar_precio(
                nodo_precio.get("data-price-amount")
                or nodo_precio.get_text(" ", strip=True)
            )
            if precio is None:
                continue
            url = (
                href
                if href.startswith("http")
                else urllib.parse.urljoin(self.BASE_URL + "/", href.lstrip("/"))
            )
            if not es_url_producto_directa_valida(url) or url in urls_vistas:
                continue
            urls_vistas.add(url)
            img = item.select_one("img")
            imagen_url = (
                str(img.get("src") or img.get("data-src") or "").strip()
                if img
                else ""
            )
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

    def _consultar_web_sync(self, termino: str) -> list[OfertaLocal]:
        url = (
            f"{self.BASE_URL}/api/catalog_system/pub/products/search/"
            f"?ft={urllib.parse.quote(termino)}&_from=0&_to=11"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        return self.parsear_respuesta_unicomer(payload)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado or self.simular:
            return []

        try:
            ofertas_web = await asyncio.to_thread(self._consultar_web_sync, termino)
        except Exception as exc:
            logger.debug(
                "Tropigas GT web error (%s) para '%s'.",
                exc.__class__.__name__,
                termino,
            )
            return []

        ofertas_filtradas = filtrar_ofertas_relevantes(ofertas_web, termino)
        logger.info("Tropigas GT ('%s'): %d ofertas reales extraídas.", termino, len(ofertas_filtradas))
        return ofertas_filtradas
