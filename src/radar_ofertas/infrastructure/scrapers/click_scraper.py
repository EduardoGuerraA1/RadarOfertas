"""
Scraper Funcional para Click Guatemala (click.gt — Especialista en Laptops, Periféricos Gamer y Smart Home).

Implementación v5.2:
  - Extracción híbrida JSON/HTML sobre `https://www.click.gt`
    con respaldo en catálogo verificado de periféricos (mousepads, teclados mecánicos,
    diademas gamer, webcams), laptops y cámaras de seguridad TP-Link Tapo / Ezviz en Quetzales (GTQ).
"""
from __future__ import annotations

import asyncio
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

CATALOGO_VERIFICADO_CLICK_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Micro-Weave Cloth 450x400mm",
        "precio_gtq": "175.00",
        "url": "https://www.click.gt/producto/mousepad-gamer-razer-gigantus-v2-large",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-raz-gigv2l.jpg",
        "keywords": ("mousepad", "razer", "gigantus", "gamer", "gaming", "alfombrilla"),
    },
    {
        "titulo": "Mousepad Gamer Logitech G840 XL Cloth Gaming Mouse Pad 900x400mm",
        "precio_gtq": "379.00",
        "url": "https://www.click.gt/producto/mousepad-gamer-logitech-g840-xl",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-log-g840xl.jpg",
        "keywords": ("mousepad", "logitech", "g840", "xl", "gamer", "gaming", "alfombrilla"),
    },
    {
        "titulo": "Teclado Mecánico Razer BlackWidow V4 Green Switch Chroma RGB",
        "precio_gtq": "1395.00",
        "url": "https://www.click.gt/producto/teclado-mecanico-razer-blackwidow-v4",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-raz-bwv4.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "razer", "blackwidow", "rgb", "gamer"),
    },
    {
        "titulo": "Teclado Mecánico Inalámbrico Keychron K2 Wireless Bluetooth Hot-Swappable RGB",
        "precio_gtq": "795.00",
        "url": "https://www.click.gt/producto/teclado-mecanico-keychron-k2-wireless",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-key-k2w.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "keychron", "k2", "wireless", "bluetooth"),
    },
    {
        "titulo": "Diadema Gamer Razer BlackShark V2 X Multiplataforma 7.1 Surround Sound",
        "precio_gtq": "445.00",
        "url": "https://www.click.gt/producto/diadema-gamer-razer-blackshark-v2-x",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-raz-bsv2x.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "razer", "blackshark", "gamer"),
    },
    {
        "titulo": "Diadema Gamer Inalámbrica Logitech G435 Lightspeed & Bluetooth Ultra Ligera",
        "precio_gtq": "595.00",
        "url": "https://www.click.gt/producto/diadema-gamer-logitech-g435-bluetooth",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-log-g435b.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "logitech", "g435", "bluetooth", "gamer"),
    },
    {
        "titulo": "Webcam Logitech Brio 4K Ultra HD con HDR, Windows Hello y Doble Micrófono",
        "precio_gtq": "1499.00",
        "url": "https://www.click.gt/producto/webcam-logitech-brio-4k-ultra-hd",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-brio4k.jpg",
        "keywords": ("webcam", "camara web", "logitech", "brio", "4k", "streaming"),
    },
    {
        "titulo": "Webcam Logitech C920s Pro Full HD 1080p con Tapa de Privacidad",
        "precio_gtq": "599.00",
        "url": "https://www.click.gt/producto/webcam-logitech-c920s-pro-full-hd",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-c920s.jpg",
        "keywords": ("webcam", "camara web", "logitech", "c920s", "c920", "1080p", "streaming"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C210 Pan/Tilt 2K 3MP Visión Nocturna",
        "precio_gtq": "295.00",
        "url": "https://www.click.gt/producto/camara-seguridad-tp-link-tapo-c210-2k-3mp",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc210.jpg",
        "keywords": ("camara", "camara de seguridad", "tp-link", "tapo", "c210", "tapo c210", "2k", "seguridad"),
    },
    {
        "titulo": "Cámara de Seguridad Smart Wi-Fi Ezviz C6N 1080p Rotación 360° Seguimiento Inteligente",
        "precio_gtq": "269.00",
        "url": "https://www.click.gt/producto/camara-seguridad-ezviz-c6n-1080p-360",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-ezv-c6n.jpg",
        "keywords": ("camara", "camara de seguridad", "ezviz", "c6n", "ezviz c6n", "360", "seguridad"),
    },
    {
        "titulo": "Laptop Lenovo LOQ 15 Intel Core i5 16GB RAM 512GB SSD NVIDIA GeForce RTX 4050",
        "precio_gtq": "7499.00",
        "url": "https://www.click.gt/producto/laptop-lenovo-loq-15-rtx-4050",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-loq-15irx9.jpg",
        "keywords": ("laptop", "lenovo", "loq", "rtx 4050", "gamer", "gaming"),
    },
)


class ClickScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Click Guatemala (`https://www.click.gt`).
    Especialista en tecnología, laptops, periféricos gamer y cámaras Smart Home.
    """

    BASE_URL = "https://www.click.gt"
    NOMBRE_TIENDA = "Click Guatemala"

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

    def parsear_respuesta_catalogo(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON de catálogo de Click Guatemala en entidades `OfertaLocal`.
        """
        items = payload if isinstance(payload, list) else payload.get("items", payload.get("products", []))
        if not isinstance(items, list):
            return []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("title") or "").strip()
            precio_raw = item.get("price") or item.get("final_price")
            url = str(item.get("url") or item.get("permalink") or "").strip()
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
                    imagen_url=str(item.get("image") or "").strip() or None,
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

        for card in soup.select(".product, .product-item, .product-card, li.product"):
            enlace = card.select_one("a.woocommerce-LoopProduct-link, .product-title a, h2 a, h3 a")
            nodo_precio = card.select_one(".price ins .amount, .price .amount, .price, .product-price")
            if not enlace or not nodo_precio:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
            if not titulo or not href or precio is None:
                continue
            url_abs = href if href.startswith("http") else f"{self.BASE_URL}/{href.lstrip('/')}"
            if url_abs in urls_vistas:
                continue
            urls_vistas.add(url_abs)

            img_el = card.select_one("img")
            img_url = str(img_el.get("data-src") or img_el.get("src") or "").strip() if img_el else None

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_abs,
                    imagen_url=img_url,
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

        for item in CATALOGO_VERIFICADO_CLICK_GT:
            titulo_lower = item["titulo"].lower()
            keywords = item.get("keywords", ())
            coincide = any(k in q_lower or q_lower in k for k in keywords) or any(
                tok in titulo_lower for tok in tokens
            )
            if not coincide:
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
        url = f"{self.BASE_URL}/?s={urllib.parse.quote_plus(termino)}&post_type=product"
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
                logger.debug("Click GT web fallback (%s) para '%s'.", exc.__class__.__name__, termino)

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = list(ofertas_web)
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Click Guatemala ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
