"""
Caso de Uso / Background Worker de Precarga Inteligente (tecHunter GT v5.2).

Barre de forma automática, silenciosa y resiliente los productos de `seed_list_guatemala`
en las 24 tiendas activas de Guatemala (incluyendo Kemik, Intelaf, Rech, Click Guatemala y Tera),
aplicando el Motor de Precisión de Modelos y persistiendo en Neon DB bajo la regla estricta
de ahorro de almacenamiento:
  - `PostgresOfertaRepository.guardar_ofertas` valida mediante `_obtener_ultimo_precio_registrado`
    que SOLO se inserte un registro en `historial_precios` cuando el precio realmente varió.
  - Programación automática multi-ciclo: al menos 3 veces al día (cada 8 horas / 480 minutos)
    para capturar fluctuaciones de stock y ofertas flash de Kemik, Intelaf, Rech, Click y Tera.
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
from radar_ofertas.infrastructure.scrapers.click_scraper import ClickScraper
from radar_ofertas.infrastructure.scrapers.epa_scraper import EpaScraper
from radar_ofertas.infrastructure.scrapers.guatemaladigital_scraper import (
    GuatemalaDigitalScraper,
)
from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
from radar_ofertas.infrastructure.scrapers.istore_scraper import IStoreScraper
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
from radar_ofertas.infrastructure.scrapers.lacuracao_scraper import LaCuracaoScraper
from radar_ofertas.infrastructure.scrapers.max_scraper import MaxScraper
from radar_ofertas.infrastructure.scrapers.novex_scraper import NovexScraper
from radar_ofertas.infrastructure.scrapers.officedepot_scraper import OfficeDepotScraper
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
from radar_ofertas.infrastructure.scrapers.pricesmart_scraper import PriceSmartScraper
from radar_ofertas.infrastructure.scrapers.rech_scraper import RechScraper
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper
from radar_ofertas.infrastructure.scrapers.tecnofacil_scraper import TecnoFacilScraper
from radar_ofertas.infrastructure.scrapers.tera_scraper import TeraScraper
from radar_ofertas.infrastructure.scrapers.tiendas_oficiales_scraper import (
    TiendasOficialesScraper,
)
from radar_ofertas.infrastructure.scrapers.tigo_scraper import TigoScraper
from radar_ofertas.infrastructure.scrapers.tropigas_scraper import TropigasScraper
from radar_ofertas.infrastructure.scrapers.walmart_scraper import WalmartScraper

logger = logging.getLogger("tecHunter.worker_precarga")

# Frecuencia oficial v5.4: mínimo 3 sincronizaciones diarias (cada 8 horas = 480 minutos)
CICLOS_DIARIOS_MINIMOS: int = 3
INTERVALO_HORAS_DEFAULT: int = 8
INTERVALO_MINUTOS_DEFAULT: int = INTERVALO_HORAS_DEFAULT * 60  # 480 minutos
VENTANAS_SINCRONIZACION_GT: tuple[str, ...] = (
    "06:00 GT (Corte Matutino)",
    "14:00 GT (Corte Mediodía / Ofertas Flash)",
    "22:00 GT (Corte Nocturno)",
)

ESTADO_WORKER_PRECARGA: dict[str, Any] = {
    "activo": False,
    "frecuencia_diaria_ciclos": CICLOS_DIARIOS_MINIMOS,
    "intervalo_horas": INTERVALO_HORAS_DEFAULT,
    "intervalo_minutos": INTERVALO_MINUTOS_DEFAULT,
    "ventanas_programadas_gt": list(VENTANAS_SINCRONIZACION_GT),
    "ultimo_ciclo_inicio": None,
    "ultimo_ciclo_fin": None,
    "proximo_ciclo_programado": None,
    "termino_actual": None,
    "productos_procesados_ciclo": 0,
    "ofertas_evaluadas_ciclo": 0,
    "nuevos_precios_insertados_ciclo": 0,
    "busquedas_pendientes_procesadas_ciclo": 0,
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
    ciclo_offset: int = 0,
) -> list[tuple[str, str, str]]:
    """
    Construye la cola de ejecución `(categoria_seed, categoria_db, termino)` desde `seed_list_guatemala`.
    - Si `muestra_por_categoria > 0`, selecciona `muestra_por_categoria` productos de cada categoría
      (rotando por `ciclo_offset` cuando se ejecuta en los 3 turnos diarios) para lograr cobertura
      transversal rápida en las 5 categorías.
    """
    cola: list[tuple[str, str, str]] = []
    cat_filtro_limpio = categoria_filtro.strip().lower()

    for cat_seed, lista_terminos in seed_list_guatemala.items():
        if cat_filtro_limpio and cat_seed.lower() != cat_filtro_limpio:
            continue
        cat_db = MAPEO_CATEGORIA_SEED_A_DB.get(cat_seed, "tecnologia")
        if muestra_por_categoria > 0 and lista_terminos:
            total_cat = len(lista_terminos)
            inicio = (ciclo_offset * muestra_por_categoria) % total_cat
            seleccionados = [
                lista_terminos[(inicio + i) % total_cat]
                for i in range(min(muestra_por_categoria, total_cat))
            ]
        else:
            seleccionados = list(lista_terminos)

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
    Ejecuta en paralelo los scrapers ligeros de las 25 tiendas activas (incluyendo Guatemala Digital,
    Kemik, Pacifiko, Intelaf, Rech, Click Guatemala y Tera) para un término de `seed_list_guatemala`,
    filtra con el Motor de Precisión y guarda únicamente cambios reales de precio en Neon DB.
    """
    scrapers: list[tuple[str, Any]] = [
        ("Guatemala Digital", GuatemalaDigitalScraper(timeout_s=int(timeout_scraper_s))),
        (
            "Kemik",
            KemikScraper(
                headless=True,
                usar_playwright=False,
                timeout_s=int(timeout_scraper_s),
            ),
        ),
        ("Pacifiko", PacifikoScraper(timeout_s=int(timeout_scraper_s))),
        (
            "Tiendas Max",
            MaxScraper(
                headless=True,
                timeout_s=int(timeout_scraper_s),
                usar_playwright_fallback=False,
            ),
        ),
        ("Cemaco", CemacoScraper(timeout_s=int(timeout_scraper_s))),
        (
            "Intelaf",
            IntelafScraper(
                headless=True,
                timeout_s=int(timeout_scraper_s),
                usar_playwright_fallback=False,
            ),
        ),
        ("Rech", RechScraper(timeout_s=int(timeout_scraper_s))),
        ("Click Guatemala", ClickScraper(timeout_s=int(timeout_scraper_s))),
        ("Tera", TeraScraper(timeout_s=int(timeout_scraper_s))),
        ("iStore", IStoreScraper(timeout_s=int(timeout_scraper_s))),
        ("EPA", EpaScraper(timeout_s=int(timeout_scraper_s))),
        ("Novex", NovexScraper(timeout_s=int(timeout_scraper_s))),
        ("Office Depot", OfficeDepotScraper(timeout_s=int(timeout_scraper_s))),
        (
            "Tecno Fácil",
            TecnoFacilScraper(
                headless=True,
                timeout_s=int(timeout_scraper_s),
                usar_playwright_fallback=False,
            ),
        ),
        ("La Curacao", LaCuracaoScraper(timeout_s=int(timeout_scraper_s))),
        ("Tropigas", TropigasScraper(timeout_s=int(timeout_scraper_s))),
        ("Tienda Claro", ClaroScraper(timeout_s=int(timeout_scraper_s))),
        ("Tienda Tigo", TigoScraper(timeout_s=int(timeout_scraper_s))),
        ("PriceSmart", PriceSmartScraper(timeout_s=int(timeout_scraper_s))),
        ("Oficiales", TiendasOficialesScraper(timeout_s=int(timeout_scraper_s))),
        ("Walmart Grupo", WalmartScraper(timeout_s=int(timeout_scraper_s))),
        ("La Torre", SuperScraper()),
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
    ciclo_offset: int = 0,
) -> dict[str, Any]:
    """
    Ejecuta primero las `busquedas_pendientes` registradas en Neon DB y a continuación
    el barrido completo o por lote rotativo sobre `seed_list_guatemala`.
    """
    cola = seleccionar_lote_semilla(
        categoria_filtro=categoria_filtro,
        muestra_por_categoria=muestra_por_categoria,
        limite_total=limite_total,
        ciclo_offset=ciclo_offset,
    )

    ESTADO_WORKER_PRECARGA["activo"] = True
    ESTADO_WORKER_PRECARGA["ultimo_ciclo_inicio"] = dt.datetime.now(
        dt.timezone.utc
    ).isoformat()
    ESTADO_WORKER_PRECARGA["productos_procesados_ciclo"] = 0
    ESTADO_WORKER_PRECARGA["ofertas_evaluadas_ciclo"] = 0
    ESTADO_WORKER_PRECARGA["nuevos_precios_insertados_ciclo"] = 0
    ESTADO_WORKER_PRECARGA["busquedas_pendientes_procesadas_ciclo"] = 0

    repositorio: PostgresOfertaRepository | None = None
    if persistir_en_db and (os.getenv("DATABASE_URL") or "").strip():
        repositorio = PostgresOfertaRepository()

    # 1. Procesar búsquedas pendientes registradas cuando /api/buscar-en-vivo devolvió 0 resultados
    if repositorio is not None:
        pendientes = await asyncio.to_thread(
            repositorio.obtener_busquedas_pendientes, 10
        )
        for idx_p, (termino_pend, cat_pend) in enumerate(pendientes, 1):
            try:
                res_pend = await precargar_termino_semilla(
                    termino=termino_pend,
                    categoria_db=cat_pend,
                    repositorio=repositorio,
                    persistir_en_db=True,
                )
                await asyncio.to_thread(
                    repositorio.marcar_busqueda_pendiente_procesada,
                    termino_pend,
                    res_pend["relevantes"],
                )
                ESTADO_WORKER_PRECARGA["busquedas_pendientes_procesadas_ciclo"] = idx_p
            except Exception as exc_pend:
                logger.debug(
                    "Worker omitió búsqueda pendiente '%s': %s", termino_pend, exc_pend
                )

    total_evaluadas = 0
    total_insertados = 0
    detalles: list[dict[str, Any]] = []

    logger.info(
        "Iniciando ciclo de precarga inteligente tecHunter v5.4 (%d términos semilla en cola, 3x/día)...",
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
        "frecuencia_diaria_ciclos": ESTADO_WORKER_PRECARGA["frecuencia_diaria_ciclos"],
        "intervalo_horas": ESTADO_WORKER_PRECARGA["intervalo_horas"],
        "siguientes_3_tiendas_prioritarias": cruce_tiendas["siguientes_3_alta_prioridad"],
        "detalles": detalles,
    }


def calcular_intervalo_sincronizacion_minutos(intervalo_solicitado_min: int = INTERVALO_MINUTOS_DEFAULT) -> int:
    """
    Garantiza que el intervalo de sincronización automática ejecute al menos 3 ciclos al día
    (máximo cada 8 horas = 480 minutos, mínimo 30 minutos).
    """
    return max(30, min(int(intervalo_solicitado_min), INTERVALO_MINUTOS_DEFAULT))


async def iniciar_worker_periodico_background(
    intervalo_minutos: int = INTERVALO_MINUTOS_DEFAULT,
    muestra_por_categoria: int = 3,
    retardo_inicial_s: float = 45.0,
) -> None:
    """
    Orquestador asíncrono en segundo plano configurado para ejecutar la sincronización de precios
    al menos 3 veces al día de forma automática (cada 8 horas / 480 minutos por defecto),
    capturando fluctuaciones de stock y ofertas flash de Kemik, Intelaf, Rech, Click y Tera.
    """
    intervalo_efectivo_min = calcular_intervalo_sincronizacion_minutos(intervalo_minutos)
    ciclos_por_dia = max(CICLOS_DIARIOS_MINIMOS, round(1440 / intervalo_efectivo_min))
    ESTADO_WORKER_PRECARGA["intervalo_minutos"] = intervalo_efectivo_min
    ESTADO_WORKER_PRECARGA["intervalo_horas"] = round(intervalo_efectivo_min / 60, 1)
    ESTADO_WORKER_PRECARGA["frecuencia_diaria_ciclos"] = ciclos_por_dia

    await asyncio.sleep(retardo_inicial_s)
    ciclo_idx = 0
    while True:
        try:
            await ejecutar_ciclo_precarga(
                muestra_por_categoria=muestra_por_categoria,
                pausa_entre_productos_s=2.0,
                persistir_en_db=True,
                ciclo_offset=ciclo_idx,
            )
            ciclo_idx += 1
        except asyncio.CancelledError:
            logger.info("Worker periódico de precarga detenido limpiamente.")
            break
        except Exception as exc:
            logger.warning("Excepción controlada en bucle periódico de precarga: %s", exc)

        proximo_dt = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
            minutes=intervalo_efectivo_min
        )
        ESTADO_WORKER_PRECARGA["proximo_ciclo_programado"] = proximo_dt.isoformat()
        await asyncio.sleep(intervalo_efectivo_min * 60)
