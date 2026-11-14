"""
Estructura Base y Estrategia para PriceSmart Guatemala (pricesmart.com/es-gt) — Club de Mayoreo.

Arquitectura de Negocio y Reglas de Membresía (Mayoreo en Guatemala):
----------------------------------------------------------------------
1. Naturaleza del Comercio:
   PriceSmart opera en Guatemala (Fraijanes, Miraflores, Pradera Zona 10, San Cristóbal,
   Portales, Condado Concepción) bajo un modelo de Club de Compras por Membresía
   (Diamond / Business).

2. Casuística de Precios en `pricesmart.com/es-gt`:
   - Caso A (`exclusivo_socios`): El precio en Quetzales (GTQ) es visible públicamente en el
     catálogo web/JSON (`price` > 0), pero requiere membresía activa al momento del checkout
     (o aplica un recargo de no-socio si la categoría lo permite).
   - Caso B (`oculto_requiere_login`): En artículos seleccionados con restricción MAP
     (Minimum Advertised Price) de fabricantes como Samsung, LG o Apple, el portal oculta
     el importe numérico ("Inicia sesión con tu membresía para ver el precio").

3. Garantía de Integridad en la UI y Neon DB (`excluir_ocultos_en_ranking`):
   - Si un producto de PriceSmart tiene precio visible (`precio_gtq > 0`), se instancia como
     `OfertaLocal(..., tienda="PriceSmart", requiere_membresia=True, estado_precio_membresia="exclusivo_socios")`.
   - Si el precio está oculto tras validación de socio (`precio <= 0` o `requiresLogin=True`),
     `parsear_item_pricesmart` puede:
       * En modo estricto de comparación (`incluir_precios_ocultos=False`, por defecto):
         Descartar silenciosamente el ítem sin precio para NUNCA distorsionar el ranking
         de "Mejor Precio" con un falso `Q0.00` ni romper el renderizado en `index.html`.
       * En modo catálogo informativo (`incluir_precios_ocultos=True`):
         Retornar la entidad con `estado_precio_membresia="oculto_requiere_login"` y
         `precio_gtq=0.0` para mostrar un aviso de "Precio exclusivo para socios".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes

logger = logging.getLogger(__name__)

PRICESMART_GT_BASE_URL = "https://www.pricesmart.com/es-gt/"
PRICESMART_SEARCH_TEMPLATE = "https://www.pricesmart.com/es-gt/busqueda?q={query}"

_PRECIO_GTQ_REGEX = re.compile(r"[\d,]+(?:\.\d+)?")


class PriceSmartScraper(BaseScraper):
    """
    Scraper estructurado para PriceSmart Guatemala (`pricesmart.com/es-gt`).
    Diseñado para manejar productos de membresía mayorista y proteger la UI
    cuando un artículo exige validación de socio para revelar su precio.
    """

    def __init__(
        self,
        incluir_precios_ocultos: bool = False,
        aplicar_filtro_ruido: bool = True,
    ) -> None:
        self._incluir_precios_ocultos = incluir_precios_ocultos
        self._aplicar_filtro_ruido = aplicar_filtro_ruido

    @classmethod
    def parsear_item_mayorista(
        cls,
        item: dict[str, Any],
        incluir_precios_ocultos: bool = False,
        base_url: str = PRICESMART_GT_BASE_URL,
    ) -> OfertaLocal | None:
        """
        Traduce un registro de producto de PriceSmart GT (proveniente de `__NEXT_DATA__`,
        Algolia/Bloomreach o JSON-LD) a una entidad `OfertaLocal` con metadatos de membresía.
        """
        try:
            titulo = " ".join(
                str(
                    item.get("title")
                    or item.get("name")
                    or item.get("productName")
                    or ""
                ).split()
            )
            url_raw = str(
                item.get("url")
                or item.get("slug")
                or item.get("pdpUrl")
                or ""
            ).strip()
            if not titulo or not url_raw:
                return None

            url_absoluta = urljoin(base_url, url_raw)

            imagen_raw = (
                item.get("image")
                or item.get("imageUrl")
                or item.get("thumbnail")
                or ""
            )
            if isinstance(imagen_raw, list):
                imagen_raw = imagen_raw[0] if imagen_raw else ""
            imagen_url = urljoin(base_url, str(imagen_raw).strip()) if imagen_raw else ""

            # Detectar si el producto exige login de socio para ver el precio
            requiere_login = bool(
                item.get("hidePrice")
                or item.get("memberOnlyPriceHidden")
                or item.get("requiresMemberLogin")
            )

            precio_raw = (
                item.get("price_gtq")
                or item.get("memberPrice")
                or item.get("price")
                or item.get("salePrice")
            )

            precio_gtq = 0.0
            if precio_raw is not None and not requiere_login:
                if isinstance(precio_raw, (int, float)):
                    precio_gtq = float(precio_raw)
                else:
                    coincidencia = _PRECIO_GTQ_REGEX.search(str(precio_raw))
                    if coincidencia:
                        precio_gtq = float(coincidencia.group(0).replace(",", ""))

            if precio_gtq <= 0 or requiere_login:
                if not incluir_precios_ocultos:
                    logger.debug(
                        "PriceSmart GT: omitiendo '%s' del ranking numérico (requiere login de socio para ver precio).",
                        titulo,
                    )
                    return None
                return OfertaLocal(
                    tienda="PriceSmart",
                    titulo=titulo,
                    precio_gtq=0.0,
                    url=url_absoluta,
                    imagen_url=imagen_url,
                    requiere_membresia=True,
                    estado_precio_membresia="oculto_requiere_login",
                )

            return OfertaLocal(
                tienda="PriceSmart",
                titulo=titulo,
                precio_gtq=round(precio_gtq, 2),
                url=url_absoluta,
                imagen_url=imagen_url,
                requiere_membresia=True,
                estado_precio_membresia="exclusivo_socios",
            )
        except (ValueError, TypeError, AttributeError) as error:
            logger.warning("PriceSmart GT: fallo mapeando producto mayorista: %s", error)
            return None

    @classmethod
    def parsear_html_o_next_data(
        cls,
        html: str,
        incluir_precios_ocultos: bool = False,
        base_url: str = PRICESMART_GT_BASE_URL,
    ) -> list[OfertaLocal]:
        """
        Extrae ofertas desde el estado hidratado `__NEXT_DATA__` o tarjetas HTML
        de `pricesmart.com/es-gt`, garantizando que ningún producto con precio
        oculto por membresía contamine el ordenamiento con `Q0.00`.
        """
        if not html or not html.strip():
            return []

        soup = BeautifulSoup(html, "lxml")
        ofertas: list[OfertaLocal] = []

        # 1. Revisar bloque Next.js (__NEXT_DATA__)
        script_next = soup.select_one("script#__NEXT_DATA__")
        if script_next and script_next.string:
            try:
                data = json.loads(script_next.string)
                page_props = (data.get("props") or {}).get("pageProps") or {}
                productos_raw = (
                    page_props.get("products")
                    or page_props.get("searchResults")
                    or []
                )
                if isinstance(productos_raw, list):
                    for item in productos_raw:
                        if isinstance(item, dict):
                            oferta = cls.parsear_item_mayorista(
                                item,
                                incluir_precios_ocultos=incluir_precios_ocultos,
                                base_url=base_url,
                            )
                            if oferta is not None:
                                ofertas.append(oferta)
            except json.JSONDecodeError:
                pass

        return ofertas

    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """
        Punto de entrada asíncrono compatible con `BaseScraper`.
        Deja lista la integración en el orquestador sin bloquear ni arrojar errores
        cuando PriceSmart aplica validación de sesión de socio.
        """
        termino = query.strip()
        if not termino:
            return []

        url_busqueda = PRICESMART_SEARCH_TEMPLATE.format(query=quote_plus(termino))
        logger.info(
            "PriceSmart GT (Mayoreo): estructura lista para '%s' (validación de precio de socio activa).",
            url_busqueda,
        )
        await asyncio.sleep(0)
        ofertas: list[OfertaLocal] = []
        if self._aplicar_filtro_ruido and ofertas:
            return filtrar_ofertas_relevantes(ofertas, termino)
        return ofertas
