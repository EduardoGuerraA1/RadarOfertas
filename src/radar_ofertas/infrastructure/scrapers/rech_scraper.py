"""
Scraper Real para Rech Guatemala (rech.com.gt — Especialista en Hardware, Componentes, PC Gaming y Periféricos).

Implementación v5.5 (Tolerancia Cero a Datos Sintéticos):
  - Sin listas estáticas (`CATALOGO_VERIFICADO_RECH_GT` eliminado por completo).
  - Consulta en tiempo real el buscador real `https://rech.com.gt/search?key=<termino>`.
  - Extrae únicamente fichas reales con enlace directo `https://rech.com.gt/detalle_producto.php?id=<id>`,
    su imagen real (`https://intech.com.gt/sU/files/articulos_thumbs_300/...`) y su precio real en GTQ.
  - Si la tienda no responde o no tiene el producto, devuelve `[]`.
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


class RechScraper(BaseScraper):
    """
    Scraper asíncrono 100% real para Rech Guatemala (`https://rech.com.gt`).
    Sin catálogos estáticos: devuelve únicamente productos reales con URL directa `detalle_producto.php?id=...`.
    """

    BASE_URL = "https://rech.com.gt"
    NOMBRE_TIENDA = "Rech"

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
        # Cuando una tarjeta tiene precio tachado y precio de oferta (ej. "Q 418 Q 369.00"),
        # tomamos el último precio válido en Quetzales (el precio de venta vigente).
        matches = re.findall(r"Q\.?\s*([\d,]+(?:\.\d{1,2})?)", texto, flags=re.IGNORECASE)
        candidato = matches[-1] if matches else re.sub(r"[^\d.,]", "", texto)
        if not candidato:
            return None
        candidato = candidato.replace(",", "")
        try:
            dec = Decimal(candidato).quantize(Decimal("0.01"))
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    def parsear_respuesta_woocommerce(
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
            url_raw = str(item.get("permalink") or item.get("url") or "").strip()
            prices_obj = item.get("prices") if isinstance(item.get("prices"), dict) else {}
            precio_raw = (
                prices_obj.get("price")
                or item.get("price")
                or item.get("regular_price")
            )
            if prices_obj.get("currency_minor_unit") == 2 and str(precio_raw or "").isdigit():
                precio = (Decimal(str(precio_raw)) / Decimal("100")).quantize(Decimal("0.01"))
            else:
                precio = self._limpiar_precio(precio_raw)

            if not titulo or not url_raw or precio is None:
                continue

            url_directa = resolver_url_saliente_segura(
                url_raw if url_raw.startswith("http") else f"{self.BASE_URL}/{url_raw.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_directa):
                continue

            imagenes = item.get("images") if isinstance(item.get("images"), list) else []
            imagen_url = ""
            if imagenes and isinstance(imagenes[0], dict):
                imagen_url = resolver_url_saliente_segura(str(imagenes[0].get("src") or "").strip())
            elif item.get("image"):
                imagen_url = resolver_url_saliente_segura(str(item.get("image")).strip())

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
        """
        Extrae productos reales del DOM de `rech.com.gt/search?key=...` (`a[href*="detalle_producto"]`)
        y tarjetas HTML estándar.
        """
        if not html or not html.strip():
            return []
        soup = BeautifulSoup(html, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        # 1. Estructura nativa de Rech GT: enlaces a detalle_producto.php?id=<id>
        for enlace in soup.select('a[href*="detalle_producto"]'):
            titulo = enlace.get_text(" ", strip=True)
            if not titulo or titulo.lower() in {"detalles", "ver", "agregar al carrito"} or len(titulo) < 5:
                continue
            href = str(enlace.get("href") or "").strip()
            if not href:
                continue
            url_abs = resolver_url_saliente_segura(
                href if href.startswith("http") else f"{self.BASE_URL}/{href.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_abs) or url_abs in urls_vistas:
                continue

            # Buscar contenedor padre de la tarjeta para extraer precio e imagen real
            contenedor = enlace.find_parent(["div", "li", "article"])
            if contenedor and contenedor.find_parent(["div", "li", "article"]):
                padre_superior = contenedor.find_parent(["div", "li", "article"])
                if padre_superior and "Q" in padre_superior.get_text():
                    contenedor = padre_superior

            texto_card = contenedor.get_text(" ", strip=True) if contenedor else ""
            precio = self._limpiar_precio(texto_card)
            if precio is None:
                continue

            img_el = contenedor.select_one("img") if contenedor else None
            img_url = (
                resolver_url_saliente_segura(
                    str(img_el.get("data-src") or img_el.get("src") or "").strip()
                )
                if img_el
                else ""
            )

            urls_vistas.add(url_abs)
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_abs,
                    imagen_url=img_url if img_url.startswith("https://") else None,
                    tienda=self.NOMBRE_TIENDA,
                )
            )

        # 2. Soporte para tarjetas de producto genéricas si no hubo nodos detalle_producto
        if not ofertas:
            for card in soup.select("li.product, .product-item, .product-card, .product-small"):
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
        url = f"{self.BASE_URL}/search?key={q_enc}"
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
            logger.debug("Rech GT sin respuesta (%s) para '%s'.", exc.__class__.__name__, termino)
            return []

        relevantes = [
            o
            for o in ofertas_web
            if es_url_producto_directa_valida(o.url)
            and es_oferta_relevante(o.titulo, termino)
        ]
        logger.info("Rech ('%s'): %d ofertas reales extraídas.", termino, len(relevantes))
        return relevantes
