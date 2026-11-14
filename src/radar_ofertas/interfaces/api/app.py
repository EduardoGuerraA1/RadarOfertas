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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import filtrar_ofertas_relevantes
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.cemaco_scraper import CemacoScraper
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
from radar_ofertas.infrastructure.scrapers.max_scraper import MaxScraper
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
from radar_ofertas.infrastructure.scrapers.pricesmart_scraper import PriceSmartScraper
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper
from radar_ofertas.infrastructure.scrapers.tiendas_oficiales_scraper import (
    TiendasOficialesScraper,
)
from radar_ofertas.infrastructure.scrapers.walmart_scraper import WalmartScraper

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="tecHunter — Comparador de Precios en Guatemala",
    description=(
        "Plataforma de comparación de precios en tiempo real "
        "(Siman, Elektra, iShop, Walmart, Paiz, Maxi Despensa, Kemik, Pacifiko, "
        "La Torre, Tiendas Max, Cemaco y PriceSmart) respaldada por Neon DB."
    ),
    version="2.5.0",
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


def _es_busqueda_computo_ztech(query: str) -> bool:
    """
    Determina si la búsqueda actual pertenece al vertical de cómputo, laptops,
    workstations o hardware especializado para destacar el banner de Z-Tech Imports.
    """
    q_lower = (query or "").strip().lower()
    if not q_lower:
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
    )
    if any(p in q_lower for p in palabras_mascotas):
        return "mascotas"

    palabras_hogar = (
        "taladro",
        "esmeriladora",
        "herramienta",
        "martillo",
        "destornillador",
        "truper",
        "pretul",
        "bosch",
        "dewalt",
        "stanley",
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


def _calcular_resumen(ofertas: list[dict[str, Any]]) -> dict[str, Any]:
    if not ofertas:
        return {
            "total": 0,
            "total_kemik": 0,
            "total_pacifiko": 0,
            "total_la_torre": 0,
            "total_tiendas_max": 0,
            "total_cemaco": 0,
            "total_walmart": 0,
            "total_paiz": 0,
            "total_maxi_despensa": 0,
            "total_siman": 0,
            "total_elektra": 0,
            "total_ishop": 0,
            "total_pricesmart": 0,
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
        "total_tiendas_max": sum(
            1 for o in ofertas if o["tienda_slug"] in {"tiendas-max", "tecnofacil"}
        ),
        "total_cemaco": sum(1 for o in ofertas if o["tienda_slug"] == "cemaco"),
        "total_walmart": sum(1 for o in ofertas if o["tienda_slug"] == "walmart"),
        "total_paiz": sum(1 for o in ofertas if o["tienda_slug"] == "paiz"),
        "total_maxi_despensa": sum(
            1 for o in ofertas if o["tienda_slug"] == "maxi-despensa"
        ),
        "total_siman": sum(1 for o in ofertas if o["tienda_slug"] == "siman"),
        "total_elektra": sum(1 for o in ofertas if o["tienda_slug"] == "elektra"),
        "total_ishop": sum(1 for o in ofertas if o["tienda_slug"] == "ishop"),
        "total_pricesmart": sum(
            1 for o in ofertas if o["tienda_slug"] == "pricesmart"
        ),
        "mejor_oferta": mejor,
        "ahorro_maximo_gtq": round(ahorro, 2),
    }


async def _ejecutar_scraper_seguro(
    scraper: Any, nombre_tienda: str, termino: str, timeout_s: float = 12.0
) -> tuple[list[OfertaLocal], str | None]:
    """
    Ejecuta un scraper con timeout estricto y captura cualquier excepción
    para garantizar que un fallo o bloqueo nunca rompa el endpoint JSON.
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
    return {"status": "ok", "service": "tecHunter"}


@app.get("/", response_class=HTMLResponse)
async def vista_comparador(
    request: Request,
    q: str = Query(default="", description="Término de búsqueda en Neon DB"),
    tienda: str = Query(
        default="",
        description="Filtro por tienda: siman, elektra, ishop, walmart, paiz, maxi-despensa, kemik, pacifiko, la-torre, tiendas-max, cemaco o pricesmart",
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
    destacar_ztech = _es_busqueda_computo_ztech(q)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "tienda_activa": tienda.lower().strip(),
            "ofertas": ofertas,
            "resumen": resumen,
            "destacar_ztech": destacar_ztech,
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
            "destacar_ztech": _es_busqueda_computo_ztech(q),
            "resumen": _calcular_resumen(ofertas),
            "ofertas": ofertas,
        }
    except Exception as error:
        logger.error("Error en GET /api/ofertas: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/escanear")
async def api_escanear_en_vivo(payload: EscanearRequest) -> JSONResponse:
    """
    Ejecuta todos los scrapers en paralelo con aislamiento de fallos, timeouts
    individuales y Filtro Inteligente Anti-Ruido. Devuelve SIEMPRE un JSON
    estructurado (`status`, `nuevas_ofertas`) para evitar errores de parseo.
    """
    try:
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

        kemik_scraper = KemikScraper(headless=True)
        pacifiko_scraper = PacifikoScraper()
        super_scraper = SuperScraper()
        max_scraper = MaxScraper(
            headless=True, timeout_s=8, usar_playwright_fallback=False
        )
        cemaco_scraper = CemacoScraper(timeout_s=10)
        walmart_scraper = WalmartScraper(timeout_s=10)
        oficiales_scraper = TiendasOficialesScraper(timeout_s=10)
        pricesmart_scraper = PriceSmartScraper()

        resultados = await asyncio.gather(
            _ejecutar_scraper_seguro(kemik_scraper, "Kemik", termino, timeout_s=8.0),
            _ejecutar_scraper_seguro(
                pacifiko_scraper, "Pacifiko", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                super_scraper, "La Torre", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                max_scraper, "Tiendas Max", termino, timeout_s=8.0
            ),
            _ejecutar_scraper_seguro(cemaco_scraper, "Cemaco", termino, timeout_s=12.0),
            _ejecutar_scraper_seguro(
                walmart_scraper, "Grupo Walmart", termino, timeout_s=14.0
            ),
            _ejecutar_scraper_seguro(
                oficiales_scraper, "Oficiales (Siman/Elektra/iShop)", termino, timeout_s=14.0
            ),
            _ejecutar_scraper_seguro(
                pricesmart_scraper, "PriceSmart", termino, timeout_s=8.0
            ),
        )

        (ofertas_kemik, err_kemik) = resultados[0]
        (ofertas_pacifiko, err_pacifiko) = resultados[1]
        (ofertas_super, err_super) = resultados[2]
        (ofertas_max, err_max) = resultados[3]
        (ofertas_cemaco, err_cemaco) = resultados[4]
        (ofertas_walmart, err_walmart) = resultados[5]
        (ofertas_oficiales, err_oficiales) = resultados[6]
        (ofertas_pricesmart, err_pricesmart) = resultados[7]

        advertencias = [
            err
            for err in (
                err_kemik,
                err_pacifiko,
                err_super,
                err_max,
                err_cemaco,
                err_walmart,
                err_oficiales,
                err_pricesmart,
            )
            if err is not None
        ]

        unificadas_brutas = [
            *ofertas_kemik,
            *ofertas_pacifiko,
            *ofertas_super,
            *ofertas_max,
            *ofertas_cemaco,
            *ofertas_walmart,
            *ofertas_oficiales,
            *ofertas_pricesmart,
        ]
        unificadas = [
            o
            for o in filtrar_ofertas_relevantes(unificadas_brutas, termino)
            if o.precio_gtq > 0 and o.estado_precio_membresia != "oculto_requiere_login"
        ]
        descartados_ruido = len(unificadas_brutas) - len(unificadas)

        insertados = 0
        error_db: str | None = None
        if unificadas:
            try:
                repositorio = PostgresOfertaRepository()
                insertados = await asyncio.to_thread(
                    repositorio.guardar_ofertas, unificadas, categoria
                )
            except Exception as db_exc:
                logger.error("Error guardando ofertas en Neon DB: %s", db_exc)
                error_db = str(db_exc)
                advertencias.append(f"Neon DB: {error_db}")

        return JSONResponse(
            status_code=200,
            content={
                "status": "success" if error_db is None else "partial",
                "nuevas_ofertas": insertados,
                "evaluados_relevantes": len(unificadas),
                "descartados_ruido": descartados_ruido,
                "query": termino,
                "categoria": categoria,
                "extraidos_kemik": len(ofertas_kemik),
                "extraidos_pacifiko": len(ofertas_pacifiko),
                "extraidos_la_torre": len(ofertas_super),
                "extraidos_tiendas_max": len(ofertas_max),
                "extraidos_cemaco": len(ofertas_cemaco),
                "extraidos_walmart": len(ofertas_walmart),
                "extraidos_oficiales": len(ofertas_oficiales),
                "extraidos_pricesmart": len(ofertas_pricesmart),
                "insertados_neon": insertados,
                "advertencias": advertencias,
            },
        )
    except Exception as unexpected_error:
        logger.exception("Error inesperado en POST /api/escanear: %s", unexpected_error)
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "nuevas_ofertas": 0,
                "insertados_neon": 0,
                "detail": f"Error controlado en el servidor: {unexpected_error}",
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
