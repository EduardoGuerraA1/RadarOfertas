"""
Entidad de dominio que representa una oferta encontrada en una tienda local.
No depende de ninguna capa externa (infraestructura, frameworks web, etc.)
Soporta tanto retail abierto como clubes de mayoreo por membresía (ej. PriceSmart GT).
"""
from pydantic import BaseModel, ConfigDict, Field


class OfertaLocal(BaseModel):
    """Representa un producto/oferta capturado desde un scraper de tienda local."""

    model_config = ConfigDict(frozen=True)

    tienda: str = Field(..., description="Nombre de la tienda de origen, ej. 'Kemik'")
    titulo: str = Field(..., description="Título/nombre del producto")
    precio_gtq: float = Field(..., ge=0, description="Precio en Quetzales (GTQ)")
    url: str = Field(..., description="URL directa al producto")
    imagen_url: str = Field(..., description="URL de la imagen del producto")
    requiere_membresia: bool = Field(
        default=False,
        description="True si la oferta pertenece a un club de mayoreo que exige membresía activa (ej. PriceSmart).",
    )
    estado_precio_membresia: str = Field(
        default="publico",
        description="Estado de visibilidad: 'publico', 'exclusivo_socios' o 'oculto_requiere_login'.",
    )