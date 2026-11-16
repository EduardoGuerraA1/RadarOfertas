"""
Esqueleto de Scraper de Infraestructura para Almacenes Tropigas Guatemala (almacenestropigas.com/guatemala).
Prioridad #3 del Roadmap v5.0: Cadena hermana del Grupo Unicomer (La Curacao) con fuerte
presencia en línea blanca (refrigeradoras Mabe/LG, estufas de 20\" y 30\", lavadoras),
pantallas y smartphones.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)


class TropigasScraper(BaseScraper):
    """
    Scraper base para Almacenes Tropigas Guatemala (`https://www.almacenestropigas.com/guatemala`).
    Preparado para consultar Magento 2 / Adobe Commerce LiveSearch del Grupo Unicomer.
    """

    BASE_URL = "https://www.almacenestropigas.com/guatemala"
    NOMBRE_TIENDA = "Tropigas"

    def __init__(self, timeout_s: int = 10, habilitado: bool = False) -> None:
        self.timeout_s = timeout_s
        self.habilitado = habilitado

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
            if not titulo or precio_raw is None or not url:
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
                    imagen_url=str(item.get("image") or ""),
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        """
        Punto de entrada asíncrono para consultar línea blanca y hogar en Tropigas GT.
        """
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado:
            logger.debug(
                "TropigasScraper (esqueleto fase siguiente) en espera para '%s'.",
                termino,
            )
            return []
        return []
