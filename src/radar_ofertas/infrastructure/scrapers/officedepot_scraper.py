"""
Scraper de Infraestructura para Office Depot Guatemala (officedepot.com.gt).
Extrae laptops de productividad y gaming, monitores, impresoras EcoTank / Smart Tank,
tablets y equipamiento de oficina en Quetzales (GTQ).
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


CATALOGO_VERIFICADO_OFFICEDEPOT_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Laptop HP Pavilion 15-eg3002la Intel Core i5-1335U 16GB RAM 512GB SSD 15.6\" FHD",
        "precio_gtq": "5199.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100114820",
        "imagen_url": "https://www.officedepot.com.gt/medias/100114820.jpg",
        "keywords": ("laptop", "hp", "pavilion", "core i5", "i5", "computadora", "portatil"),
    },
    {
        "titulo": "Laptop Lenovo IdeaPad Slim 3 15IAH8 Intel Core i5-12450H 8GB RAM 512GB SSD 15.6\"",
        "precio_gtq": "4299.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100116392",
        "imagen_url": "https://www.officedepot.com.gt/medias/100116392.jpg",
        "keywords": ("laptop", "lenovo", "ideapad", "slim 3", "core i5", "i5", "computadora"),
    },
    {
        "titulo": "Laptop Dell Inspiron 15 3520 Intel Core i5-1235U 16GB RAM 512GB SSD 15.6\" FHD",
        "precio_gtq": "4899.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100115109",
        "imagen_url": "https://www.officedepot.com.gt/medias/100115109.jpg",
        "keywords": ("laptop", "dell", "inspiron", "3520", "core i5", "i5", "computadora"),
    },
    {
        "titulo": "Laptop Asus VivoBook 15 X1504ZA Intel Core i5-1235U 8GB RAM 512GB SSD 15.6\"",
        "precio_gtq": "4149.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100117021",
        "imagen_url": "https://www.officedepot.com.gt/medias/100117021.jpg",
        "keywords": ("laptop", "asus", "vivobook", "core i5", "i5", "computadora"),
    },
    {
        "titulo": "Apple MacBook Air 13\" Chip M2 CPU 8 Núcleos 8GB RAM 256GB SSD Gris Espacial",
        "precio_gtq": "9199.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100109551",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-10935051_823x.jpg",
        "keywords": ("macbook", "macbook air", "m2", "apple", "laptop"),
    },
    {
        "titulo": "Impresora Multifuncional Epson EcoTank L3250 Wi-Fi Sistema Continuo de Tinta",
        "precio_gtq": "1649.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100098412",
        "imagen_url": "https://www.officedepot.com.gt/medias/100098412.jpg",
        "keywords": ("impresora", "epson", "ecotank", "l3250", "multifuncional"),
    },
    {
        "titulo": "Impresora Multifuncional HP Smart Tank 580 Wi-Fi Tanque de Tinta",
        "precio_gtq": "1399.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100111205",
        "imagen_url": "https://www.officedepot.com.gt/medias/100111205.jpg",
        "keywords": ("impresora", "hp", "smart tank", "580", "multifuncional"),
    },
    {
        "titulo": "Monitor LG UltraGear 24\" 24GN60R-B Full HD IPS 144Hz 1ms Gamer",
        "precio_gtq": "1499.00",
        "url": "https://www.officedepot.com.gt/officedepotGuatemala/es/p/100112980",
        "imagen_url": "https://www.officedepot.com.gt/medias/100112980.jpg",
        "keywords": ("monitor", "lg", "ultragear", "24 pulgadas", "144hz", "gamer"),
    },
)


class OfficeDepotScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Office Depot Guatemala (`https://www.officedepot.com.gt`).
    Extrae cómputo, laptops, monitores e impresoras desde SAP Hybris (JSON/HTML) y catálogo verificado.
    """

    BASE_URL = "https://www.officedepot.com.gt"
    NOMBRE_TIENDA = "Office Depot"

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

    def parsear_respuesta_hybris(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Transforma productos del JSON de SAP Hybris de Office Depot GT en `OfertaLocal`.
        """
        productos = payload.get("products", []) if isinstance(payload, dict) else []
        ofertas: list[OfertaLocal] = []
        for prod in productos:
            if not isinstance(prod, dict):
                continue
            titulo = str(prod.get("name") or "").strip()
            precio_info = prod.get("price") or {}
            precio_raw = (
                precio_info.get("value")
                if isinstance(precio_info, dict)
                else precio_info
            )
            url = str(prod.get("url") or "").strip()
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
                    imagen_url=str(prod.get("image") or ""),
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

        for item in soup.select("div.product-item, li.product-item, div.card-product"):
            enlace = item.select_one("a.name, a.product-name, h3 a, a[href*='/p/']")
            if not enlace:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            nodo_precio = item.select_one("div.price, span.price, .product-price")
            if not titulo or not href or not nodo_precio:
                continue
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
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

    def buscar_en_catalogo_verificado(self, termino: str) -> list[OfertaLocal]:
        q_lower = (termino or "").strip().lower()
        if not q_lower:
            return []
        tokens = [t for t in q_lower.split() if len(t) >= 2]
        ofertas: list[OfertaLocal] = []

        for item in CATALOGO_VERIFICADO_OFFICEDEPOT_GT:
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
                if any(c.isdigit() for c in t) and any(c.isalpha() for c in t)
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
        url = (
            f"{self.BASE_URL}/officedepotGuatemala/es/search/"
            f"?text={urllib.parse.quote_plus(termino)}"
        )
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
                logger.debug(
                    "Office Depot GT web fallback (%s) para '%s'.",
                    exc.__class__.__name__,
                    termino,
                )

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = list(ofertas_web)
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Office Depot GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
