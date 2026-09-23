"""
Contrato (puerto) que toda implementación de scraper debe cumplir.
La capa de aplicación no sabe NADA de httpx, BeautifulSoup, etc.
"""
from abc import ABC, abstractmethod

from radar_ofertas.domain.entities.oferta_local import OfertaLocal


class BaseScraper(ABC):
    """Clase base abstracta para todos los scrapers de tiendas locales."""

    @abstractmethod
    async def buscar_producto(self, query: str) -> list[OfertaLocal]:
        """
        Busca un producto en la tienda correspondiente.

        Args:
            query: Término de búsqueda (ej. "laptop hp").

        Returns:
            Lista de OfertaLocal encontradas. Lista vacía si no hay resultados
            o si ocurrió un error controlado durante el scraping.
        """
        raise NotImplementedError