"""
Puerto (contrato) de repositorio en la capa de Dominio para persistir ofertas.
No conoce detalles de SQL, psycopg2 ni Neon DB.
"""
from abc import ABC, abstractmethod

from radar_ofertas.domain.entities.oferta_local import OfertaLocal


class OfertaRepository(ABC):
    """Contrato para almacenar ofertas capturadas por los scrapers."""

    @abstractmethod
    def guardar_ofertas(
        self, ofertas: list[OfertaLocal], categoria_slug: str = "tecnologia"
    ) -> int:
        """
        Registra o actualiza los productos en la tabla `productos` e inserta
        una instantánea en `historial_precios` por cada OfertaLocal.

        Args:
            ofertas: Lista de entidades OfertaLocal extraídas.
            categoria_slug: Slug de la categoría en base de datos (por defecto 'tecnologia').

        Returns:
            Cantidad de registros insertados en `historial_precios`.
        """
        raise NotImplementedError
