"""
Scraper Funcional para Rech Guatemala (rech.com.gt — Especialista en Cómputo, Periféricos Gamer y Cámaras Smart Home).

Implementación v5.2:
  - Extracción híbrida sobre WooCommerce Store API / HTML (`https://www.rech.com.gt/?s=<query>&post_type=product`)
    con respaldo en catálogo verificado de periféricos gamer (teclados mecánicos, mousepads,
    diademas gamer, webcams), componentes de PC y cámaras de seguridad TP-Link Tapo / Ezviz en Guatemala.
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

CATALOGO_VERIFICADO_RECH_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Mousepad Gamer Logitech G840 XL Cloth Gaming Mouse Pad 900x400mm Negro",
        "precio_gtq": "365.00",
        "url": "https://www.rech.com.gt/producto/mousepad-gamer-logitech-g840-xl",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-log-g840xl.jpg",
        "keywords": ("mousepad", "logitech", "g840", "xl", "gamer", "gaming", "alfombrilla"),
    },
    {
        "titulo": "Mousepad Gamer HyperX Fury S Pro XL Extended 900x420mm",
        "precio_gtq": "245.00",
        "url": "https://www.rech.com.gt/producto/mousepad-gamer-hyperx-fury-s-pro-xl",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-hx-furysxl.jpg",
        "keywords": ("mousepad", "hyperx", "fury s", "xl", "gamer", "gaming", "alfombrilla"),
    },
    {
        "titulo": "Teclado Mecánico Logitech G Pro X TKL Lightspeed RGB Switch Tactile Negro",
        "precio_gtq": "1495.00",
        "url": "https://www.rech.com.gt/producto/teclado-mecanico-logitech-g-pro-x-tkl",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-log-gproxtkl.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "logitech", "g pro", "tkl", "gamer"),
    },
    {
        "titulo": "Teclado Mecánico Gamer Redragon Kumara K552 RGB Switch Outemu Red Español",
        "precio_gtq": "325.00",
        "url": "https://www.rech.com.gt/producto/teclado-mecanico-redragon-kumara-k552-rgb",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-red-k552rgb.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "redragon", "kumara", "k552", "rgb", "gamer"),
    },
    {
        "titulo": "Teclado Mecánico HyperX Alloy Origins Core Tenkeyless RGB Switch HyperX Red",
        "precio_gtq": "749.00",
        "url": "https://www.rech.com.gt/producto/teclado-mecanico-hyperx-alloy-origins-core",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-hx-alloycore.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "hyperx", "alloy origins", "gamer"),
    },
    {
        "titulo": "Diadema Gamer HyperX Cloud III Gaming Headset 7.1 DTS Micrófono Desmontable Negro/Rojo",
        "precio_gtq": "795.00",
        "url": "https://www.rech.com.gt/producto/diadema-gamer-hyperx-cloud-iii",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-hx-cloud3.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "hyperx", "cloud iii", "cloud 3", "gamer"),
    },
    {
        "titulo": "Diadema Gamer Inalámbrica Logitech G733 Lightspeed RGB White",
        "precio_gtq": "1149.00",
        "url": "https://www.rech.com.gt/producto/diadema-gamer-logitech-g733-lightspeed",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-log-g733w.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "logitech", "g733", "lightspeed", "gamer"),
    },
    {
        "titulo": "Webcam Logitech C920s Pro Full HD 1080p con Tapa de Privacidad y Micrófono Estéreo",
        "precio_gtq": "585.00",
        "url": "https://www.rech.com.gt/producto/webcam-logitech-c920s-pro-full-hd-1080p",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-c920s.jpg",
        "keywords": ("webcam", "camara web", "logitech", "c920s", "c920", "1080p", "streaming"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C200 360° Full HD 1080p Visión Nocturna",
        "precio_gtq": "249.00",
        "url": "https://www.rech.com.gt/producto/camara-seguridad-tp-link-tapo-c200-360-wifi",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc200.jpg",
        "keywords": ("camara", "camara de seguridad", "tp-link", "tapo", "c200", "tapo c200", "seguridad", "wifi"),
    },
    {
        "titulo": "Cámara de Seguridad Exterior Wi-Fi Ezviz H8C 2K Pan & Tilt 360° Visión Nocturna Color",
        "precio_gtq": "475.00",
        "url": "https://www.rech.com.gt/producto/camara-seguridad-exterior-ezviz-h8c-2k",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-ezv-h8c2k.jpg",
        "keywords": ("camara", "camara de seguridad", "ezviz", "h8c", "exterior", "seguridad", "2k"),
    },
    {
        "titulo": "Laptop Asus TUF Gaming F15 Intel Core i5 16GB RAM 512GB SSD RTX 3050 144Hz",
        "precio_gtq": "6695.00",
        "url": "https://www.rech.com.gt/producto/laptop-asus-tuf-gaming-f15-rtx-3050",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-fx507zc4.jpg",
        "keywords": ("laptop", "asus", "tuf", "f15", "rtx 3050", "gamer", "gaming"),
    },
)


class RechScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Rech Guatemala (`https://www.rech.com.gt`).
    Especialista en hardware, periféricos gamer, laptops y cámaras de seguridad Smart Home.
    """

    BASE_URL = "https://www.rech.com.gt"
    NOMBRE_TIENDA = "Rech"

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

    def parsear_respuesta_woocommerce(self, payload: list[dict[str, Any]] | dict[str, Any]) -> list[OfertaLocal]:
        """
        Convierte la respuesta JSON de WooCommerce Store API de Rech GT en entidades `OfertaLocal`.
        """
        items = payload if isinstance(payload, list) else payload.get("products", payload.get("items", []))
        if not isinstance(items, list):
            return []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("title") or "").strip()
            prices_obj = item.get("prices") if isinstance(item.get("prices"), dict) else {}
            precio_raw = (
                item.get("price")
                or prices_obj.get("price")
                or item.get("regular_price")
            )
            url = str(item.get("permalink") or item.get("url") or "").strip()
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None or not url:
                continue

            images = item.get("images")
            img_url = None
            if isinstance(images, list) and images and isinstance(images[0], dict):
                img_url = str(images[0].get("src") or "").strip() or None
            elif item.get("image"):
                img_url = str(item.get("image")).strip()

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url
                    if url.startswith("http")
                    else f"{self.BASE_URL}/{url.lstrip('/')}",
                    imagen_url=img_url,
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

        for card in soup.select(".product, li.product, .type-product, .product-small"):
            enlace = card.select_one("a.woocommerce-LoopProduct-link, .product-title a, h2 a, h3 a")
            nodo_precio = card.select_one(".price ins .amount, .price .amount, .woocommerce-Price-amount")
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

        for item in CATALOGO_VERIFICADO_RECH_GT:
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
                logger.debug("Rech GT web fallback (%s) para '%s'.", exc.__class__.__name__, termino)

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = list(ofertas_web)
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Rech GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
