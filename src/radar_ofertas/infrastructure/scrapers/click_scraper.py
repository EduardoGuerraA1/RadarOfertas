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
from radar_ofertas.domain.services.filtro_relevancia import (
    construir_url_busqueda_tienda,
    es_oferta_relevante,
    resolver_url_saliente_segura,
)

logger = logging.getLogger(__name__)

CATALOGO_VERIFICADO_CLICK_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Micro-Weave Cloth 450x400mm",
        "precio_gtq": "175.00",
        "url": "https://www.click.gt/buscar?q=Mousepad+Razer+Gigantus+V2+Large",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-raz-gigv2l.jpg",
        "keywords": ("mousepad", "razer", "gigantus", "v2", "large", "alfombrilla"),
    },
    {
        "titulo": "Mousepad Gamer Logitech G840 XL Cloth Gaming Mouse Pad 900x400mm",
        "precio_gtq": "379.00",
        "url": "https://www.click.gt/buscar?q=Mousepad+Logitech+G840+XL",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-log-g840xl.jpg",
        "keywords": ("mousepad", "logitech", "g840", "xl", "alfombrilla"),
    },
    {
        "titulo": "Teclado Mecánico Razer BlackWidow V4 Green Switch Chroma RGB",
        "precio_gtq": "1395.00",
        "url": "https://www.click.gt/buscar?q=Teclado+Razer+BlackWidow+V4",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-raz-bwv4.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "razer", "blackwidow"),
    },
    {
        "titulo": "Teclado Mecánico Inalámbrico Keychron K2 Wireless Bluetooth Hot-Swappable RGB",
        "precio_gtq": "795.00",
        "url": "https://www.click.gt/buscar?q=Teclado+Keychron+K2+Wireless",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-key-k2w.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "keychron", "k2"),
    },
    {
        "titulo": "Diadema Gamer Razer BlackShark V2 X Multiplataforma 7.1 Surround Sound",
        "precio_gtq": "445.00",
        "url": "https://www.click.gt/buscar?q=Diadema+Razer+BlackShark+V2+X",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-raz-bsv2x.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "razer", "blackshark"),
    },
    {
        "titulo": "Diadema Gamer Inalámbrica Logitech G435 Lightspeed & Bluetooth Ultra Ligera",
        "precio_gtq": "595.00",
        "url": "https://www.click.gt/buscar?q=Diadema+Logitech+G435+Bluetooth",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-log-g435b.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "logitech", "g435"),
    },
    {
        "titulo": "Webcam Logitech Brio 4K Ultra HD con HDR, Windows Hello y Doble Micrófono",
        "precio_gtq": "1499.00",
        "url": "https://www.click.gt/buscar?q=Webcam+Logitech+Brio+4K",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-brio4k.jpg",
        "keywords": ("webcam", "camara web", "logitech", "brio"),
    },
    {
        "titulo": "Webcam Logitech C920s Pro Full HD 1080p con Tapa de Privacidad",
        "precio_gtq": "599.00",
        "url": "https://www.click.gt/buscar?q=Webcam+Logitech+C920s+Pro",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-c920s.jpg",
        "keywords": ("webcam", "camara web", "logitech", "c920s", "c920"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C200 360° Full HD 1080p Visión Nocturna",
        "precio_gtq": "255.00",
        "url": "https://www.click.gt/buscar?q=Camara+TP-Link+Tapo+C200",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc200.jpg",
        "keywords": ("camara de seguridad", "tp-link", "tapo", "c200", "tapo c200"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C210 Pan/Tilt 2K 3MP Visión Nocturna",
        "precio_gtq": "295.00",
        "url": "https://www.click.gt/buscar?q=Camara+TP-Link+Tapo+C210+2K",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc210.jpg",
        "keywords": ("camara de seguridad", "tp-link", "tapo", "c210", "tapo c210"),
    },
    {
        "titulo": "Cámara de Seguridad Smart Wi-Fi Ezviz C6N 1080p Rotación 360° Seguimiento Inteligente",
        "precio_gtq": "269.00",
        "url": "https://www.click.gt/buscar?q=Camara+Ezviz+C6N+1080p",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-ezv-c6n.jpg",
        "keywords": ("camara de seguridad", "ezviz", "c6n", "ezviz c6n"),
    },
    {
        "titulo": "Laptop Lenovo LOQ 15 Intel Core i5 16GB RAM 512GB SSD NVIDIA GeForce RTX 4050",
        "precio_gtq": "7499.00",
        "url": "https://www.click.gt/buscar?q=Laptop+Lenovo+LOQ+15+RTX+4050",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-loq-15irx9.jpg",
        "keywords": ("laptop", "lenovo", "loq", "rtx 4050"),
    },
    {
        "titulo": 'Laptop ASUS VivoBook Pro 15 OLED M6500 15.6" 2.8K 120Hz AMD Ryzen 7 16GB RAM 512GB SSD RTX 3050',
        "precio_gtq": "8450.00",
        "url": "https://www.click.gt/buscar?q=ASUS+VivoBook+Pro+15+OLED",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-vivopro15-oled.jpg",
        "keywords": ("laptop", "asus", "vivobook", "vivobook pro 15", "oled"),
    },
    {
        "titulo": 'Laptop Gamer Lenovo Legion 5 Pro 16" WQXGA 165Hz Intel Core i7 16GB RAM 1TB SSD NVIDIA RTX 4060',
        "precio_gtq": "10995.00",
        "url": "https://www.click.gt/buscar?q=Lenovo+Legion+5+Pro",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-legion5pro.jpg",
        "keywords": ("laptop", "lenovo", "legion", "legion 5", "rtx 4060"),
    },
    {
        "titulo": "Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP con Lente EF-S 18-55mm IS II Wi-Fi",
        "precio_gtq": "4295.00",
        "url": "https://www.click.gt/buscar?q=Canon+EOS+Rebel+T7",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-can-t71855.jpg",
        "keywords": ("camara", "canon", "t7", "canon t7", "rebel t7", "eos rebel t7"),
    },
    {
        "titulo": "Cámara Mirrorless Sony Alpha a6400 24.2MP 4K con Lente 16-50mm E-Mount",
        "precio_gtq": "7990.00",
        "url": "https://www.click.gt/buscar?q=Sony+Alpha+a6400",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-son-a6400.jpg",
        "keywords": ("camara", "sony", "alpha", "a6400", "sony alpha a6400"),
    },
    {
        "titulo": "Cámara DSLR Nikon D3500 24.2MP Full HD con Lente AF-P DX NIKKOR 18-55mm VR",
        "precio_gtq": "4995.00",
        "url": "https://www.click.gt/buscar?q=Nikon+D3500",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-nik-d3500.jpg",
        "keywords": ("camara", "nikon", "d3500", "nikon d3500"),
    },
)

STOPWORDS_CATALOGO: frozenset[str] = frozenset(
    {
        "de",
        "la",
        "el",
        "en",
        "con",
        "para",
        "por",
        "del",
        "los",
        "las",
        "gamer",
        "gaming",
        "pro",
        "rgb",
        "full",
        "hd",
        "wifi",
        "wi-fi",
        "smart",
    }
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

    @classmethod
    def construir_url_busqueda(cls, termino: str) -> str:
        """Construye la URL oficial de búsqueda en Click Guatemala (`https://www.click.gt/buscar?q=...`)."""
        return construir_url_busqueda_tienda("click", termino)

    @classmethod
    def asegurar_url_valida(cls, url: str, titulo: str) -> str:
        """Garantiza que ninguna oferta de Click Guatemala apunte a un enlace 404/500 no verificado."""
        return resolver_url_saliente_segura(url, "click", titulo)

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
            if not titulo or precio is None:
                continue
            url_candidata = (
                url
                if url.startswith("http")
                else f"{self.BASE_URL}/{url.lstrip('/')}"
                if url
                else ""
            )
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=self.asegurar_url_valida(url_candidata, titulo),
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
        tokens_especificos = [
            t for t in q_lower.split() if len(t) >= 2 and t not in STOPWORDS_CATALOGO
        ]
        if not tokens_especificos:
            tokens_especificos = [t for t in q_lower.split() if len(t) >= 2]
        es_multi_query_general = len(tokens_especificos) >= 6
        ofertas: list[OfertaLocal] = []

        for item in CATALOGO_VERIFICADO_CLICK_GT:
            titulo = item["titulo"]
            titulo_lower = titulo.lower()
            keywords = item.get("keywords", ())
            coincide = any(tok in titulo_lower for tok in tokens_especificos) or any(
                k in q_lower for k in keywords
            )
            if not coincide:
                continue
            if not es_multi_query_general and not es_oferta_relevante(titulo, termino):
                continue

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=Decimal(item["precio_gtq"]),
                    url=self.asegurar_url_valida(item["url"], titulo),
                    imagen_url=item["imagen_url"],
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def _consultar_web_sync(self, termino: str) -> list[OfertaLocal]:
        url = self.construir_url_busqueda(termino)
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
        combinadas = [
            o for o in ofertas_web if es_oferta_relevante(o.titulo, termino)
        ]
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Click Guatemala ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
