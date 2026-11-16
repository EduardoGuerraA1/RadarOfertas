"""
Punto de acceso en raíz para `seed_data.py` (tecHunter GT v5.0).
Reexporta `seed_list_guatemala`, `tiendas_ecommerce_guatemala`,
`TIENDAS_OPERATIVAS_TECHUNTER`, `obtener_todos_los_productos_semilla`
y `cruzar_matriz_tiendas_y_prioridades`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from radar_ofertas.domain.seed_data import (  # noqa: E402,F401
    MAPEO_CATEGORIA_SEED_A_DB,
    TIENDAS_OPERATIVAS_TECHUNTER,
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
    tiendas_ecommerce_guatemala,
)

__all__ = [
    "seed_list_guatemala",
    "tiendas_ecommerce_guatemala",
    "TIENDAS_OPERATIVAS_TECHUNTER",
    "MAPEO_CATEGORIA_SEED_A_DB",
    "obtener_todos_los_productos_semilla",
    "cruzar_matriz_tiendas_y_prioridades",
]
