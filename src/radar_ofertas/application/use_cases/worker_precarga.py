"""
Caso de Uso / Background Worker de Precarga Inteligente (tecHunter GT v5.0).

Barre de forma automática, silenciosa y resiliente los productos de `seed_list_guatemala`
en las 18 tiendas activas de Guatemala, aplicando el Motor de Precisión de Modelos
y persistiendo en Neon DB bajo la regla estricta de ahorro de almacenamiento:
  - `PostgresOfertaRepository.guardar_ofertas` valida mediante `_obtener_ultimo_precio_registrado`
    que SOLO se inserte un registro en `historial_precios` cuando el precio realmente varió.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Any

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.seed_data import (
    MAPEO_CATEGORIA_SEED_A_DB,
    cruzar_matriz_tiendas_y_prioridades,
    seed_list_guatemala,
)
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.cemaco_scraper import CemacoScraper
from radar_ofertas.infrastructure.scrapers.claro_scraper import ClaroScraper
from radar_ofertas.infrastructure.scrapers.epa_scraper import EpaScraper
from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
from radar_ofertas.infrastructure.scrapers.istore_scraper import IStoreScraper
from radar_ofertas.infrastructure.scrapers.lacuracao_scraper import LaCuracaoScraper
from radar_ofertas.infrastructure.scrapers.max_scraper import MaxScraper
from radar_ofertas.infrastructure.scrapers.novex_scraper import NovexScraper
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
from radar_ofertas.infrastructure.scrapers.pricesmart_scraper import PriceSmartScraper
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper
from radar_ofertas.infrastructure.scrapers.tecnofacil_scraper import TecnoFacilScraper
from radar_ofertas.infrastructure.scrapers.tiendas_oficiales_scraper import (
    TiendasOficialesScraper,
)
from radar_ofertas.infrastructure.scrapers.walmart_scraper import WalmartScraper

logger = logging.getLogger("tecHunter.worker_precarga")

ESTADO_WORKER_PRECARGA: dict[str, Any] = {
    "activo": False,
    "ultimo_ciclo_inicio": None,
    "ultimo_ciclo_fin": None,
    "termino_actual": None,
    "productos_procesados_ciclo": 0,
    "ofertas_evaluadas_ciclo": 0,
    "nuevos_precios_insertados_ciclo": 0,
    "ciclos_completados": 0,
}


async def _ejecutar_scraper_con_timeout(
    scraper: Any, nombre: str, termino: str, timeout_s: float = 10.0
) -> list[OfertaLocal]:
    try:
        res = await asyncio.wait_for(scraper.buscar_producto(termino), timeout=timeout_s)
        return list(res or [])
    except Exception as exc:
        logger.debug("Worker precarga (%s) omitido en '%s': %s", nombre, termino, exc)
        return []


def seleccionar_lote_semilla(
    categoria_filtro: str = "",
    muestra_por_categoria: int = 0,
    limite_total: int = 0,
) -> list[tuple[str, str, str]]:
    """
    Construye la cola de ejecución `(categoria_seed, categoria_db, termino)` desde `seed_list_guatemala`.
    - Si `muestra_por_categoria > 0`, selecciona los primeros N productos de cada categoría
      para lograr cobertura transversal rápida en las 5 categorías.
    """
    cola: list[tuple[str, str, str]] = []
    cat_filtro_limpio = categoria_filtro.strip().lower()

    for cat_seed, lista_terminos in seed_list_guatemala.items():
        if cat_filtro_limpio and cat_seed.lower() != cat_filtro_limpio:
            continue
        cat_db = MAPEO_CATEGORIA_SEED_A_DB.get(cat_seed, "tecnologia")
        seleccionados = (
            lista_terminos[:muestra_por_categoria]
            if muestra_por_categoria > 0
            else lista_terminos
        )
        for termino in seleccionados:
            cola.append((cat_seed, cat_db, termino))

    if limite_total > 0:
        return cola[:limite_total]
    return cola


async def precargar_termino_semilla(
    termino: str,
    categoria_db: str = "tecnologia",
    repositorio: PostgresOfertaRepository | None = None,
    persistir_en_db: bool = True,
    timeout_scraper_s: float = 10.0,
) -> dict[str, Any]:
    """
    Ejecuta en paralelo los scrapers ligeros/cloud-safe para un término de `seed_list_guatemala`,
    filtra con el Motor de Precisión y guarda únicamente cambios reales de precio en Neon DB.
    """
    scrapers: list[tuple[str, Any]] = [
        ("iStore", IStoreScraper(timeout_s=int(timeout_scraper_s))),
        ("EPA", EpaScraper(timeout_s=int(timeout_scraper_s))),
        ("Novex", NovexScraper(timeout_s=int(timeout_scraper_s))),
        ("Intelaf", IntelafScraper(headless=True, timeout_s=int(timeout_scraper_s))),
        (
            "Tecno Fácil",
            TecnoFacilScraper(
                headless=True,
                timeout_s=int(timeout_scraper_s),
                usar_playwright_fallback=False,
            ),
        ),
        ("La Curacao", LaCuracaoScraper(timeout_s=int(timeout_scraper_s))),
        ("Tienda Claro", ClaroScraper(timeout_s=int(timeout_scraper_s))),
        ("PriceSmart", PriceSmartScraper(timeout_s=int(timeout_scraper_s))),
        ("Oficiales", TiendasOficialesScraper(timeout_s=int(timeout_scraper_s))),
        ("Walmart Grupo", WalmartScraper(timeout_s=int(timeout_scraper_s))),
        ("Cemaco", CemacoScraper(timeout_s=int(timeout_scraper_s))),
        ("Pacifiko", PacifikoScraper()),
        ("La Torre", SuperScraper()),
        (
            "Tiendas Max",
            MaxScraper(
                headless=True,
                timeout_s=int(timeout_scraper_s),
                usar_playwright_fallback=False,
            ),
        ),
    ]

    listas = await asyncio.gather(
        *[
            _ejecutar_scraper_con_timeout(
                instancia, nombre, termino, timeout_s=timeout_scraper_s
            )
            for nombre, instancia in scrapers
        ]
    )

    brutas: list[OfertaLocal] = [oferta for sublista in listas for oferta in sublista]
    relevantes: list[OfertaLocal] = [
        o
        for o in filtrar_ofertas_relevantes(brutas, termino)
        if o.precio_gtq > 0 and o.estado_precio_membresia != "oculto_requiere_login"
    ]

    insertados = 0
    if persistir_en_db and relevantes:
        repo = repositorio or PostgresOfertaRepository()
        insertados = await asyncio.to_thread(
            repo.guardar_ofertas, relevantes, categoria_db
        )

    return {
        "termino": termino,
        "categoria_db": categoria_db,
        "brutas": len(brutas),
        "relevantes": len(relevantes),
        "insertados_neon": insertados,
    }


async def ejecutar_ciclo_precarga(
    categoria_filtro: str = "",
    muestra_por_categoria: int = 0,
    limite_total: int = 0,
    pausa_entre_productos_s: float = 0.8,
    persistir_en_db: bool = True,
) -> dict[str, Any]:
    """
    Ejecuta un barrido completo o por lote sobre `seed_list_guatemala`.
    """
    cola = seleccionar_lote_semilla(
        categoria_filtro=categoria_filtro,
        muestra_por_categoria=muestra_por_categoria,
        limite_total=limite_total,
    )

    ESTADO_WORKER_PRECARGA["activo"] = True
    ESTADO_WORKER_PRECARGA["ultimo_ciclo_inicio"] = dt.datetime.now(
        dt.timezone.utc
    ).isoformat()
    ESTADO_WORKER_PRECARGA["productos_procesados_ciclo"] = 0
    ESTADO_WORKER_PRECARGA["ofertas_evaluadas_ciclo"] = 0
    ESTADO_WORKER_PRECARGA["nuevos_precios_insertados_ciclo"] = 0

    repositorio: PostgresOfertaRepository | None = None
    if persistir_en_db and (os.getenv("DATABASE_URL") or "").strip():
        repositorio = PostgresOfertaRepository()

    total_evaluadas = 0
    total_insertados = 0
    detalles: list[dict[str, Any]] = []

    logger.info(
        "Iniciando ciclo de precarga inteligente tecHunter v5.0 (%d términos semilla en cola)...",
        len(cola),
    )

    try:
        for idx, (cat_seed, cat_db, termino) in enumerate(cola, 1):
            ESTADO_WORKER_PRECARGA["termino_actual"] = termino
            try:
                res = await precargar_termino_semilla(
                    termino=termino,
                    categoria_db=cat_db,
                    repositorio=repositorio,
                    persistir_en_db=bool(repositorio is not None and persistir_en_db),
                )
                total_evaluadas += res["relevantes"]
                total_insertados += res["insertados_neon"]
                detalles.append(res)

                ESTADO_WORKER_PRECARGA["productos_procesados_ciclo"] = idx
                ESTADO_WORKER_PRECARGA["ofertas_evaluadas_ciclo"] = total_evaluadas
                ESTADO_WORKER_PRECARGA["nuevos_precios_insertados_ciclo"] = (
                    total_insertados
                )

                logger.info(
                    "[%d/%d] Seed '%s' (%s) -> %d relevantes | %d variaciones insertadas en Neon DB.",
                    idx,
                    len(cola),
                    termino,
                    cat_seed,
                    res["relevantes"],
                    res["insertados_neon"],
                )
            except Exception as item_exc:
                logger.warning(
                    "Error no bloqueante procesando semilla '%s': %s",
                    termino,
                    item_exc,
                )

            if pausa_entre_productos_s > 0 and idx < len(cola):
                await asyncio.sleep(pausa_entre_productos_s)

        ESTADO_WORKER_PRECARGA["ciclos_completados"] = (
            int(ESTADO_WORKER_PRECARGA.get("ciclos_completados") or 0) + 1
        )
    finally:
        ESTADO_WORKER_PRECARGA["activo"] = False
        ESTADO_WORKER_PRECARGA["termino_actual"] = None
        ESTADO_WORKER_PRECARGA["ultimo_ciclo_fin"] = dt.datetime.now(
            dt.timezone.utc
        ).isoformat()

    cruce_tiendas = cruzar_matriz_tiendas_y_prioridades()
    return {
        "productos_procesados": len(detalles),
        "ofertas_relevantes_evaluadas": total_evaluadas,
        "nuevos_precios_insertados": total_insertados,
        "siguientes_3_tiendas_prioritarias": cruce_tiendas["siguientes_3_alta_prioridad"],
        "detalles": detalles,
    }


async def iniciar_worker_periodico_background(
    intervalo_minutos: int = 180,
    muestra_por_categoria: int = 2,
    retardo_inicial_s: float = 25.0,
) -> None:
    """
    Bucle asíncrono no bloqueante diseñado para ejecutarse en segundo plano dentro
    del ciclo de vida de FastAPI en Render, manteniendo fresca la base de datos de Neon
    sin afectar la latencia de respuesta web (<50ms).
    """
    await asyncio.sleep(retardo_inicial_s)
    while True:
        try:
            await ejecutar_ciclo_precarga(
                muestra_por_categoria=muestra_por_categoria,
                pausa_entre_productos_s=2.0,
                persistir_en_db=True,
            )
        except asyncio.CancelledError:
            logger.info("Worker periódico de precarga detenido limpiamente.")
            break
        except Exception as exc:
            logger.warning("Excepción controlada en bucle periódico de precarga: %s", exc)

        await asyncio.sleep(max(60, intervalo_minutos * 60))
