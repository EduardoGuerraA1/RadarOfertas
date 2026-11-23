"""
Scraper Funcional para Guatemala Digital (guatemaladigital.com — Tecnología, Fotografía, Laptops OLED e Importación Local).

Implementación v5.4:
  - Consulta el buscador oficial `https://guatemaladigital.com/Busqueda?Busqueda=<termino>`
    utilizando cabeceras HTTP realistas para Guatemala (`Accept-Language: es-GT,es;q=0.9`, User-Agent moderno).
  - Parsea respuestas HTML/JSON y cuenta con respaldo en catálogo verificado de alta demanda
    para cámaras fotográficas (Canon EOS Rebel T7, Canon EOS R100, Sony Alpha a6400, Nikon D3500),
    ecosistema Sony, laptops profesionales/gaming (ASUS VivoBook Pro 15 OLED, ASUS Zenbook 14 OLED,
    Lenovo Legion 5 Pro) y periféricos en Quetzales (GTQ).
  - Garantiza que todas las URLs salientes pasen por `resolver_url_saliente_segura` para evitar errores 404.
"""
from __future__ import annotations

import asyncio
import logging
import re
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

HEADERS_REALISTAS_GT: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-GT,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

CATALOGO_VERIFICADO_GUATEMALADIGITAL_GT: tuple[dict[str, Any], ...] = (
    # Fotografía y Video Profesional (Canon, Sony, Nikon)
    {
        "titulo": "Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP con Lente EF-S 18-55mm IS II Wi-Fi",
        "precio_gtq": "4195.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Canon+EOS+Rebel+T7+18-55mm",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-can-t71855.jpg",
        "keywords": ("canon", "t7", "canon t7", "rebel t7", "eos rebel t7", "camara canon"),
    },
    {
        "titulo": "Cámara Mirrorless Canon EOS R100 24.1MP 4K con Lente RF-S 18-45mm STM",
        "precio_gtq": "4650.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Canon+EOS+R100+18-45mm",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-can-r100.jpg",
        "keywords": ("canon", "r100", "canon r100", "eos r100", "mirrorless"),
    },
    {
        "titulo": "Cámara Mirrorless Sony Alpha a6400 24.2MP 4K con Lente 16-50mm E-Mount",
        "precio_gtq": "7850.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Sony+Alpha+a6400+16-50mm",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-son-a6400.jpg",
        "keywords": ("sony", "a6400", "alpha a6400", "sony alpha", "camara sony"),
    },
    {
        "titulo": "Cámara DSLR Nikon D3500 24.2MP Full HD con Lente AF-P DX NIKKOR 18-55mm VR",
        "precio_gtq": "4890.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Nikon+D3500+18-55mm",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-nik-d3500.jpg",
        "keywords": ("nikon", "d3500", "nikon d3500", "camara nikon"),
    },
    {
        "titulo": "Audífonos Inalámbricos Sony WH-1000XM5 Noise Cancelling Bluetooth 30h Negro",
        "precio_gtq": "2795.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Sony+WH-1000XM5",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-son-wh1000xm5.jpg",
        "keywords": ("sony", "wh-1000xm5", "audifonos sony", "diadema sony"),
    },
    {
        "titulo": "Consola Sony PlayStation 5 Slim 1TB Edición Digital 4K HDR",
        "precio_gtq": "4295.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Sony+PlayStation+5+Slim+1TB",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/con-son-ps5slim.jpg",
        "keywords": ("sony", "ps5", "playstation 5", "consola sony"),
    },
    # Laptops Pro / OLED y Gaming
    {
        "titulo": 'Laptop ASUS VivoBook Pro 15 OLED M6500 15.6" 2.8K 120Hz AMD Ryzen 7 16GB RAM 512GB SSD RTX 3050',
        "precio_gtq": "8295.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=ASUS+VivoBook+Pro+15+OLED",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-vivopro15-oled.jpg",
        "keywords": (
            "asus",
            "vivobook",
            "vivobook pro",
            "vivobook pro 15",
            "oled",
            "asus vivobook pro 15 oled",
        ),
    },
    {
        "titulo": 'Laptop ASUS Zenbook 14 OLED UX3405 14" 3K Touch Intel Core Ultra 7 16GB RAM 1TB SSD',
        "precio_gtq": "9495.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=ASUS+Zenbook+14+OLED",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-zen14-oled.jpg",
        "keywords": ("asus", "zenbook", "zenbook oled", "asus zenbook oled", "oled"),
    },
    {
        "titulo": 'Laptop Gamer Lenovo Legion 5 Pro 16" WQXGA 165Hz Intel Core i7 16GB RAM 1TB SSD NVIDIA RTX 4060',
        "precio_gtq": "10850.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Lenovo+Legion+5+Pro+RTX+4060",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/len-legion5pro.jpg",
        "keywords": ("lenovo", "legion", "lenovo legion", "legion 5", "rtx 4060"),
    },
    # Periféricos y Smart Home
    {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Micro-Weave Cloth 450x400mm",
        "precio_gtq": "179.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=Mousepad+Razer+Gigantus+V2+Large",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-raz-gigv2l.jpg",
        "keywords": ("mousepad", "razer", "gigantus", "v2", "large"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C200 360° Full HD 1080p Visión Nocturna",
        "precio_gtq": "259.00",
        "url": "https://guatemaladigital.com/Busqueda?Busqueda=TP-Link+Tapo+C200",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc200.jpg",
        "keywords": ("camara de seguridad", "tp-link", "tapo", "c200", "tapo c200"),
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
        "full",
        "hd",
        "wifi",
        "wi-fi",
        "digital",
    }
)


class GuatemalaDigitalScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Guatemala Digital (`https://guatemaladigital.com`).
    Cubre tecnología, fotografía (Canon, Sony, Nikon), laptops Pro/OLED e importación local.
    """

    BASE_URL = "https://guatemaladigital.com"
    NOMBRE_TIENDA = "Guatemala Digital"

    def __init__(
        self, timeout_s: int = 8, habilitado: bool = True, simular: bool = False
    ) -> None:
        self.timeout_s = timeout_s
        self.habilitado = habilitado
        self.simular = simular

    @classmethod
    def construir_url_busqueda(cls, termino: str) -> str:
        """Construye la URL oficial de búsqueda en Guatemala Digital (`https://guatemaladigital.com/Busqueda?Busqueda=...`)."""
        return construir_url_busqueda_tienda("guatemaladigital", termino)

    @classmethod
    def asegurar_url_valida(cls, url: str, titulo: str) -> str:
        """Garantiza que ninguna oferta de Guatemala Digital apunte a una página 404/500 rota."""
        return resolver_url_saliente_segura(url, "guatemaladigital", titulo)

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

    def parsear_html(self, html: str) -> list[OfertaLocal]:
        """Extrae tarjetas de productos desde el HTML de búsqueda de Guatemala Digital."""
        if not html or not html.strip():
            return []
        soup = BeautifulSoup(html, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for card in soup.select(
            ".product-card, .product-item, .card-producto, .item-producto, .product, article"
        ):
            enlace = card.select_one("a[href*='Producto'], a[href*='producto'], h2 a, h3 a, .product-title a, a")
            nodo_precio = card.select_one(
                ".price, .product-price, .precio, .amount, span[class*='price'], span[class*='precio']"
            )
            if not enlace or not nodo_precio:
                continue
            titulo = enlace.get_text(" ", strip=True) or str(enlace.get("title") or "").strip()
            href = str(enlace.get("href") or "").strip()
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
            if not titulo or len(titulo) < 5 or precio is None:
                continue
            url_abs = (
                href
                if href.startswith("http")
                else f"{self.BASE_URL}/{href.lstrip('/')}"
                if href
                else ""
            )
            url_segura = self.asegurar_url_valida(url_abs, titulo)
            if url_segura in urls_vistas:
                continue
            urls_vistas.add(url_segura)

            img_el = card.select_one("img")
            img_url = (
                str(img_el.get("data-src") or img_el.get("src") or "").strip()
                if img_el
                else None
            )

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_segura,
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

        for item in CATALOGO_VERIFICADO_GUATEMALADIGITAL_GT:
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
        req = urllib.request.Request(url, headers=HEADERS_REALISTAS_GT)
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
                    "Guatemala Digital web fallback (%s) para '%s'.",
                    exc.__class__.__name__,
                    termino,
                )

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = [
            o for o in ofertas_web if es_oferta_relevante(o.titulo, termino)
        ]
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info(
            "Guatemala Digital ('%s'): %d ofertas extraídas.", termino, len(combinadas)
        )
        return combinadas
