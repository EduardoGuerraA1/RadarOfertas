"""
Scraper Real para Tera Guatemala (tera.com.gt — Hardware, Componentes y Periféricos).

Implementación v5.5 (Tolerancia Cero a Datos Sintéticos):
  - Sin listas estáticas (`CATALOGO_VERIFICADO_TERA_GT` eliminado por completo).
  - Extrae exclusivamente productos reales con URL directa verificada, imagen real y precio real.
  - Si la tienda no responde o no tiene el producto en su catálogo en línea, devuelve `[]`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import ssl
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_oferta_relevante,
    es_url_producto_directa_valida,
    resolver_url_saliente_segura,
)

logger = logging.getLogger(__name__)


class TeraScraper(BaseScraper):
    """
    Scraper asíncrono 100% real para Tera Guatemala (`https://www.tera.com.gt`).
    Sin catálogos estáticos: si la tienda no responde o no tiene coincidencias reales, devuelve `[]`.
    """

    BASE_URL = "https://www.tera.com.gt"
    NOMBRE_TIENDA = "Tera"

    def __init__(
        self, timeout_s: int = 8, habilitado: bool = True, simular: bool = False
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

    def parsear_respuesta_catalogo(
        self, payload: list[dict[str, Any]] | dict[str, Any]
    ) -> list[OfertaLocal]:
        items = payload if isinstance(payload, list) else payload.get("products", payload.get("items", []))
        if not isinstance(items, list):
            return []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("title") or "").strip()
            precio_raw = item.get("price") or item.get("final_price")
            url_raw = str(item.get("permalink") or item.get("url") or "").strip()
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None or not url_raw:
                continue
            url_directa = resolver_url_saliente_segura(
                url_raw if url_raw.startswith("http") else f"{self.BASE_URL}/{url_raw.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_directa):
                continue
            img_raw = resolver_url_saliente_segura(str(item.get("image") or "").strip())
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_directa,
                    imagen_url=img_raw if img_raw.startswith("https://") else None,
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def parsear_html(self, html: str) -> list[OfertaLocal]:
        if not html or not html.strip():
            return []
        soup = BeautifulSoup(html, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for card in soup.select("li.product, .product-item, .product-card, .product"):
            enlace = card.select_one("a.woocommerce-LoopProduct-link, .product-title a, h2 a, h3 a")
            nodo_precio = card.select_one(".price ins .amount, .price .amount, .price, .product-price")
            if not enlace or not nodo_precio:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
            if not titulo or not href or precio is None:
                continue
            url_abs = resolver_url_saliente_segura(
                href if href.startswith("http") else f"{self.BASE_URL}/{href.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_abs) or url_abs in urls_vistas:
                continue
            urls_vistas.add(url_abs)

            img_el = card.select_one("img")
            img_url = (
                resolver_url_saliente_segura(
                    str(img_el.get("data-src") or img_el.get("src") or "").strip()
                )
                if img_el
                else ""
            )

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_abs,
                    imagen_url=img_url if img_url.startswith("https://") else None,
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def _consultar_web_sync(self, termino: str) -> list[OfertaLocal]:
        q_enc = urllib.parse.quote_plus(termino.strip())
        url = f"{self.BASE_URL}/?s={q_enc}&post_type=product"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
            },
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        return self.parsear_html(html)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado or self.simular:
            return []

        try:
            ofertas_web = await asyncio.to_thread(self._consultar_web_sync, termino)
        except Exception as exc:
            logger.debug("Tera GT sin respuesta (%s) para '%s'.", exc.__class__.__name__, termino)
            return []

        relevantes = [
            o
            for o in ofertas_web
            if es_url_producto_directa_valida(o.url)
            and es_oferta_relevante(o.titulo, termino)
        ]
        logger.info("Tera ('%s'): %d ofertas reales extraídas.", termino, len(relevantes))
        return relevantes
