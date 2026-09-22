"""Pruebas unitarias del Value Object CostoRealGT."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from radar_ofertas.domain.value_objects.costo_real_gt import CostoRealGT


def _vo(**overrides: float) -> CostoRealGT:
    datos: dict[str, float] = {
        "precio_usd": 100.0,
        "peso_libras": 2.0,
        "tarifa_lb_usd": 4.0,
        "dai_porcentaje": 0.0,
        "tipo_cambio": 7.80,
    }
    datos.update(overrides)
    return CostoRealGT(**datos)


def test_producto_sin_dai() -> None:
    """DAI 0%: CIF=(100+8)*7.80=842.40; IVA=101.09; total=943.49."""
    costo = _vo(dai_porcentaje=0.0)

    assert costo.cif_gtq == Decimal("842.40")
    assert costo.dai_gtq == Decimal("0.00")
    assert costo.iva_gtq == Decimal("101.09")
    assert costo.costo_total_gtq == Decimal("943.49")


def test_producto_tecnologia_dai_5_porciento() -> None:
    """Tecnología 5%: DAI=42.12; IVA sobre CIF+DAI=106.14; total=990.66."""
    costo = _vo(dai_porcentaje=0.05)

    assert costo.cif_gtq == Decimal("842.40")
    assert costo.dai_gtq == Decimal("42.12")
    assert costo.iva_gtq == Decimal("106.14")
    assert costo.costo_total_gtq == Decimal("990.66")


def test_peso_negativo_lanza_validacion() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _vo(peso_libras=-1.0)

    assert "peso_libras" in str(exc_info.value)
