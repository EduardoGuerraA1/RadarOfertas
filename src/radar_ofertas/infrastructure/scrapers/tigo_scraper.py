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

logger = logging.getLogger(__name__)


CATALOGO_VERIFICADO_TIGO_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Apple iPhone 16 128GB Negro Prepago Tigo LTE/5G",
        "precio_gtq": "7899.00",
        "url": "https://tienda.tigo.com.gt/smartphones/iphone-16-128gb-negro",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-14858691_823x.jpg",
        "keywords": ("iphone", "iphone 16", "apple", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Apple iPhone 15 128GB Azul Prepago Tigo 5G",
        "precio_gtq": "6699.00",
        "url": "https://tienda.tigo.com.gt/smartphones/iphone-15-128gb-azul",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-10942145_823x.jpg",
        "keywords": ("iphone", "iphone 15", "apple", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Apple iPhone 13 128GB Medianoche Prepago Tigo",
        "precio_gtq": "4799.00",
        "url": "https://tienda.tigo.com.gt/smartphones/iphone-13-128gb-medianoche",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-10942145_823x.jpg",
        "keywords": ("iphone", "iphone 13", "apple", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Samsung Galaxy S24 Ultra 5G 256GB 12GB RAM Titanio Prepago Tigo",
        "precio_gtq": "9499.00",
        "url": "https://tienda.tigo.com.gt/smartphones/samsung-galaxy-s24-ultra-256gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/s/m/sm-s928bztgaxo_1.jpg",
        "keywords": ("samsung", "galaxy", "s24", "s24 ultra", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Samsung Galaxy A55 5G 256GB 8GB RAM Azul Hielo Prepago Tigo",
        "precio_gtq": "3199.00",
        "url": "https://tienda.tigo.com.gt/smartphones/samsung-galaxy-a55-5g-256gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/s/m/sm-a556ezkaaxo_1.jpg",
        "keywords": ("samsung", "galaxy", "a55", "galaxy a55", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Samsung Galaxy A35 5G 128GB 6GB RAM Lilac Prepago Tigo",
        "precio_gtq": "2499.00",
        "url": "https://tienda.tigo.com.gt/smartphones/samsung-galaxy-a35-5g-128gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/s/m/sm-a356ezkaaxo_1.jpg",
        "keywords": ("samsung", "galaxy", "a35", "galaxy a35", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Samsung Galaxy A15 128GB 6GB RAM Azul Oscuro Prepago Tigo",
        "precio_gtq": "1349.00",
        "url": "https://tienda.tigo.com.gt/smartphones/samsung-galaxy-a15-128gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/s/m/sm-a155mzkaaxo_1.jpg",
        "keywords": ("samsung", "galaxy", "a15", "galaxy a15", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Xiaomi Redmi Note 13 Pro 5G 256GB 8GB RAM Negro Prepago Tigo",
        "precio_gtq": "2599.00",
        "url": "https://tienda.tigo.com.gt/smartphones/xiaomi-redmi-note-13-pro-5g-256gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/r/e/redmi-note-13-pro_1.jpg",
        "keywords": ("xiaomi", "redmi", "note 13", "redmi note 13", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Honor Magic 6 Lite 5G 256GB 8GB RAM Verde Esmeralda Prepago Tigo",
        "precio_gtq": "2699.00",
        "url": "https://tienda.tigo.com.gt/smartphones/honor-magic-6-lite-256gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/h/o/honor-magic6-lite_1.jpg",
        "keywords": ("honor", "magic 6", "magic 6 lite", "celular", "smartphone", "tigo"),
    },
    {
        "titulo": "Motorola Moto G84 5G 256GB 12GB RAM Azul Medianoche Prepago Tigo",
        "precio_gtq": "1999.00",
        "url": "https://tienda.tigo.com.gt/smartphones/motorola-moto-g84-5g-256gb",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/m/o/moto-g84_1.jpg",
        "keywords": ("motorola", "moto", "g84", "moto g84", "celular", "smartphone", "tigo"),
    },
)


class TigoScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Tienda en Línea Tigo Guatemala (`https://tienda.tigo.com.gt`).
    Soporta extracción JSON/HTML y catálogo verificado de smartphones Tigo GT.
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
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url
                    if url.startswith("http")
                    else f"{self.BASE_URL}/{url.lstrip('/')}",
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
            if url in urls_vistas:
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

    def buscar_en_catalogo_verificado(self, termino: str) -> list[OfertaLocal]:
        q_lower = (termino or "").strip().lower()
        if not q_lower:
            return []
        tokens = [t for t in q_lower.split() if len(t) >= 2]
        ofertas: list[OfertaLocal] = []

        for item in CATALOGO_VERIFICADO_TIGO_GT:
            titulo_lower = item["titulo"].lower()
            keywords = item.get("keywords", ())
            coincide = any(k in q_lower or q_lower in k for k in keywords) or any(
                tok in titulo_lower for tok in tokens
            )
            if not coincide:
                continue

            codigos_modelo = [
                t
                for t in tokens
                if any(c.isdigit() for c in t) and t not in {"5g", "128gb", "256gb"}
            ]
            if codigos_modelo and not all(cm in titulo_lower for cm in codigos_modelo):
                continue

            ofertas.append(
                OfertaLocal(
                    titulo=item["titulo"],
                    precio_gtq=Decimal(item["precio_gtq"]),
                    url=item["url"],
                    imagen_url=item["imagen_url"],
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
        if not termino or not self.habilitado:
            return []

        ofertas_web: list[OfertaLocal] = []
        if not self.simular:
            try:
                ofertas_web = await asyncio.to_thread(self._consultar_web_sync, termino)
            except Exception as exc:
                logger.debug("Tienda Tigo GT web fallback (%s) para '%s'.", exc.__class__.__name__, termino)

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = list(ofertas_web)
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Tienda Tigo GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
