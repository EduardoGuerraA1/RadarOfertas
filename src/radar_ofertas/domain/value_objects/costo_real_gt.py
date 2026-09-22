"""Costo real puesto en Guatemala (Amazon / courier PO Box).

Fórmula:
    CIF  = (precio_usd + peso_libras * tarifa_lb_usd) * tipo_cambio
    DAI  = CIF * dai_porcentaje
    IVA  = (CIF + DAI) * 0.12
    total = CIF + DAI + IVA
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

IVA_PORCENTAJE = Decimal("0.12")
_CENTAVO = Decimal("0.01")


def _a_decimal(valor: float | int | Decimal) -> Decimal:
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def _gtq(valor: Decimal) -> Decimal:
    """Redondeo bancario a 2 decimales (centavos GTQ)."""
    return valor.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


class CostoRealGT(BaseModel):
    """Value Object inmutable del landed cost en quetzales."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    precio_usd: float = Field(..., ge=0, description="Precio FOB / listado en USD.")
    peso_libras: float = Field(..., description="Peso volumétrico o real en libras.")
    tarifa_lb_usd: float = Field(default=4.0, ge=0, description="Tarifa courier USD/lb.")
    dai_porcentaje: float = Field(
        ...,
        ge=0,
        le=0.15,
        description="DAI como fracción (0.05 = 5%). Máximo 15%.",
    )
    tipo_cambio: float = Field(..., gt=0, description="USD → GTQ.")

    @field_validator("peso_libras")
    @classmethod
    def _peso_positivo(cls, valor: float) -> float:
        if valor <= 0:
            raise ValueError("peso_libras debe ser mayor que 0")
        return valor

    @property
    def _cif_crudo(self) -> Decimal:
        flete = _a_decimal(self.peso_libras) * _a_decimal(self.tarifa_lb_usd)
        return (_a_decimal(self.precio_usd) + flete) * _a_decimal(self.tipo_cambio)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cif_gtq(self) -> Decimal:
        """CIF en GTQ: mercancía + flete courier, convertidos."""
        return _gtq(self._cif_crudo)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def dai_gtq(self) -> Decimal:
        """DAI arancelario sobre el CIF."""
        return _gtq(self._cif_crudo * _a_decimal(self.dai_porcentaje))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def iva_gtq(self) -> Decimal:
        """IVA 12% sobre (CIF + DAI) sin redondear componentes intermedios."""
        cif = self._cif_crudo
        dai = cif * _a_decimal(self.dai_porcentaje)
        return _gtq((cif + dai) * IVA_PORCENTAJE)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def costo_total_gtq(self) -> Decimal:
        """Landed cost: CIF + DAI + IVA (suma de partidas ya redondeadas)."""
        return self.cif_gtq + self.dai_gtq + self.iva_gtq
