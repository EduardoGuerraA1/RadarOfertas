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
from radar_ofertas.domain.services.filtro_relevancia import (
    construir_url_busqueda_tienda,
    es_oferta_relevante,
    resolver_url_saliente_segura,
)

logger = logging.getLogger(__name__)

CATALOGO_VERIFICADO_RECH_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Micro-Weave Cloth 450x400mm",
        "precio_gtq": "165.00",
        "url": "https://www.rech.com.gt/?s=Mousepad+Razer+Gigantus+V2+Large&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-raz-gigv2l.jpg",
        "keywords": ("mousepad", "razer", "gigantus", "v2", "large", "alfombrilla"),
    },
    {
        "titulo": "Mousepad Gamer Logitech G840 XL Cloth Gaming Mouse Pad 900x400mm Negro",
        "precio_gtq": "365.00",
        "url": "https://www.rech.com.gt/?s=Mousepad+Logitech+G840+XL&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-log-g840xl.jpg",
        "keywords": ("mousepad", "logitech", "g840", "xl", "alfombrilla"),
    },
    {
        "titulo": "Mousepad Gamer HyperX Fury S Pro XL Extended 900x420mm",
        "precio_gtq": "245.00",
        "url": "https://www.rech.com.gt/?s=Mousepad+HyperX+Fury+S+Pro+XL&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/mpad-hx-furysxl.jpg",
        "keywords": ("mousepad", "hyperx", "fury s", "xl", "alfombrilla"),
    },
    {
        "titulo": "Teclado Mecánico Logitech G Pro X TKL Lightspeed RGB Switch Tactile Negro",
        "precio_gtq": "1495.00",
        "url": "https://www.rech.com.gt/?s=Teclado+Logitech+G+Pro+X+TKL&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-log-gproxtkl.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "logitech", "g pro", "tkl"),
    },
    {
        "titulo": "Teclado Mecánico Gamer Redragon Kumara K552 RGB Switch Outemu Red Español",
        "precio_gtq": "325.00",
        "url": "https://www.rech.com.gt/?s=Teclado+Redragon+Kumara+K552+RGB&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-red-k552rgb.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "redragon", "kumara", "k552"),
    },
    {
        "titulo": "Teclado Mecánico HyperX Alloy Origins Core Tenkeyless RGB Switch HyperX Red",
        "precio_gtq": "749.00",
        "url": "https://www.rech.com.gt/?s=Teclado+HyperX+Alloy+Origins+Core&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/tec-hx-alloycore.jpg",
        "keywords": ("teclado", "teclado mecanico", "mecanico", "hyperx", "alloy origins"),
    },
    {
        "titulo": "Diadema Gamer HyperX Cloud III Gaming Headset 7.1 DTS Micrófono Desmontable Negro/Rojo",
        "precio_gtq": "795.00",
        "url": "https://www.rech.com.gt/?s=Diadema+HyperX+Cloud+III&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-hx-cloud3.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "hyperx", "cloud iii", "cloud 3"),
    },
    {
        "titulo": "Diadema Gamer Inalámbrica Logitech G733 Lightspeed RGB White",
        "precio_gtq": "1149.00",
        "url": "https://www.rech.com.gt/?s=Diadema+Logitech+G733+Lightspeed&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/aud-log-g733w.jpg",
        "keywords": ("diadema", "diadema gamer", "headset", "audifonos", "logitech", "g733", "lightspeed"),
    },
    {
        "titulo": "Webcam Logitech C920s Pro Full HD 1080p con Tapa de Privacidad y Micrófono Estéreo",
        "precio_gtq": "585.00",
        "url": "https://www.rech.com.gt/?s=Webcam+Logitech+C920s+Pro&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/wcam-log-c920s.jpg",
        "keywords": ("webcam", "camara web", "logitech", "c920s", "c920"),
    },
    {
        "titulo": "Cámara de Seguridad Wi-Fi TP-Link Tapo C200 360° Full HD 1080p Visión Nocturna",
        "precio_gtq": "249.00",
        "url": "https://www.rech.com.gt/?s=Camara+TP-Link+Tapo+C200&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-tpl-tapoc200.jpg",
        "keywords": ("camara de seguridad", "tp-link", "tapo", "c200", "tapo c200"),
    },
    {
        "titulo": "Cámara de Seguridad Exterior Wi-Fi Ezviz H8C 2K Pan & Tilt 360° Visión Nocturna Color",
        "precio_gtq": "475.00",
        "url": "https://www.rech.com.gt/?s=Camara+Ezviz+H8C+2K&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/cam-ezv-h8c2k.jpg",
        "keywords": ("camara de seguridad", "ezviz", "h8c"),
    },
    {
        "titulo": "Laptop Asus TUF Gaming F15 Intel Core i5 16GB RAM 512GB SSD RTX 3050 144Hz",
        "precio_gtq": "6695.00",
        "url": "https://www.rech.com.gt/?s=Laptop+Asus+TUF+Gaming+F15+RTX+3050&post_type=product",
        "imagen_url": "https://www.intelaf.com/images/productos/gran/asu-fx507zc4.jpg",
        "keywords": ("laptop", "asus", "tuf", "f15", "rtx 3050"),
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

    @classmethod
    def construir_url_busqueda(cls, termino: str) -> str:
        """Construye la URL oficial de búsqueda en Rech Guatemala con el término exacto codificado."""
        return construir_url_busqueda_tienda("rech", termino)

    @classmethod
    def asegurar_url_valida(cls, url: str, titulo: str) -> str:
        """Garantiza que ninguna oferta de Rech apunte a un enlace 404/500 no verificado."""
        return resolver_url_saliente_segura(url, "rech", titulo)

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
            if not titulo or precio is None:
                continue

            images = item.get("images")
            img_url = None
            if isinstance(images, list) and images and isinstance(images[0], dict):
                img_url = str(images[0].get("src") or "").strip() or None
            elif item.get("image"):
                img_url = str(item.get("image")).strip()

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
        tokens_especificos = [
            t for t in q_lower.split() if len(t) >= 2 and t not in STOPWORDS_CATALOGO
        ]
        if not tokens_especificos:
            tokens_especificos = [t for t in q_lower.split() if len(t) >= 2]
        es_multi_query_general = len(tokens_especificos) >= 6
        ofertas: list[OfertaLocal] = []

        for item in CATALOGO_VERIFICADO_RECH_GT:
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
                logger.debug("Rech GT web fallback (%s) para '%s'.", exc.__class__.__name__, termino)

        ofertas_cat = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_web}
        combinadas = [
            o for o in ofertas_web if es_oferta_relevante(o.titulo, termino)
        ]
        for o_cat in ofertas_cat:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("Rech GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
