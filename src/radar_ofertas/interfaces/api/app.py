"""
Capa de Interfaces (Web / API) de tecHunter GT v5.0 con FastAPI + Jinja2.

Arquitectura v5.0 (Cero Timeouts 502 en Render):
  - El buscador web (`GET /` y `GET /api/ofertas`) lee ÚNICAMENTE de Neon DB en milisegundos.
  - La precarga y actualización de precios ocurre en segundo plano mediante `worker_precarga.py`
    (tanto por CLI/cron como en el bucle asíncrono de `lifespan`), insertando en `historial_precios`
    únicamente cuando `_obtener_ultimo_precio_registrado` detecta una variación real de precio.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from radar_ofertas.application.use_cases.worker_precarga import (
    ESTADO_WORKER_PRECARGA,
    iniciar_worker_periodico_background,
    precargar_termino_semilla,
)
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.seed_data import (
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
)
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    Inicia de forma silenciosa y no bloqueante el Worker Periódico de Precarga en segundo plano
    cuando `ENABLE_BACKGROUND_WORKER` está activo (por defecto `true` en producción).
    """
    habilitar_worker = (
        os.environ.get("ENABLE_BACKGROUND_WORKER", "true").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    tarea_worker: asyncio.Task | None = None
    if habilitar_worker and (os.environ.get("DATABASE_URL") or "").strip():
        tarea_worker = asyncio.create_task(
            iniciar_worker_periodico_background(
                intervalo_minutos=int(os.environ.get("WORKER_INTERVAL_MINUTES", "180")),
                muestra_por_categoria=int(
                    os.environ.get("WORKER_SAMPLE_PER_CATEGORY", "2")
                ),
                retardo_inicial_s=30.0,
            )
        )
        logger.info(
            "Worker en segundo plano de tecHunter GT v5.0 programado exitosamente."
        )
    try:
        yield
    finally:
        if tarea_worker and not tarea_worker.done():
            tarea_worker.cancel()


app = FastAPI(
    title="tecHunter GT v5.0 — Comparador Instantáneo en Guatemala",
    description=(
        "Plataforma de comparación de precios en milisegundos respaldada por Neon DB "
        "y Worker de Precarga Inteligente sobre 18 tiendas activas en Guatemala."
    ),
    version="5.0.0",
    lifespan=lifespan,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TERMINOS_ZTECH_COMPUTO: tuple[str, ...] = (
    "laptop",
    "notebook",
    "workstation",
    "computadora",
    "pc",
    "macbook",
    "imac",
    "mac mini",
    "monitor",
    "pantalla",
    "rtx",
    "gtx",
    "radeon",
    "gpu",
    "tarjeta grafica",
    "procesador",
    "ryzen",
    "intel",
    "core i",
    "ram",
    "ssd",
    "nvme",
    "teclado",
    "mouse",
    "gamer",
    "gaming",
    "volante",
    "g29",
    "logitech",
    "asus",
    "lenovo",
    "thinkpad",
    "hp",
    "dell",
    "alienware",
    "msi",
    "acer",
    "razer",
    "servidor",
    "nas",
)


class EscanearRequest(BaseModel):
    query: str = ""
    categoria: str = ""


def _es_busqueda_computo_ztech(query: str, categoria_ui: str = "") -> bool:
    """
    Determina si la búsqueda o categoría activa pertenece al vertical de cómputo,
    laptops, workstations o hardware especializado para destacar Z-Tech Imports GT.
    """
    if categoria_ui.strip().lower() == "computo":
        return True
    q_lower = (query or "").strip().lower()
    if not q_lower and not categoria_ui.strip():
        return True
    return any(termino in q_lower for termino in TERMINOS_ZTECH_COMPUTO)


def _detectar_categoria_por_query(query: str, categoria_explicita: str = "") -> str:
    if categoria_explicita.strip():
        return categoria_explicita.strip().lower()
    q_lower = query.lower()
    palabras_mascotas = (
        "pedigree",
        "purina",
        "perro",
        "gato",
        "mascota",
        "dog chow",
        "beneful",
        "pro plan",
        "whiskas",
        "croqueta",
        "incaparina",
        "cafe",
        "arroz",
        "frijol",
        "aceite",
        "leche",
    )
    if any(p in q_lower for p in palabras_mascotas):
        return "mascotas"

    palabras_hogar = (
        "taladro",
        "barreno",
        "esmeriladora",
        "herramienta",
        "martillo",
        "destornillador",
        "truper",
        "pretul",
        "bosch",
        "dewalt",
        "stanley",
        "makita",
        "lampara",
        "ventilador",
        "refrigeradora",
        "lavadora",
        "microondas",
        "estufa",
        "hogar",
    )
    if any(p in q_lower for p in palabras_hogar):
        return "hogar"

    return "tecnologia"


def _calcular_ahorro_preciso(ofertas: list[dict[str, Any]]) -> float:
    """
    Calcula el ahorro máximo comparando equipos dentro de la misma familia/modelo o
    dentro de la misma categoría y gama para evitar comparar un equipo básico con uno profesional.
    """
    if len(ofertas) <= 1:
        return 0.0

    grupos: dict[str, list[float]] = defaultdict(list)
    for o in ofertas:
        clave = str(
            o.get("clave_modelo")
            or f"{o.get('categoria_ui', 'general')}:{o.get('gama_slug', 'media')}"
        )
        grupos[clave].append(
            float(o.get("costo_real_gtq") or o.get("precio_gtq") or 0.0)
        )

    ahorros_por_grupo = [
        max(precios_g) - min(precios_g)
        for precios_g in grupos.values()
        if len(precios_g) >= 2 and (max(precios_g) - min(precios_g)) > 0
    ]
    if ahorros_por_grupo:
        return round(max(ahorros_por_grupo), 2)

    precios = [float(o["precio_gtq"]) for o in ofertas]
    return round(max(precios) - min(precios), 2)


def _calcular_resumen(ofertas: list[dict[str, Any]]) -> dict[str, Any]:
    conteo_categorias = {
        "computo": sum(1 for o in ofertas if o.get("categoria_ui") == "computo"),
        "smartphones": sum(
            1 for o in ofertas if o.get("categoria_ui") == "smartphones"
        ),
        "hogar": sum(1 for o in ofertas if o.get("categoria_ui") == "hogar"),
        "herramientas": sum(
            1 for o in ofertas if o.get("categoria_ui") == "herramientas"
        ),
        "super-mascotas": sum(
            1 for o in ofertas if o.get("categoria_ui") == "super-mascotas"
        ),
    }
    conteo_gamas = {
        "profesional": sum(1 for o in ofertas if o.get("gama_slug") == "profesional"),
        "media": sum(1 for o in ofertas if o.get("gama_slug") == "media"),
        "entrada": sum(1 for o in ofertas if o.get("gama_slug") == "entrada"),
    }

    if not ofertas:
        return {
            "total": 0,
            "total_istore": 0,
            "total_epa": 0,
            "total_novex": 0,
            "total_intelaf": 0,
            "total_tecno_facil": 0,
            "total_la_curacao": 0,
            "total_tienda_claro": 0,
            "total_pricesmart": 0,
            "total_siman": 0,
            "total_elektra": 0,
            "total_ishop": 0,
            "total_walmart": 0,
            "total_paiz": 0,
            "total_maxi_despensa": 0,
            "total_cemaco": 0,
            "total_pacifiko": 0,
            "total_la_torre": 0,
            "total_tiendas_max": 0,
            "total_kemik": 0,
            "conteo_categorias": conteo_categorias,
            "conteo_gamas": conteo_gamas,
            "mejor_oferta": None,
            "ahorro_maximo_gtq": 0.0,
        }

    mejor = ofertas[0]
    ahorro = _calcular_ahorro_preciso(ofertas)
    total_istore = sum(
        1 for o in ofertas if o["tienda_slug"] in {"istore", "ishop"}
    )

    return {
        "total": len(ofertas),
        "total_istore": total_istore,
        "total_epa": sum(1 for o in ofertas if o["tienda_slug"] == "epa"),
        "total_novex": sum(1 for o in ofertas if o["tienda_slug"] == "novex"),
        "total_intelaf": sum(1 for o in ofertas if o["tienda_slug"] == "intelaf"),
        "total_tecno_facil": sum(
            1 for o in ofertas if o["tienda_slug"] in {"tecno-facil", "tecnofacil"}
        ),
        "total_la_curacao": sum(
            1 for o in ofertas if o["tienda_slug"] == "la-curacao"
        ),
        "total_tienda_claro": sum(
            1 for o in ofertas if o["tienda_slug"] == "tienda-claro"
        ),
        "total_pricesmart": sum(
            1 for o in ofertas if o["tienda_slug"] == "pricesmart"
        ),
        "total_siman": sum(1 for o in ofertas if o["tienda_slug"] == "siman"),
        "total_elektra": sum(1 for o in ofertas if o["tienda_slug"] == "elektra"),
        "total_ishop": total_istore,
        "total_walmart": sum(1 for o in ofertas if o["tienda_slug"] == "walmart"),
        "total_paiz": sum(1 for o in ofertas if o["tienda_slug"] == "paiz"),
        "total_maxi_despensa": sum(
            1 for o in ofertas if o["tienda_slug"] == "maxi-despensa"
        ),
        "total_cemaco": sum(1 for o in ofertas if o["tienda_slug"] == "cemaco"),
        "total_pacifiko": sum(1 for o in ofertas if o["tienda_slug"] == "pacifiko"),
        "total_la_torre": sum(1 for o in ofertas if o["tienda_slug"] == "la-torre"),
        "total_tiendas_max": sum(
            1 for o in ofertas if o["tienda_slug"] == "tiendas-max"
        ),
        "total_kemik": sum(1 for o in ofertas if o["tienda_slug"] == "kemik"),
        "conteo_categorias": conteo_categorias,
        "conteo_gamas": conteo_gamas,
        "mejor_oferta": mejor,
        "ahorro_maximo_gtq": ahorro,
    }


async def _ejecutar_scraper_seguro(
    scraper: Any, nombre_tienda: str, termino: str, timeout_s: float = 12.0
) -> tuple[list[OfertaLocal], str | None]:
    """
    Ejecuta un scraper con timeout estricto y captura cualquier excepción
    para garantizar que un fallo o bloqueo nunca rompa el flujo asíncrono.
    """
    try:
        ofertas = await asyncio.wait_for(
            scraper.buscar_producto(termino), timeout=timeout_s
        )
        return list(ofertas or []), None
    except asyncio.TimeoutError:
        msg = f"{nombre_tienda}: tiempo de espera agotado ({timeout_s:.0f}s)"
        logger.warning(msg)
        return [], msg
    except Exception as error:
        msg = f"{nombre_tienda}: {error.__class__.__name__}"
        logger.warning("Fallo controlado en scraper %s: %s", nombre_tienda, error)
        return [], msg


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Endpoint de salud para el balanceador de Render."""
    return {"status": "ok", "service": "tecHunter", "version": "5.0.0"}


@app.get("/api/seed-status")
async def api_seed_status() -> dict[str, Any]:
    """
    Expone el estado del Worker de Precarga Inteligente, el conteo de productos de
    `seed_list_guatemala` y el cruce automático de `tiendas_ecommerce_guatemala`
    con las siguientes 3 tiendas de alta prioridad.
    """
    cruce = cruzar_matriz_tiendas_y_prioridades()
    todos_seed = obtener_todos_los_productos_semilla()
    return {
        "version": "5.0.0",
        "total_productos_semilla": len(todos_seed),
        "categorias_semilla": {
            cat: len(items) for cat, items in seed_list_guatemala.items()
        },
        "worker_precarga": ESTADO_WORKER_PRECARGA,
        "matriz_tiendas": cruce,
    }


@app.get("/", response_class=HTMLResponse)
async def vista_comparador(
    request: Request,
    q: str = Query(default="", description="Término de búsqueda en Neon DB"),
    tienda: str = Query(
        default="",
        description="Filtro por tienda: istore, epa, novex, intelaf, tecno-facil, la-curacao, tienda-claro, pricesmart, siman, elektra, walmart, paiz, maxi-despensa, cemaco, pacifiko, la-torre, tiendas-max o kemik",
    ),
    cat: str = Query(
        default="",
        description="Filtro de categoría principal: computo, smartphones, hogar, herramientas o super-mascotas",
    ),
    gama: str = Query(
        default="",
        description="Filtro por gama de especificaciones: profesional, media o entrada",
    ),
    orden: str = Query(
        default="final",
        description="Criterio de ordenamiento: 'final' (precio con envío) o 'base' (precio de lista)",
    ),
) -> HTMLResponse:
    error_db: str | None = None
    ofertas_totales: list[dict[str, Any]] = []

    try:
        repositorio = PostgresOfertaRepository()
        ofertas_totales = await asyncio.to_thread(
            repositorio.buscar_ofertas_comparadas, q, tienda, ""
        )
    except Exception as error:
        logger.error("Error consultando Neon DB en GET /: %s", error)
        error_db = str(error)

    cat_limpia = cat.strip().lower()
    if cat_limpia in {
        "computo",
        "smartphones",
        "hogar",
        "herramientas",
        "super-mascotas",
    }:
        ofertas_visibles = [
            o for o in ofertas_totales if o.get("categoria_ui") == cat_limpia
        ]
    else:
        ofertas_visibles = list(ofertas_totales)

    gama_limpia = gama.strip().lower()
    if gama_limpia in {"profesional", "media", "entrada"}:
        ofertas_visibles = [
            o for o in ofertas_visibles if o.get("gama_slug") == gama_limpia
        ]

    orden_limpio = orden.strip().lower()
    if orden_limpio == "base":
        ofertas_visibles.sort(
            key=lambda o: (o.get("precio_gtq", 0.0), o.get("costo_real_gtq", 0.0))
        )
    else:
        ofertas_visibles.sort(
            key=lambda o: (o.get("costo_real_gtq", 0.0), o.get("precio_gtq", 0.0))
        )

    resumen = _calcular_resumen(ofertas_totales)
    resumen_visible = _calcular_resumen(ofertas_visibles)
    resumen["mejor_oferta"] = resumen_visible["mejor_oferta"]
    resumen["ahorro_maximo_gtq"] = resumen_visible["ahorro_maximo_gtq"]

    destacar_ztech = _es_busqueda_computo_ztech(q, cat_limpia)
    cruce_tiendas = cruzar_matriz_tiendas_y_prioridades()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "tienda_activa": tienda.lower().strip(),
            "categoria_activa": cat_limpia,
            "gama_activa": gama_limpia,
            "orden_activo": orden_limpio
            if orden_limpio in {"final", "base"}
            else "final",
            "ofertas": ofertas_visibles,
            "resumen": resumen,
            "destacar_ztech": destacar_ztech,
            "siguientes_tiendas": cruce_tiendas["siguientes_3_alta_prioridad"],
            "error_db": error_db,
        },
    )


@app.get("/api/ofertas")
async def api_listar_ofertas(
    q: str = Query(default="", description="Término de búsqueda"),
    tienda: str = Query(default="", description="Filtro opcional de tienda"),
    cat: str = Query(default="", description="Filtro opcional de categoría UI"),
    gama: str = Query(
        default="", description="Filtro opcional de gama: profesional, media, entrada"
    ),
) -> dict[str, Any]:
    try:
        repositorio = PostgresOfertaRepository()
        ofertas = await asyncio.to_thread(
            repositorio.buscar_ofertas_comparadas, q, tienda, cat
        )
        gama_limpia = gama.strip().lower()
        if gama_limpia in {"profesional", "media", "entrada"}:
            ofertas = [o for o in ofertas if o.get("gama_slug") == gama_limpia]
        return {
            "query": q,
            "tienda": tienda,
            "categoria_ui": cat,
            "gama": gama_limpia,
            "destacar_ztech": _es_busqueda_computo_ztech(q, cat),
            "resumen": _calcular_resumen(ofertas),
            "ofertas": ofertas,
        }
    except Exception as error:
        logger.error("Error en GET /api/ofertas: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/escanear")
async def api_escanear_en_vivo(payload: EscanearRequest) -> JSONResponse:
    """
    Endpoint asíncrono no bloqueante (v5.0):
    Para erradicar cualquier error 502 por timeout en Render, delega la actualización
    al Worker de Precarga en segundo plano (`asyncio.create_task`) y responde de inmediato.
    """
    termino = (payload.query or "").strip()
    if not termino:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "nuevas_ofertas": 0,
                "detail": "Debes indicar un término de búsqueda.",
            },
        )

    categoria = _detectar_categoria_por_query(termino, payload.categoria)
    asyncio.create_task(
        precargar_termino_semilla(
            termino=termino, categoria_db=categoria, persistir_en_db=True
        )
    )
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "modo": "background_worker_v5",
            "nuevas_ofertas": 0,
            "query": termino,
            "categoria": categoria,
            "detail": (
                "Tarea encolada en el Worker en Segundo Plano; "
                "el buscador web consulta directamente Neon DB en milisegundos."
            ),
        },
    )


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "radar_ofertas.interfaces.api.app:app",
        host="0.0.0.0",
        port=puerto,
        reload=False,
    )
