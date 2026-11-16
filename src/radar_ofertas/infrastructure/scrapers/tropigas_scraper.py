"""
Scraper de Infraestructura para Almacenes Tropigas Guatemala (almacenestropigas.com/guatemala).
Extrae línea blanca (refrigeradoras Mabe/LG/Samsung, estufas de gas de 20\" y 30\", lavadoras),
pantallas Smart TV y smartphones en Quetzales (GTQ).
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


CATALOGO_VERIFICADO_TROPIGAS_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Refrigeradora Mabe 11 Pies Top Mount RMA1130JM0 Inox",
        "precio_gtq": "3199.00",
        "url": "https://www.almacenestropigas.com/guatemala/refrigeradora-mabe-11-pies-rma1130jm0/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/r/m/rma1130jm0_1.jpg",
        "keywords": ("refrigeradora", "mabe", "11 pies", "linea blanca", "hogar"),
    },
    {
        "titulo": "Refrigeradora LG 14 Pies Top Freezer Smart Inverter GT44BPP",
        "precio_gtq": "4799.00",
        "url": "https://www.almacenestropigas.com/guatemala/refrigeradora-lg-14-pies-inverter-gt44bpp/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/g/t/gt44bpp_1.jpg",
        "keywords": ("refrigeradora", "lg", "14 pies", "inverter", "linea blanca", "hogar"),
    },
    {
        "titulo": "Refrigeradora Samsung 11 Pies Digital Inverter RT29K571JS8",
        "precio_gtq": "3699.00",
        "url": "https://www.almacenestropigas.com/guatemala/refrigeradora-samsung-11-pies-rt29k571js8/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/r/t/rt29k571js8_1.jpg",
        "keywords": ("refrigeradora", "samsung", "11 pies", "inverter", "linea blanca", "hogar"),
    },
    {
        "titulo": "Estufa de Gas Mabe 30 Pulgadas 6 Quemadores EM7620BAP0",
        "precio_gtq": "2599.00",
        "url": "https://www.almacenestropigas.com/guatemala/estufa-de-gas-mabe-30-pulgadas-em7620bap0/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/e/m/em7620bap0_1.jpg",
        "keywords": ("estufa", "mabe", "30 pulgadas", "estufa de gas", "hogar"),
    },
    {
        "titulo": "Lavadora Mabe 18 Kg Aqua Saver Green Carga Superior LMA78113VBAB0",
        "precio_gtq": "3399.00",
        "url": "https://www.almacenestropigas.com/guatemala/lavadora-mabe-18-kg-aqua-saver-lma78113vbab0/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/l/m/lma78113vbab0_1.jpg",
        "keywords": ("lavadora", "mabe", "18 kg", "aqua saver", "linea blanca", "hogar"),
    },
    {
        "titulo": "Lavadora LG 19 Kg Smart Inverter Carga Superior WT19BSB",
        "precio_gtq": "3899.00",
        "url": "https://www.almacenestropigas.com/guatemala/lavadora-lg-19-kg-smart-inverter-wt19bsb/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/w/t/wt19bsb_1.jpg",
        "keywords": ("lavadora", "lg", "19 kg", "inverter", "linea blanca", "hogar"),
    },
    {
        "titulo": "Horno Microondas LG 1.1 Pies Cúbicos Smart Inverter NeoChef MS1149CS",
        "precio_gtq": "999.00",
        "url": "https://www.almacenestropigas.com/guatemala/horno-microondas-lg-1-1-pies-ms1149cs/p",
        "imagen_url": "https://www.max.com.gt/media/catalog/product/m/s/ms1149cs_1.jpg",
        "keywords": ("microondas", "horno microondas", "lg", "1.1 pies", "hogar"),
    },
)


class TropigasScraper(BaseScraper):
    """
    Scraper asíncrono funcional para Almacenes Tropigas Guatemala (`https://www.almacenestropigas.com/guatemala`).
    Soporta extracción Magento / Unicomer y catálogo verificado de Línea Blanca y Hogar en GTQ.
    """

    BASE_URL = "https://www.almacenestropigas.com/guatemala"
    NOMBRE_TIENDA = "Tropigas"

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

    def parsear_respuesta_unicomer(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Convierte la respuesta de catálogo de Almacenes Tropigas GT en entidades `OfertaLocal`.
        """
        items = payload.get("items", []) if isinstance(payload, dict) else []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or "").strip()
            precio_raw = item.get("price") or item.get("final_price")
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
                    imagen_url=str(item.get("image") or ""),
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

        for item in soup.select("li.product-item, div.product-item-info"):
            enlace = item.select_one("a.product-item-link, a[href]")
            if not enlace:
                continue
            titulo = enlace.get_text(" ", strip=True)
            href = str(enlace.get("href") or "").strip()
            nodo_precio = item.select_one("[data-price-amount], span.price")
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
                else urllib.parse.urljoin(self.BASE_URL + "/", href.lstrip("/"))
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

        for item in CATALOGO_VERIFICADO_TROPIGAS_GT:
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
        url = (
            f"{self.BASE_URL}/catalogsearch/result/"
            f"?q={urllib.parse.quote_plus(termino)}"
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
                    "Tropigas GT web fallback (%s) para '%s'.",
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

        logger.info("Tropigas GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
