"""
Esqueleto de Scraper de Infraestructura para Office Depot Guatemala (officedepot.com.gt).
Prioridad #2 del Roadmap v5.0: Líder en cómputo corporativo, laptops de productividad,
monitores, impresoras (Epson EcoTank / HP Smart Tank / Canon Pixma) y mobiliario de oficina.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)


class OfficeDepotScraper(BaseScraper):
    """
    Scraper base para Office Depot Guatemala (`https://www.officedepot.com.gt`).
    Diseñado para integrarse con la arquitectura SAP Hybris / OCC de Office Depot
    (`/officedepotGuatemala/es/search/?text=...`).
    """

    BASE_URL = "https://www.officedepot.com.gt"
    NOMBRE_TIENDA = "Office Depot"

    def __init__(self, timeout_s: int = 10, habilitado: bool = False) -> None:
        self.timeout_s = timeout_s
        self.habilitado = habilitado

    def parsear_respuesta_hybris(self, payload: dict[str, Any]) -> list[OfertaLocal]:
        """
        Transforma productos del JSON/HTML de SAP Hybris de Office Depot GT en `OfertaLocal`.
        """
        productos = payload.get("products", []) if isinstance(payload, dict) else []
        ofertas: list[OfertaLocal] = []
        for prod in productos:
            if not isinstance(prod, dict):
                continue
            titulo = str(prod.get("name") or "").strip()
            precio_info = prod.get("price") or {}
            precio_raw = (
                precio_info.get("value")
                if isinstance(precio_info, dict)
                else precio_info
            )
            url = str(prod.get("url") or "").strip()
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
                    imagen_url=str(prod.get("image") or ""),
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        """
        Punto de entrada asíncrono para consultar cómputo y oficina en Office Depot GT.
        """
        termino = (termino_busqueda or "").strip()
        if not termino or not self.habilitado:
            logger.debug(
                "OfficeDepotScraper (esqueleto fase siguiente) en espera para '%s'.",
                termino,
            )
            return []
        return []
