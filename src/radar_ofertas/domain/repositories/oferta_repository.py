"""
Puerto (contrato) de repositorio en la capa de Dominio para persistir y consultar ofertas.
No conoce detalles de SQL, psycopg2 ni Neon DB.
"""
from abc import ABC, abstractmethod
from typing import Any

from radar_ofertas.domain.entities.oferta_local import OfertaLocal


class OfertaRepository(ABC):
    """Contrato para almacenar y consultar ofertas capturadas por los scrapers."""

    @abstractmethod
    def guardar_ofertas(
        self, ofertas: list[OfertaLocal], categoria_slug: str = "tecnologia"
    ) -> int:
        """
        Registra o actualiza los productos en la tabla `productos` e inserta
        una instantánea en `historial_precios` por cada OfertaLocal.
        """
        raise NotImplementedError

    @abstractmethod
    def buscar_ofertas_comparadas(
        self, query: str = "", tienda_slug: str = ""
    ) -> list[dict[str, Any]]:
        """
        Consulta las ofertas más recientes en la base de datos filtrando por término
        de búsqueda y tienda opcional, ordenadas de menor a mayor precio en Quetzales.
        """
        raise NotImplementedError
