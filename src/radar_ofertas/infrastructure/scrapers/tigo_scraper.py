"""
Esqueleto de Scraper de Infraestructura para Tienda Tigo Guatemala (tienda.tigo.com.gt).
Prioridad #1 del Roadmap v5.0: Completa el duopolio de telefonía móvil junto a Tienda Claro GT
en el vertical de Smartphones (prepago, postpago y equipos liberados).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)


class TigoScraper(BaseScraper):
    """
    Scraper base para Tienda en Línea Tigo Guatemala (`https://tienda.tigo.com.gt`).
    Preparado para conectar con el catálogo de smartphones (iPhone, Samsung Galaxy,
    Xiaomi, Honor y Motorola) en planes prepago y renovación.
    """

    BASE_URL = "https://tienda.tigo.com.gt"
    NOMBRE_TIENDA = "Tienda Tigo"

    def __init__(self, timeout_s: int = 10, habilitado: bool = False) -> None:
        self.timeout_s = timeout_s
        self.habilitado = habilitado

    def parsear_respuesta_catalogo(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Transforma nodos de producto del catálogo de Tienda Tigo GT en entidades `OfertaLocal`.
        """
        items = payload.get("items", []) if isinstance(payload, dict) else []
        ofertas: list[OfertaLocal] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("name") or item.get("titulo") or "").strip()
            precio_raw = item.get("price") or item.get("precio_gtq")
            url = str(item.get("url") or "").strip()
            if not titulo or not precio_raw or not url:
                continue
            try:
                precio = Decimal(str(precio_raw)).quantize(Decimal("0.01"))
            except Exception:
                continue
            if precio <= 0:
                continue
            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url if url.startswith("http") else f"{self.BASE_URL}/{url.lstrip('/')}",
                    imagen_url=str(item.get("image") or item.get("imagen_url") or ""),
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        """
        Punto de entrada asíncrono para consultar smartphones en Tienda Tigo GT.
        """
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado:
            logger.debug(
                "TigoScraper (esqueleto fase siguiente) en espera para '%s'.", termino
            )
            return []
        return []
