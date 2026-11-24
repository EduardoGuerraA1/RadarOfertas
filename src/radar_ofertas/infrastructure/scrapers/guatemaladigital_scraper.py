"""
Scraper Real para Guatemala Digital (guatemaladigital.com — Tecnología, Fotografía, Laptops e Importación Local).

Implementación v5.5 (Tolerancia Cero a Datos Sintéticos):
  - Sin listas estáticas (`CATALOGO_VERIFICADO_*` eliminado por completo).
  - Consulta en tiempo real la API oficial `https://webapi.guatemaladigital.click/api/Busqueda`
    y el HTML de `https://guatemaladigital.com`.
  - Extrae exclusivamente el título real (`Descripcion`), precio real en Quetzales (`Precio`),
    imagen real (`Foto`) y la URL directa real del producto (`https://guatemaladigital.com/Producto/<CodigoProducto>`).
  - Si la tienda no responde o no tiene el producto, devuelve `[]`.
"""
from __future__ import annotations

import asyncio
import json
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

HEADERS_REALISTAS_GT: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "es-GT,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://guatemaladigital.com",
    "Referer": "https://guatemaladigital.com/",
}


class GuatemalaDigitalScraper(BaseScraper):
    """
    Scraper asíncrono 100% real para Guatemala Digital (`https://guatemaladigital.com`).
    Sin catálogos estáticos: devuelve únicamente productos reales con URL directa verificada.
    """

    BASE_URL = "https://guatemaladigital.com"
    API_BUSQUEDA_URL = "https://webapi.guatemaladigital.click/api/Busqueda"
    NOMBRE_TIENDA = "Guatemala Digital"

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
        if not texto or texto.lower() in {"ver precio", "comprar", "gratis", "0"}:
            return None
        limpio = re.sub(r"[^\d.,]", "", texto)
        if not limpio:
            return None
        limpio = limpio.replace(",", "")
        try:
            dec = Decimal(limpio).quantize(Decimal("0.01"))
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    @classmethod
    def _construir_url_producto_directa(cls, item: dict[str, Any]) -> str:
        """
        Construye la URL directa real de ficha de producto en Guatemala Digital:
          - `https://guatemaladigital.com/Producto/<CodigoProducto>`
          - o `https://guatemaladigital.com/ProductoP/<CodigoAmazon>` si `CodigoProducto == 0`.
        """
        codigo_prod = item.get("CodigoProducto")
        try:
            cod_int = int(codigo_prod or 0)
        except (ValueError, TypeError):
            cod_int = 0

        if cod_int > 0:
            return f"{cls.BASE_URL}/Producto/{cod_int}"

        codigo_amz = str(item.get("CodigoAmazon") or "").strip()
        if codigo_amz:
            return f"{cls.BASE_URL}/ProductoP/{codigo_amz}"

        link_raw = str(item.get("Link") or item.get("url") or "").strip()
        if link_raw:
            url_abs = (
                link_raw
                if link_raw.startswith("http")
                else f"{cls.BASE_URL}/{link_raw.lstrip('/')}"
            )
            return resolver_url_saliente_segura(url_abs)
        return ""

    def parsear_respuesta_api(self, payload: dict[str, Any] | list[Any]) -> list[OfertaLocal]:
        """
        Extrae entidades `OfertaLocal` reales desde el JSON oficial de `webapi.guatemaladigital.click/api/Busqueda`.
        """
        articulos: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            resp_list = payload.get("Response")
            if isinstance(resp_list, list) and resp_list:
                primero = resp_list[0]
                if isinstance(primero, dict) and isinstance(primero.get("Articulos"), list):
                    articulos = primero["Articulos"]
                else:
                    articulos = [x for x in resp_list if isinstance(x, dict)]
            elif isinstance(payload.get("Articulos"), list):
                articulos = payload["Articulos"]
        elif isinstance(payload, list):
            articulos = [x for x in payload if isinstance(x, dict)]

        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for item in articulos:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("Descripcion") or item.get("name") or item.get("title") or "").strip()
            precio = self._limpiar_precio(item.get("Precio") or item.get("price"))
            url_directa = self._construir_url_producto_directa(item)
            imagen_url = resolver_url_saliente_segura(
                str(item.get("Foto") or item.get("image") or "").strip()
            )

            if not titulo or precio is None or not es_url_producto_directa_valida(url_directa):
                continue
            if not imagen_url or not imagen_url.startswith("https://"):
                continue
            if url_directa in urls_vistas:
                continue
            urls_vistas.add(url_directa)

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url_directa,
                    imagen_url=imagen_url,
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def parsear_html(self, html: str) -> list[OfertaLocal]:
        """Extrae tarjetas de productos reales con URL directa desde HTML de Guatemala Digital."""
        if not html or not html.strip():
            return []
        soup = BeautifulSoup(html, "html.parser")
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for card in soup.select(
            ".bloque--busqueda--item-PB, .product-card, .product-item, .card-producto, article"
        ):
            enlace = card.select_one("a[href*='/Producto/'], a[href*='/ProductoP/'], a[href]")
            nodo_precio = card.select_one(
                ".Rectangle_8_PB, .price, .product-price, .precio, .amount"
            )
            if not enlace or not nodo_precio:
                continue
            titulo = (
                enlace.get_text(" ", strip=True)
                or str(enlace.get("title") or "").strip()
            )
            href = str(enlace.get("href") or "").strip()
            precio = self._limpiar_precio(nodo_precio.get_text(" ", strip=True))
            if not titulo or len(titulo) < 5 or not href or precio is None:
                continue
            url_abs = resolver_url_saliente_segura(
                href if href.startswith("http") else f"{self.BASE_URL}/{href.lstrip('/')}"
            )
            if not es_url_producto_directa_valida(url_abs) or url_abs in urls_vistas:
                continue

            img_el = card.select_one("img")
            img_url = (
                resolver_url_saliente_segura(
                    str(img_el.get("data-src") or img_el.get("src") or "").strip()
                )
                if img_el
                else ""
            )
            if not img_url.startswith("https://"):
                continue

            urls_vistas.add(url_abs)
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

    def _consultar_api_sync(self, termino: str) -> list[OfertaLocal]:
        q_enc = urllib.parse.quote(termino.strip())
        url = f"{self.API_BUSQUEDA_URL}?CadenaBusqueda={q_enc}&NumeroPagina=1&Traduccion={q_enc}"
        req = urllib.request.Request(url, headers=HEADERS_REALISTAS_GT)
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        return self.parsear_respuesta_api(payload)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado or self.simular:
            return []

        try:
            ofertas_api = await asyncio.to_thread(self._consultar_api_sync, termino)
        except Exception as exc:
            logger.debug(
                "Guatemala Digital API sin resultados (%s) para '%s'.",
                exc.__class__.__name__,
                termino,
            )
            return []

        relevantes = [
            o
            for o in ofertas_api
            if es_url_producto_directa_valida(o.url)
            and es_oferta_relevante(o.titulo, termino)
        ]
        logger.info(
            "Guatemala Digital ('%s'): %d ofertas reales extraídas.",
            termino,
            len(relevantes),
        )
        return relevantes
