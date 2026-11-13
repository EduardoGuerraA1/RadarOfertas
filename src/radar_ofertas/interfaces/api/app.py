"""
Capa de Interfaces (Web / API) de tecHunter con FastAPI + Jinja2.
Configurada para despliegue en la nube (Render / Railway) leyendo el puerto
dinámico desde `os.environ.get("PORT", 8000)`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="tecHunter — Comparador de Precios en Guatemala",
    description=(
        "Plataforma de comparación de precios en tiempo real "
        "(Kemik, Pacifiko y Supermercados La Torre) respaldada por Neon DB."
    ),
    version="1.1.0",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class EscanearRequest(BaseModel):
    query: str
    categoria: str = ""


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
    )
    if any(p in q_lower for p in palabras_mascotas):
        return "mascotas"
    return "tecnologia"


def _calcular_resumen(ofertas: list[dict[str, Any]]) -> dict[str, Any]:
    if not ofertas:
        return {
            "total": 0,
            "total_kemik": 0,
            "total_pacifiko": 0,
            "total_la_torre": 0,
            "mejor_oferta": None,
            "ahorro_maximo_gtq": 0.0,
        }

    precios = [o["precio_gtq"] for o in ofertas]
    mejor = ofertas[0]
    ahorro = max(precios) - min(precios) if len(precios) > 1 else 0.0

    return {
        "total": len(ofertas),
        "total_kemik": sum(1 for o in ofertas if o["tienda_slug"] == "kemik"),
        "total_pacifiko": sum(1 for o in ofertas if o["tienda_slug"] == "pacifiko"),
        "total_la_torre": sum(1 for o in ofertas if o["tienda_slug"] == "la-torre"),
        "mejor_oferta": mejor,
        "ahorro_maximo_gtq": round(ahorro, 2),
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Endpoint de salud para el balanceador de Render."""
    return {"status": "ok", "service": "tecHunter"}


@app.get("/", response_class=HTMLResponse)
async def vista_comparador(
    request: Request,
    q: str = Query(default="", description="Término de búsqueda en Neon DB"),
    tienda: str = Query(
        default="", description="Filtro por tienda: kemik, pacifiko o la-torre"
    ),
) -> HTMLResponse:
    error_db: str | None = None
    ofertas: list[dict[str, Any]] = []

    try:
        repositorio = PostgresOfertaRepository()
        ofertas = await asyncio.to_thread(
            repositorio.buscar_ofertas_comparadas, q, tienda
        )
    except Exception as error:
        logger.error("Error consultando Neon DB en GET /: %s", error)
        error_db = str(error)

    resumen = _calcular_resumen(ofertas)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "tienda_activa": tienda.lower().strip(),
            "ofertas": ofertas,
            "resumen": resumen,
            "error_db": error_db,
        },
    )


@app.get("/api/ofertas")
async def api_listar_ofertas(
    q: str = Query(default="", description="Término de búsqueda"),
    tienda: str = Query(default="", description="Filtro opcional de tienda"),
) -> dict[str, Any]:
    try:
        repositorio = PostgresOfertaRepository()
        ofertas = await asyncio.to_thread(
            repositorio.buscar_ofertas_comparadas, q, tienda
        )
        return {
            "query": q,
            "tienda": tienda,
            "resumen": _calcular_resumen(ofertas),
            "ofertas": ofertas,
        }
    except Exception as error:
        logger.error("Error en GET /api/ofertas: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/escanear")
async def api_escanear_en_vivo(payload: EscanearRequest) -> dict[str, Any]:
    termino = payload.query.strip()
    if not termino:
        raise HTTPException(
            status_code=400, detail="Debes indicar un término de búsqueda."
        )

    categoria = _detectar_categoria_por_query(termino, payload.categoria)

    kemik_scraper = KemikScraper(headless=True)
    pacifiko_scraper = PacifikoScraper()
    super_scraper = SuperScraper()

    ofertas_kemik, ofertas_pacifiko, ofertas_super = await asyncio.gather(
        kemik_scraper.buscar_producto(termino),
        pacifiko_scraper.buscar_producto(termino),
        super_scraper.buscar_producto(termino),
    )
    unificadas = [*ofertas_kemik, *ofertas_pacifiko, *ofertas_super]

    insertados = 0
    if unificadas:
        repositorio = PostgresOfertaRepository()
        insertados = await asyncio.to_thread(
            repositorio.guardar_ofertas, unificadas, categoria
        )

    return {
        "query": termino,
        "categoria": categoria,
        "extraidos_kemik": len(ofertas_kemik),
        "extraidos_pacifiko": len(ofertas_pacifiko),
        "extraidos_la_torre": len(ofertas_super),
        "insertados_neon": insertados,
    }


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "radar_ofertas.interfaces.api.app:app",
        host="0.0.0.0",
        port=puerto,
        reload=False,
    )
