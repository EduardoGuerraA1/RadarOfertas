"""
Capa de Interfaces (Web / API) de tecHunter GT v4.0 con FastAPI + Jinja2.
Configurada para despliegue en la nube (Render / Railway) leyendo el puerto
dinámico desde `os.environ.get("PORT", 8000)`.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
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
from radar_ofertas.infrastructure.scrapers.claro_scraper import ClaroScraper
from radar_ofertas.infrastructure.scrapers.epa_scraper import EpaScraper
from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
from radar_ofertas.infrastructure.scrapers.istore_scraper import IStoreScraper
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
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

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(
    title="tecHunter GT v4.0 — Comparador de Precios en Guatemala",
    description=(
        "Plataforma de comparación de precios en tiempo real "
        "(iStore, EPA, Novex, Intelaf, Tecno Fácil, La Curacao, Tienda Claro, "
        "PriceSmart, Siman, Elektra, Walmart, Paiz, Maxi Despensa, Kemik, "
        "Pacifiko, La Torre, Tiendas Max y Cemaco) respaldada por Neon DB."
    ),
    version="4.0.0",
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
        clave = str(o.get("clave_modelo") or f"{o.get('categoria_ui', 'general')}:{o.get('gama_slug', 'media')}")
        grupos[clave].append(float(o.get("costo_real_gtq") or o.get("precio_gtq") or 0.0))

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
    return {"status": "ok", "service": "tecHunter", "version": "4.0.0"}


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
        ofertas_visibles.sort(key=lambda o: (o.get("precio_gtq", 0.0), o.get("costo_real_gtq", 0.0)))
    else:
        ofertas_visibles.sort(key=lambda o: (o.get("costo_real_gtq", 0.0), o.get("precio_gtq", 0.0)))

    resumen = _calcular_resumen(ofertas_totales)
    resumen_visible = _calcular_resumen(ofertas_visibles)
    resumen["mejor_oferta"] = resumen_visible["mejor_oferta"]
    resumen["ahorro_maximo_gtq"] = resumen_visible["ahorro_maximo_gtq"]

    destacar_ztech = _es_busqueda_computo_ztech(q, cat_limpia)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "tienda_activa": tienda.lower().strip(),
            "categoria_activa": cat_limpia,
            "gama_activa": gama_limpia,
            "orden_activo": orden_limpio if orden_limpio in {"final", "base"} else "final",
            "ofertas": ofertas_visibles,
            "resumen": resumen,
            "destacar_ztech": destacar_ztech,
            "error_db": error_db,
        },
    )


@app.get("/api/ofertas")
async def api_listar_ofertas(
    q: str = Query(default="", description="Término de búsqueda"),
    tienda: str = Query(default="", description="Filtro opcional de tienda"),
    cat: str = Query(default="", description="Filtro opcional de categoría UI"),
    gama: str = Query(default="", description="Filtro opcional de gama: profesional, media, entrada"),
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
    Ejecuta todos los scrapers v4.0 en paralelo con aislamiento de fallos, timeouts
    individuales y el Motor de Precisión de Modelos. Devuelve SIEMPRE un JSON
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
        tecnofacil_scraper = TecnoFacilScraper(
            headless=True, timeout_s=8, usar_playwright_fallback=False
        )
        cemaco_scraper = CemacoScraper(timeout_s=10)
        walmart_scraper = WalmartScraper(timeout_s=10)
        oficiales_scraper = TiendasOficialesScraper(timeout_s=10)
        pricesmart_scraper = PriceSmartScraper(timeout_s=10)
        intelaf_scraper = IntelafScraper(headless=True, timeout_s=8)
        lacuracao_scraper = LaCuracaoScraper(timeout_s=10)
        claro_scraper = ClaroScraper(timeout_s=10)
        istore_scraper = IStoreScraper(timeout_s=10)
        epa_scraper = EpaScraper(timeout_s=10)
        novex_scraper = NovexScraper(timeout_s=10)

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
            _ejecutar_scraper_seguro(
                tecnofacil_scraper, "Tecno Fácil", termino, timeout_s=8.0
            ),
            _ejecutar_scraper_seguro(cemaco_scraper, "Cemaco", termino, timeout_s=12.0),
            _ejecutar_scraper_seguro(
                walmart_scraper, "Grupo Walmart", termino, timeout_s=14.0
            ),
            _ejecutar_scraper_seguro(
                oficiales_scraper,
                "Oficiales (Siman/Elektra/iShop)",
                termino,
                timeout_s=14.0,
            ),
            _ejecutar_scraper_seguro(
                pricesmart_scraper, "PriceSmart", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                intelaf_scraper, "Intelaf", termino, timeout_s=10.0
            ),
            _ejecutar_scraper_seguro(
                lacuracao_scraper, "La Curacao", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                claro_scraper, "Tienda Claro", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                istore_scraper, "iStore", termino, timeout_s=10.0
            ),
            _ejecutar_scraper_seguro(
                epa_scraper, "EPA", termino, timeout_s=12.0
            ),
            _ejecutar_scraper_seguro(
                novex_scraper, "Novex", termino, timeout_s=10.0
            ),
        )

        (ofertas_kemik, err_kemik) = resultados[0]
        (ofertas_pacifiko, err_pacifiko) = resultados[1]
        (ofertas_super, err_super) = resultados[2]
        (ofertas_max, err_max) = resultados[3]
        (ofertas_tecnofacil, err_tecnofacil) = resultados[4]
        (ofertas_cemaco, err_cemaco) = resultados[5]
        (ofertas_walmart, err_walmart) = resultados[6]
        (ofertas_oficiales, err_oficiales) = resultados[7]
        (ofertas_pricesmart, err_pricesmart) = resultados[8]
        (ofertas_intelaf, err_intelaf) = resultados[9]
        (ofertas_lacuracao, err_lacuracao) = resultados[10]
        (ofertas_claro, err_claro) = resultados[11]
        (ofertas_istore, err_istore) = resultados[12]
        (ofertas_epa, err_epa) = resultados[13]
        (ofertas_novex, err_novex) = resultados[14]

        advertencias = [
            err
            for err in (
                err_kemik,
                err_pacifiko,
                err_super,
                err_max,
                err_tecnofacil,
                err_cemaco,
                err_walmart,
                err_oficiales,
                err_pricesmart,
                err_intelaf,
                err_lacuracao,
                err_claro,
                err_istore,
                err_epa,
                err_novex,
            )
            if err is not None
        ]

        unificadas_brutas = [
            *ofertas_istore,
            *ofertas_epa,
            *ofertas_novex,
            *ofertas_kemik,
            *ofertas_pacifiko,
            *ofertas_super,
            *ofertas_max,
            *ofertas_tecnofacil,
            *ofertas_cemaco,
            *ofertas_walmart,
            *ofertas_oficiales,
            *ofertas_pricesmart,
            *ofertas_intelaf,
            *ofertas_lacuracao,
            *ofertas_claro,
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
                "extraidos_istore": len(ofertas_istore),
                "extraidos_epa": len(ofertas_epa),
                "extraidos_novex": len(ofertas_novex),
                "extraidos_kemik": len(ofertas_kemik),
                "extraidos_pacifiko": len(ofertas_pacifiko),
                "extraidos_la_torre": len(ofertas_super),
                "extraidos_tiendas_max": len(ofertas_max),
                "extraidos_tecno_facil": len(ofertas_tecnofacil),
                "extraidos_cemaco": len(ofertas_cemaco),
                "extraidos_walmart": len(ofertas_walmart),
                "extraidos_oficiales": len(ofertas_oficiales),
                "extraidos_pricesmart": len(ofertas_pricesmart),
                "extraidos_intelaf": len(ofertas_intelaf),
                "extraidos_la_curacao": len(ofertas_lacuracao),
                "extraidos_tienda_claro": len(ofertas_claro),
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
