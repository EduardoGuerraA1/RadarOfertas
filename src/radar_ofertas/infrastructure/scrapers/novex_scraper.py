"""
Scraper de Infraestructura para Novex Guatemala (novex.com.gt).
Ferretería, herramientas eléctricas/manuales, construcción, hogar y suministros industriales.
Implementa cabeceras HTTP limpias para sortear WAF, parser HTML de tarjetas de catálogo
de Novex (`/search?term=...` y `/catalogo/...`) y respaldo de catálogo verificado de
Novex Guatemala cuando Cloudflare bloquea rangos de IP de datacenter (Render/Cloud).
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


class NovexScraper(BaseScraper):
    """
    Scraper asíncrono para Novex Guatemala (`https://www.novex.com.gt`).
    Implementa cabeceras limpias de navegador real y extracción de JSON-LD / tarjetas HTML
    sin catálogos estáticos inventados (v5.5).
    """

    BASE_URL = "https://www.novex.com.gt"
    NOMBRE_TIENDA = "Novex"

    def __init__(self, timeout_s: int = 10) -> None:
        self.timeout_s = timeout_s

    @staticmethod
    def _limpiar_precio(valor: Any) -> Decimal | None:
        if valor is None:
            return None
        texto = str(valor).strip()
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
            dec = Decimal(limpio).quantize(Decimal("0.01"))
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    def _absolutizar_url(self, href: str) -> str:
        limpio = (href or "").strip()
        if not limpio:
            return ""
        if limpio.startswith("//"):
            return f"https:{limpio}"
        if limpio.startswith("http://") or limpio.startswith("https://"):
            return limpio
        return urllib.parse.urljoin(self.BASE_URL, limpio)

    def parsear_html(self, html_content: str) -> list[OfertaLocal]:
        """
        Extrae productos desde el HTML de Novex Guatemala (bloques JSON-LD y tarjetas `.item-product` / `.product-card`).
        """
        if not html_content or not html_content.strip():
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        # 1. Intentar bloques JSON-LD si están presentes
        for script in soup.select('script[type="application/ld+json"]'):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            bloques = data if isinstance(data, list) else [data]
            for bloque in bloques:
                if not isinstance(bloque, dict):
                    continue
                if bloque.get("@type") == "Product":
                    nombre = str(bloque.get("name") or "").strip()
                    offers = bloque.get("offers") or {}
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    precio = self._limpiar_precio(
                        offers.get("price") if isinstance(offers, dict) else None
                    )
                    url = self._absolutizar_url(
                        str(
                            (offers.get("url") if isinstance(offers, dict) else None)
                            or bloque.get("url")
                            or ""
                        )
                    )
                    img = bloque.get("image")
                    if isinstance(img, list) and img:
                        img = img[0]
                    imagen_url = self._absolutizar_url(str(img or "")) if img else ""
                    if (
                        nombre
                        and precio
                        and es_url_producto_directa_valida(url)
                        and url not in urls_vistas
                    ):
                        urls_vistas.add(url)
                        ofertas.append(
                            OfertaLocal(
                                titulo=nombre,
                                precio_gtq=precio,
                                url=url,
                                imagen_url=imagen_url,
                                tienda=self.NOMBRE_TIENDA,
                            )
                        )

        # 2. Tarjetas HTML de catálogo Novex (.product-item, .item-box, .card-product)
        selectores_tarjeta = (
            "div.product-item, div.item-product, div.card-product, "
            "div.item, article.product"
        )
        for card in soup.select(selectores_tarjeta):
            enlace = card.select_one('a[href*="/catalogo/"], a.product-title, a.title, h3 a, h2 a')
            if not enlace:
                continue
            titulo = enlace.get_text(" ", strip=True) or str(enlace.get("title") or "").strip()
            href = str(enlace.get("href") or "").strip()
            if not titulo or not href:
                continue

            nodo_precio = card.select_one(
                "span.price, div.price, span.precio, div.precio-actual, .product-price"
            )
            if not nodo_precio:
                continue
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
            if precio is None:
                continue

            url = self._absolutizar_url(href)
            if not es_url_producto_directa_valida(url) or url in urls_vistas:
                continue
            urls_vistas.add(url)

            img_tag = card.select_one("img")
            imagen_url = ""
            if img_tag:
                src = str(img_tag.get("src") or img_tag.get("data-src") or "").strip()
                if src:
                    imagen_url = self._absolutizar_url(src)

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
        query_encoded = urllib.parse.quote_plus(termino)
        url = f"{self.BASE_URL}/search?term={query_encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-GT,es;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        return self.parsear_html(html)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino:
            return []

        try:
            ofertas_web = await asyncio.to_thread(self._consultar_web_sync, termino)
        except Exception as error:
            logger.debug(
                "Novex GT WAF/red (%s); retornando [].",
                error.__class__.__name__,
            )
            return []

        ofertas_filtradas = filtrar_ofertas_relevantes(ofertas_web, termino)
        logger.info(
            "Novex GT ('%s'): %d ofertas reales obtenidas.", termino, len(ofertas_filtradas)
        )
        return ofertas_filtradas
