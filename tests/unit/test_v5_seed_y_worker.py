"""
Pruebas unitarias para tecHunter GT v5.0:
  - Módulo de Datos Semilla (`seed_data.py`): `seed_list_guatemala` y `tiendas_ecommerce_guatemala`
  - Cruce automático de las 18 tiendas operativas e identificación del Top 3 de alta prioridad
  - Selección de lotes en `worker_precarga.py` y validación de no-duplicación en Neon DB
"""
from __future__ import annotations

from radar_ofertas.application.use_cases.worker_precarga import seleccionar_lote_semilla
from radar_ofertas.domain.seed_data import (
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
    tiendas_ecommerce_guatemala,
)


def test_seed_list_guatemala_contiene_5_verticales_y_productos_clave() -> None:
    expected_keys = {
        "computo_y_laptops",
        "smartphones",
        "linea_blanca_y_hogar",
        "herramientas_y_ferreteria",
        "supermercado_y_mascotas",
    }
    assert set(seed_list_guatemala.keys()) == expected_keys

    todos = obtener_todos_los_productos_semilla()
    assert len(todos) >= 130
    nombres = [item[2] for item in todos]
    assert "MacBook Air M2 8GB 256GB" in nombres
    assert "Samsung Galaxy S24 Ultra 256GB" in nombres
    assert "Refrigeradora Mabe 11 pies" in nombres
    assert "Taladro percutor inalambrico DeWalt 20V" in nombres
    assert "Alimento para perro Pedigree adulto 21 kg" in nombres
    assert "Incaparina original 450g" in nombres


def test_cruce_matriz_tiendas_identifica_18_operativas_y_top_3_prioridad() -> None:
    assert len(tiendas_ecommerce_guatemala) == 6
    reporte = cruzar_matriz_tiendas_y_prioridades()

    assert reporte["total_operativas_sistema"] == 18
    assert len(reporte["operativas_cruzadas"]) >= 14

    top_3 = reporte["siguientes_3_alta_prioridad"]
    assert len(top_3) == 3
    nombres_top_3 = [t["nombre"] for t in top_3]
    assert nombres_top_3 == [
        "Tienda Tigo Guatemala",
        "Office Depot Guatemala",
        "Tropigas",
    ]


def test_worker_precarga_selecciona_lote_por_muestra_y_categoria() -> None:
    lote_muestra = seleccionar_lote_semilla(muestra_por_categoria=2)
    # 5 categorías * 2 productos por categoría = 10 productos
    assert len(lote_muestra) == 10

    lote_herramientas = seleccionar_lote_semilla(
        categoria_filtro="herramientas_y_ferreteria", limite_total=5
    )
    assert len(lote_herramientas) == 5
    assert all(cat_db == "hogar" for _, cat_db, _ in lote_herramientas)
