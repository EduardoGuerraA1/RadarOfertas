"""
Script Ejecutable de Precarga Inteligente y Auditoría de Tiendas (tecHunter GT v5.0).

Uso:
  - Ejecutar lote transversal rápido (ej. 1 producto por cada una de las 5 categorías):
      ./venv/bin/python worker_precarga.py --muestra-por-categoria 1
  - Ejecutar barrido completo de los 134 productos semilla de Guatemala:
      ./venv/bin/python worker_precarga.py
  - Mostrar únicamente el cruce de las 18 tiendas operativas y el Top 3 de prioridad:
      ./venv/bin/python worker_precarga.py --solo-matriz
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from radar_ofertas.application.use_cases.worker_precarga import (  # noqa: E402
    ESTADO_WORKER_PRECARGA,
    ejecutar_ciclo_precarga,
    iniciar_worker_periodico_background,
    precargar_termino_semilla,
    seleccionar_lote_semilla,
)
from radar_ofertas.domain.seed_data import (  # noqa: E402
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Worker en Segundo Plano de Precarga Inteligente (tecHunter GT v5.0)."
    )
    parser.add_argument(
        "--categoria",
        default="",
        help=(
            "Categoría específica de seed_list_guatemala a procesar "
            "(computo_y_laptops, smartphones, linea_blanca_y_hogar, "
            "herramientas_y_ferreteria, supermercado_y_mascotas)."
        ),
    )
    parser.add_argument(
        "--muestra-por-categoria",
        type=int,
        default=0,
        help="Cantidad de productos por categoría a procesar en este ciclo (0 = todos).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=0,
        help="Límite máximo total de productos a procesar en esta corrida (0 = sin límite).",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.5,
        help="Segundos de pausa entre cada producto semilla (por defecto: 0.5s).",
    )
    parser.add_argument(
        "--sin-db",
        action="store_true",
        help="Ejecuta el worker sin escribir en Neon DB (modo simulación/diagnóstico).",
    )
    parser.add_argument(
        "--solo-matriz",
        action="store_true",
        help="Imprime el cruce de las 18 tiendas operativas y las siguientes 3 tiendas prioritarias.",
    )
    return parser.parse_args()


def imprimir_reporte_matriz() -> None:
    reporte = cruzar_matriz_tiendas_y_prioridades()
    todos_seed = obtener_todos_los_productos_semilla()
    print("\n" + "=" * 105)
    print(" MATRIZ E-COMMERCE GUATEMALA Y SEMILLAS DE ALTA DEMANDA — TECHUNTER GT v5.0")
    print("=" * 105)
    print(
        f" • Productos en `seed_list_guatemala` : {len(todos_seed)} productos en {len(seed_list_guatemala)} verticales"
    )
    print(
        f" • Tiendas Operativas en tecHunter GT : {reporte['total_operativas_sistema']} tiendas activas"
    )
    print(
        f" • Tiendas Cruzadas en Matriz Nacional: {len(reporte['operativas_cruzadas'])} operativas | "
        f"{len(reporte['pendientes_ordenadas'])} pendientes en backlog"
    )
    print("-" * 105)
    print(" 🎯 TOP 3 SIGUIENTES TIENDAS DE ALTA PRIORIDAD PARA PRÓXIMOS SCRAPERS:")
    for idx, tienda in enumerate(reporte["siguientes_3_alta_prioridad"], 1):
        verticales_str = ", ".join(tienda["verticales"])
        print(
            f"   [{idx}] {tienda['nombre']} ({tienda['url']}) | Verticales: [{verticales_str}]"
        )
        print(f"       ↳ {tienda['justificacion']}")
    print("=" * 105 + "\n")


async def main_async() -> None:
    args = parse_args()
    imprimir_reporte_matriz()
    if args.solo_matriz:
        return

    resumen = await ejecutar_ciclo_precarga(
        categoria_filtro=args.categoria,
        muestra_por_categoria=args.muestra_por_categoria,
        limite_total=args.limite,
        pausa_entre_productos_s=args.pausa,
        persistir_en_db=not args.sin_db,
    )
    print("\n" + "=" * 105)
    print(" ✅ CICLO DE WORKER DE PRECARGA COMPLETADO (REGLA ESTRICTA NEON DB)")
    print(f" • Productos semilla barridos          : {resumen['productos_procesados']}")
    print(f" • Ofertas principales relevantes      : {resumen['ofertas_relevantes_evaluadas']}")
    print(
        f" • Nuevos cambios de precio insertados : {resumen['nuevos_precios_insertados']} "
        "(sin duplicar precios idénticos en `historial_precios`)"
    )
    print("=" * 105 + "\n")


if __name__ == "__main__":
    asyncio.run(main_async())

__all__ = [
    "ESTADO_WORKER_PRECARGA",
    "ejecutar_ciclo_precarga",
    "iniciar_worker_periodico_background",
    "precargar_termino_semilla",
    "seleccionar_lote_semilla",
]
