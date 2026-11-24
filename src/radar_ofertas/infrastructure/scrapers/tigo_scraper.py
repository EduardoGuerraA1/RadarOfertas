"""
Scraper de Infraestructura para Tienda Tigo Guatemala (tienda.tigo.com.gt).
Extrae smartphones en planes prepago, postpago y equipos liberados en Quetzales (GTQ),
completando el duopolio de telefonía móvil junto a Tienda Claro GT.
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


class TigoScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Tienda en Línea Tigo Guatemala (`https://tienda.tigo.com.gt`).
    Tolerancia cero a datos sintéticos (v5.5): solo devuelve productos extraídos en vivo.
    """

    BASE_URL = "https://tienda.tigo.com.gt"
    NOMBRE_TIENDA = "Tienda Tigo"

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

    def parsear_respuesta_catalogo(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Transforma nodos de producto del catálogo de Tienda Tigo GT en entidades `OfertaLocal`.
        """
        items = payload.get("items", []) if isinstance(payload, dict) else []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("titulo") or "").strip()
            precio_raw = item.get("price") or item.get("precio_gtq")
            url = str(item.get("url") or "").strip()
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None or not url:
                continue
            url_abs = (
                url
                if url.startswith("http")
                else f"{self.BASE_URL}/{url.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_abs):
                continue
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_abs,
                    imagen_url=str(item.get("image") or item.get("imagen_url") or ""),
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

        for card in soup.select(
            "li.product-item, div.product-item-info, article.product-card"
        ):
            enlace = card.select_one("a.product-item-link, a[href]")
            if not enlace:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            nodo_precio = card.select_one(
                "[data-price-amount], span.price, div.price-box"
            )
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
                else urllib.parse.urljoin(self.BASE_URL, href)
            )
            if not es_url_producto_directa_valida(url) or url in urls_vistas:
                continue
            urls_vistas.add(url)
            img = card.select_one("img")
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
        url = f"{self.BASE_URL}/catalogsearch/result/?q={urllib.parse.quote_plus(termino)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        return self.parsear_html(html)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado or self.simular:
            return []

        try:
            ofertas_web = await asyncio.to_thread(self._consultar_web_sync, termino)
        except Exception as exc:
            logger.debug("Tienda Tigo GT web error (%s) para '%s'.", exc.__class__.__name__, termino)
            return []

        ofertas_filtradas = filtrar_ofertas_relevantes(ofertas_web, termino)
        logger.info("Tienda Tigo GT ('%s'): %d ofertas reales extraídas.", termino, len(ofertas_filtradas))
        return ofertas_filtradas
