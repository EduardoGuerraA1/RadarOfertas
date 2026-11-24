"""
Implementación concreta de BaseScraper para Tecno Fácil Guatemala (tecnofacil.com.gt).
Distinto a Tiendas Max: enfocado en cuotas accesibles, electrodomésticos, línea blanca,
smartphones liberados y tecnología para el hogar en Guatemala.

Arquitectura técnica de Tecno Fácil (`https://www.tecnofacil.com.gt`):
  - Plataforma: Magento 2 / Adobe Commerce (`catalogsearch/result/?q={query}` y `/graphql`).
  - Soporta extracción directa de precios de contado y promociones vigentes en Quetzales (GTQ),
    además de un catálogo verificado de respaldo de Tecno Fácil Guatemala para garantizar
    resultados cuando Cloudflare bloquea IPs de servidores en la nube (Render).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote_plus, urljoin

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_url_producto_directa_valida,
    filtrar_ofertas_relevantes,
)
from radar_ofertas.infrastructure.scrapers.max_scraper import MaxScraper

logger = logging.getLogger(__name__)

TECNOFACIL_BASE_URL = "https://www.tecnofacil.com.gt/"
TECNOFACIL_SEARCH_URL_TEMPLATE = (
    "https://www.tecnofacil.com.gt/catalogsearch/result/?q={query}"
)


class TecnoFacilScraper(BaseScraper):
    """
    Scraper independiente para Tecno Fácil Guatemala (`tecnofacil.com.gt`),
    especializado en electrodomésticos, línea blanca, celulares y planes en cuotas.
    Tolerancia cero a datos sintéticos (v5.5): solo devuelve productos extraídos en vivo.
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_s: int = 10,
        usar_playwright_fallback: bool = False,
        usar_catalogo_respaldo: bool = False,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._delegate = MaxScraper(
            headless=headless,
            timeout_s=timeout_s,
            usar_playwright_fallback=usar_playwright_fallback,
            nombre_tienda="Tecno Fácil",
            base_url=TECNOFACIL_BASE_URL,
        )
        self._usar_catalogo_respaldo = False
        self._aplicar_filtro_ruido = aplicar_filtro_ruido

    @classmethod
    def parsear_respuesta_graphql(
        cls,
        raw_data: str | dict[str, Any],
        base_url: str = TECNOFACIL_BASE_URL,
    ) -> list[OfertaLocal]:
        """Traduce una respuesta GraphQL de Tecno Fácil a entidades `OfertaLocal`."""
        return MaxScraper.parsear_respuesta_graphql(
            raw_data, tienda="Tecno Fácil", base_url=base_url
        )

    @classmethod
    def parsear_html_busqueda(
        cls,
        html: str,
        base_url: str = TECNOFACIL_BASE_URL,
    ) -> list[OfertaLocal]:
        """Extrae ofertas desde el HTML de Tecno Fácil (`tecnofacil.com.gt`)."""
        return MaxScraper.parsear_html_busqueda(
            html, tienda="Tecno Fácil", base_url=base_url
        )

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """Busca `query` en Tecno Fácil Guatemala y retorna únicamente ofertas reales en Quetzales (o [] si falla)."""
        termino = (query or "").strip()
        if not termino:
            return []

        url_busqueda = TECNOFACIL_SEARCH_URL_TEMPLATE.format(query=quote_plus(termino))
        logger.info("Tecno Fácil GT: consultando '%s'...", url_busqueda)

        ofertas = await self._delegate.buscar_producto(termino)
        ofertas = [
            o for o in ofertas
            if es_url_producto_directa_valida(o.url)
        ]

        if self._aplicar_filtro_ruido and ofertas:
            ofertas = filtrar_ofertas_relevantes(ofertas, termino)

        return ofertas
