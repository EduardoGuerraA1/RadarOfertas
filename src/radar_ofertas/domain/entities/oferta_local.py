"""
Entidad de dominio que representa una oferta encontrada en una tienda local.
No depende de ninguna capa externa (infraestructura, frameworks web, etc.)
"""
from pydantic import BaseModel, Field


class OfertaLocal(BaseModel):
    """Representa un producto/oferta capturado desde un scraper de tienda local."""

    tienda: str = Field(..., description="Nombre de la tienda de origen, ej. 'Kemik'")
    titulo: str = Field(..., description="Título/nombre del producto")
    precio_gtq: float = Field(..., ge=0, description="Precio en Quetzales (GTQ)")
    url: str = Field(..., description="URL directa al producto")
    imagen_url: str = Field(..., description="URL de la imagen del producto")

    class Config:
        frozen = True  # Inmutable: una oferta capturada no debería mutar