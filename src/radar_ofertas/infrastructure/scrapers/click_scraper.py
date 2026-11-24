"""
Scraper Real para Click Guatemala (click.gt — Shopify Store de Laptops, Periféricos Gamer y Tecnología).

Implementación v5.5 (Tolerancia Cero a Datos Sintéticos):
  - Sin listas estáticas (`CATALOGO_VERIFICADO_CLICK_GT` eliminado por completo).
  - Consulta en tiempo real la API JSON de Shopify `https://click.gt/search/suggest.json?q=<termino>&resources[type]=product`
    y el HTML de `https://click.gt`.
  - Extrae únicamente la URL directa real del producto (`https://click.gt/products/<handle>`),
    la imagen real del CDN de Shopify (`https://cdn.shopify.com/...`) y el precio real en GTQ.
  - Si la tienda no responde o no tiene el producto, devuelve `[]`.
"""
from __future__ import annotations

import asyncio
import json
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


class ClickScraper(BaseScraper):
    """
    Scraper asíncrono 100% real para Click Guatemala (`https://click.gt`).
    Sin catálogos estáticos: devuelve únicamente productos reales con URL directa `/products/<handle>`.
    """

    BASE_URL = "https://click.gt"
    NOMBRE_TIENDA = "Click Guatemala"

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
        self, payload: dict[str, Any] | list[dict[str, Any]]
    ) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON real de Shopify (`resources.results.products`) o lista de productos
        de Click Guatemala en entidades `OfertaLocal` con URL directa verificada.
        """
        items: list[Any] = []
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            shopify_prods = (
                (payload.get("resources") or {}).get("results") or {}
            ).get("products")
            if isinstance(shopify_prods, list):
                items = shopify_prods
            else:
                items = payload.get("items", payload.get("products", []))

        if not isinstance(items, list):
            return []

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("title") or item.get("name") or "").strip()
            precio_raw = item.get("price") or item.get("final_price")
            url_raw = str(item.get("url") or item.get("permalink") or "").strip()
            if not url_raw and item.get("handle"):
                url_raw = f"/products/{item['handle']}"
            url_sin_tracking = url_raw.split("?")[0].strip()

            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None or not url_sin_tracking:
                continue

            url_directa = resolver_url_saliente_segura(
                url_sin_tracking
                if url_sin_tracking.startswith("http")
                else f"{self.BASE_URL}/{url_sin_tracking.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_directa) or url_directa in urls_vistas:
                continue

            img_raw = item.get("image")
            if not img_raw and isinstance(item.get("featured_image"), dict):
                img_raw = item["featured_image"].get("url")
            imagen_url = resolver_url_saliente_segura(str(img_raw or "").strip())

            urls_vistas.add(url_directa)
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_directa,
                    imagen_url=imagen_url if imagen_url.startswith("https://") else None,
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

        for card in soup.select(".product, .product-item, .product-card, li.product, .grid__item"):
            enlace = card.select_one("a[href*='/products/'], a.woocommerce-LoopProduct-link, .product-title a, h2 a, h3 a")
            nodo_precio = card.select_one(".price-item--sale, .price-item--regular, .price ins .amount, .price .amount, .price, .product-price")
            if not enlace or not nodo_precio:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip().split("?")[0]
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

    def _consultar_shopify_json_sync(self, termino: str) -> list[OfertaLocal]:
        q_enc = urllib.parse.quote(termino.strip())
        url = f"{self.BASE_URL}/search/suggest.json?q={q_enc}&resources[type]=product&resources[limit]=15"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
            },
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return self.parsear_respuesta_catalogo(payload)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado or self.simular:
            return []

        try:
            ofertas_web = await asyncio.to_thread(self._consultar_shopify_json_sync, termino)
        except Exception as exc:
            logger.debug("Click GT sin respuesta (%s) para '%s'.", exc.__class__.__name__, termino)
            return []

        relevantes = [
            o
            for o in ofertas_web
            if es_url_producto_directa_valida(o.url)
            and es_oferta_relevante(o.titulo, termino)
        ]
        logger.info("Click Guatemala ('%s'): %d ofertas reales extraídas.", termino, len(relevantes))
        return relevantes
