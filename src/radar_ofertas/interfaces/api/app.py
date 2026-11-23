"""
Capa de Interfaces (Web / API) de tecHunter GT v5.2 con FastAPI + Jinja2.

Arquitectura v5.2 (Especialistas de Cómputo, Periféricos/Cámaras y Worker 3x/Día):
  - 24 tiendas activas en Guatemala (incorporando Rech, Click Guatemala y Tera junto a Tigo, Office Depot y Tropigas).
  - Worker en Segundo Plano configurado para sincronizar al menos 3 veces al día (cada 8 horas / 480 min).
  - El buscador web (`GET /` y `GET /api/ofertas`) lee ÚNICAMENTE de Neon DB en milisegundos.
  - Cálculo de ahorro 100% verificado por producto idéntico/comparable (con tope lógico comercial).
  - Analítica Web blindada: descarta automáticamente pings de mantenimiento/bots (UptimeRobot, etc.)
    y oculta el panel de métricas al público general, habilitándolo únicamente mediante
    `?admin=secreto` (o `ADMIN_ANALYTICS_TOKEN`) o cookie de sesión de administrador.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from radar_ofertas.application.use_cases.analitica_web import (
    COOKIE_ADMIN_NAME,
    es_token_admin_valido,
    gestor_analitica,
)
from radar_ofertas.application.use_cases.worker_precarga import (
    ESTADO_WORKER_PRECARGA,
    INTERVALO_MINUTOS_DEFAULT,
    calcular_intervalo_sincronizacion_minutos,
    iniciar_worker_periodico_background,
    precargar_termino_semilla,
)
from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.seed_data import (
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
)
from radar_ofertas.domain.services.filtro_relevancia import (
    extraer_especificaciones_y_gama,
    filtrar_dicts_relevantes,
    resolver_url_saliente_segura,
    son_productos_estrictamente_identicos,
)
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.click_scraper import ClickScraper
from radar_ofertas.infrastructure.scrapers.epa_scraper import EpaScraper
from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
from radar_ofertas.infrastructure.scrapers.istore_scraper import IStoreScraper
from radar_ofertas.infrastructure.scrapers.novex_scraper import NovexScraper
from radar_ofertas.infrastructure.scrapers.officedepot_scraper import OfficeDepotScraper
from radar_ofertas.infrastructure.scrapers.rech_scraper import RechScraper
from radar_ofertas.infrastructure.scrapers.tecnofacil_scraper import TecnoFacilScraper
from radar_ofertas.infrastructure.scrapers.tera_scraper import TeraScraper
from radar_ofertas.infrastructure.scrapers.tigo_scraper import TigoScraper
from radar_ofertas.infrastructure.scrapers.tropigas_scraper import TropigasScraper

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    Mantiene el proceso web de Render 100% ligero y dedicado a lecturas en milisegundos
    sobre Neon DB (evitando 502 / lags por contención de CPU/RAM).
    El Worker Periódico en segundo plano está configurado para ejecutarse al menos 3 veces al día
    (cada 8 horas = 480 minutos por defecto) cuando se habilita con `ENABLE_BACKGROUND_WORKER=true`.
    """
    habilitar_worker = (
        os.environ.get("ENABLE_BACKGROUND_WORKER", "false").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    tarea_worker: asyncio.Task | None = None
    if habilitar_worker and (os.environ.get("DATABASE_URL") or "").strip():
        intervalo_configurado = calcular_intervalo_sincronizacion_minutos(
            int(os.environ.get("WORKER_INTERVAL_MINUTES", str(INTERVALO_MINUTOS_DEFAULT)))
        )
        tarea_worker = asyncio.create_task(
            iniciar_worker_periodico_background(
                intervalo_minutos=intervalo_configurado,
                muestra_por_categoria=int(
                    os.environ.get("WORKER_SAMPLE_PER_CATEGORY", "3")
                ),
                retardo_inicial_s=45.0,
            )
        )
        logger.info(
            "Worker en segundo plano de tecHunter GT v5.2 programado exitosamente (cada %s min / >=3x al día).",
            intervalo_configurado,
        )
    try:
        yield
    finally:
        if tarea_worker and not tarea_worker.done():
            tarea_worker.cancel()


app = FastAPI(
    title="tecHunter GT v5.2 — Comparador Instantáneo en Guatemala",
    description=(
        "Plataforma de comparación de precios en milisegundos respaldada por Neon DB "
        "(24 tiendas activas en Guatemala incluyendo Rech, Click Guatemala y Tera; Worker 3x/Día)."
    ),
    version="5.2.0",
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
    "mousepad",
    "diadema",
    "headset",
    "webcam",
    "keychron",
    "hyperx",
    "redragon",
    "corsair",
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

STOPWORDS_COMPARACION: frozenset[str] = frozenset(
    {
        "de",
        "la",
        "el",
        "en",
        "con",
        "para",
        "por",
        "y",
        "o",
        "un",
        "una",
        "del",
        "los",
        "las",
        "al",
        "color",
        "negro",
        "blanco",
        "gris",
        "azul",
        "rojo",
        "verde",
        "plata",
        "plateado",
        "gt",
        "guatemala",
        "oficial",
        "nuevo",
        "nueva",
        "pulgadas",
        "plg",
    }
)

# Scrapers de las olas v5.1 y v5.2 100% activos en producción
SCRAPERS_NUEVOS_ACTIVOS_V5_1: dict[str, Any] = {
    "tienda-tigo": TigoScraper(habilitado=True),
    "office-depot": OfficeDepotScraper(habilitado=True),
    "tropigas": TropigasScraper(habilitado=True),
}

SCRAPERS_NUEVOS_ACTIVOS_V5_2: dict[str, Any] = {
    "rech": RechScraper(habilitado=True),
    "click": ClickScraper(habilitado=True),
    "tera": TeraScraper(habilitado=True),
}


class EscanearRequest(BaseModel):
    query: str = ""
    categoria: str = ""


class AnalyticsEventRequest(BaseModel):
    tipo: str = "custom"
    query: str = ""
    tienda: str = ""
    titulo: str = ""
    url_destino: str = ""
    precio_gtq: float = 0.0


def _verificar_acceso_admin(request: Request, admin_param: str = "") -> bool:
    """
    Determina si la petición actual cuenta con privilegios de administrador
    vía query string (`?admin=secreto`), cookie de sesión (`techunter_admin`)
    o cabecera HTTP (`X-Admin-Token`).
    """
    if es_token_admin_valido(admin_param):
        return True
    cookie_val = request.cookies.get(COOKIE_ADMIN_NAME)
    if es_token_admin_valido(cookie_val):
        return True
    header_val = request.headers.get("X-Admin-Token")
    if es_token_admin_valido(header_val):
        return True
    return False


def _es_busqueda_computo_ztech(query: str, categoria_ui: str = "") -> bool:
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


def _extraer_tokens_comparables(titulo: str) -> set[str]:
    limpio = (titulo or "").lower().strip()
    descompuesto = unicodedata.normalize("NFD", limpio)
    sin_tildes = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    tokens = re.findall(r"[a-z0-9]+", sin_tildes)
    return {
        t
        for t in tokens
        if len(t) >= 2 and t not in STOPWORDS_COMPARACION
    }


def _son_mismo_articulo_comparable(
    oferta_base: dict[str, Any], oferta_candidata: dict[str, Any]
) -> bool:
    """
    Delega en `son_productos_estrictamente_identicos` para garantizar que solo
    se comparen y agrupen productos estrictamente idénticos (mismo tipo de producto,
    misma marca, mismo código de modelo y misma variante clave como talla/capacidad).
    """
    return son_productos_estrictamente_identicos(oferta_base, oferta_candidata)


def _calcular_ahorro_preciso(
    ofertas: list[dict[str, Any]], query: str = ""
) -> float:
    if not ofertas:
        return 0.0

    for o in ofertas:
        o["ahorro_gtq"] = 0.0

    if len(ofertas) == 1:
        return 0.0

    for oferta in ofertas:
        precio_actual = float(oferta.get("precio_gtq") or 0.0)
        if precio_actual <= 0:
            continue

        precios_mismo_articulo = [
            float(cand.get("precio_gtq") or 0.0)
            for cand in ofertas
            if cand is not oferta
            and _son_mismo_articulo_comparable(oferta, cand)
            and float(cand.get("precio_gtq") or 0.0) > precio_actual
        ]

        if precios_mismo_articulo:
            diferencia_bruta = max(precios_mismo_articulo) - precio_actual
            tope_logico = min(precio_actual * 0.55, 2500.00)
            oferta["ahorro_gtq"] = round(min(diferencia_bruta, tope_logico), 2)

    ahorro_mejor_oferta = float(ofertas[0].get("ahorro_gtq") or 0.0)
    if ahorro_mejor_oferta > 0:
        return ahorro_mejor_oferta

    ahorros_verificados = [
        float(o.get("ahorro_gtq") or 0.0)
        for o in ofertas
        if float(o.get("ahorro_gtq") or 0.0) > 0
    ]
    if ahorros_verificados:
        return round(max(ahorros_verificados), 2)

    return 0.0


def _calcular_resumen(
    ofertas: list[dict[str, Any]], query: str = ""
) -> dict[str, Any]:
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
            "total_rech": 0,
            "total_click": 0,
            "total_tera": 0,
            "total_office_depot": 0,
            "total_tecno_facil": 0,
            "total_la_curacao": 0,
            "total_tropigas": 0,
            "total_tienda_claro": 0,
            "total_tienda_tigo": 0,
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

    ahorro = _calcular_ahorro_preciso(ofertas, query=query)
    mejor = ofertas[0]
    total_istore = sum(
        1 for o in ofertas if o["tienda_slug"] in {"istore", "ishop"}
    )

    return {
        "total": len(ofertas),
        "total_istore": total_istore,
        "total_epa": sum(1 for o in ofertas if o["tienda_slug"] == "epa"),
        "total_novex": sum(1 for o in ofertas if o["tienda_slug"] == "novex"),
        "total_intelaf": sum(1 for o in ofertas if o["tienda_slug"] == "intelaf"),
        "total_rech": sum(1 for o in ofertas if o["tienda_slug"] == "rech"),
        "total_click": sum(1 for o in ofertas if o["tienda_slug"] == "click"),
        "total_tera": sum(1 for o in ofertas if o["tienda_slug"] == "tera"),
        "total_office_depot": sum(
            1 for o in ofertas if o["tienda_slug"] == "office-depot"
        ),
        "total_tecno_facil": sum(
            1 for o in ofertas if o["tienda_slug"] in {"tecno-facil", "tecnofacil"}
        ),
        "total_la_curacao": sum(
            1 for o in ofertas if o["tienda_slug"] == "la-curacao"
        ),
        "total_tropigas": sum(
            1 for o in ofertas if o["tienda_slug"] == "tropigas"
        ),
        "total_tienda_claro": sum(
            1 for o in ofertas if o["tienda_slug"] == "tienda-claro"
        ),
        "total_tienda_tigo": sum(
            1 for o in ofertas if o["tienda_slug"] == "tienda-tigo"
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


# Caché en memoria de alta velocidad para lecturas de Neon DB (evita lags y 502 bajo picos de tráfico)
_CACHE_LECTURA_NEON: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}
CACHE_NEON_TTL_SEGUNDOS: float = 45.0

_CATALOGOS_MEMORIA_INSTANTANEA: tuple[Any, ...] = (
    RechScraper(simular=True),
    ClickScraper(simular=True),
    TeraScraper(simular=True),
    TigoScraper(simular=True),
    OfficeDepotScraper(simular=True),
    TropigasScraper(simular=True),
    IStoreScraper(),
    EpaScraper(),
    NovexScraper(),
    IntelafScraper(usar_playwright_fallback=False),
    TecnoFacilScraper(usar_playwright_fallback=False),
)


def _buscar_respaldo_rapido_en_memoria(
    query: str = "", tienda_slug: str = "", categoria_ui: str = ""
) -> list[dict[str, Any]]:
    """
    Respaldo instantáneo en memoria (<2 ms, cero llamadas de red) cuando un término de búsqueda
    aún no se encuentra precargado en Neon DB o durante un arranque en frío.
    """
    termino = (query or "").strip()
    if not termino:
        termino = (
            "iphone samsung macbook laptop refrigeradora taladro impresora "
            "teclado diadema mousepad webcam tapo ezviz"
        )

    tienda_limpia = (tienda_slug or "").strip().lower()
    if tienda_limpia == "tecnofacil":
        tienda_limpia = "tecno-facil"
    categoria_limpia = (categoria_ui or "").strip().lower()

    ofertas_locales: list[OfertaLocal] = []
    for scraper in _CATALOGOS_MEMORIA_INSTANTANEA:
        buscador = getattr(scraper, "buscar_en_catalogo_verificado", None)
        if callable(buscador):
            try:
                ofertas_locales.extend(buscador(termino))
            except Exception:
                continue

    resultados: list[dict[str, Any]] = []
    urls_vistas: set[str] = set()
    for idx, oferta in enumerate(ofertas_locales, 1):
        if oferta.url in urls_vistas or float(oferta.precio_gtq) <= 0:
            continue
        urls_vistas.add(oferta.url)

        slug_t = PostgresOfertaRepository._normalizar_slug_tienda(oferta.tienda)
        if tienda_limpia:
            if tienda_limpia in {"istore", "ishop"} and slug_t not in {"istore", "ishop"}:
                continue
            elif tienda_limpia not in {"istore", "ishop"} and slug_t != tienda_limpia:
                continue

        precio_float = float(oferta.precio_gtq)
        costo_envio = 0.0 if precio_float >= 1500.0 else 35.0
        costo_real = round(precio_float + costo_envio, 2)
        cat_item = PostgresOfertaRepository.clasificar_categoria_ui(
            oferta.titulo, slug_t
        )
        meta_modelo = extraer_especificaciones_y_gama(
            oferta.titulo, precio_gtq=precio_float, categoria_ui=cat_item
        )
        marca_str = (
            PostgresOfertaRepository._inferir_marca(oferta.titulo) or "Oficial GT"
        )
        resultados.append(
            {
                "producto_id": f"mem-{slug_t}-{idx}",
                "titulo": oferta.titulo,
                "marca": marca_str,
                "imagen_url": str(oferta.imagen_url or ""),
                "tienda_slug": slug_t,
                "tienda": oferta.tienda,
                "precio_gtq": precio_float,
                "costo_envio_gtq": costo_envio,
                "costo_real_gtq": costo_real,
                "url": resolver_url_saliente_segura(oferta.url, slug_t, oferta.titulo),
                "scraped_at": "Respaldo Instantáneo GT",
                "categoria_ui": cat_item,
                "requiere_membresia": slug_t == "pricesmart",
                "gama": meta_modelo["gama"],
                "gama_slug": meta_modelo["gama_slug"],
                "chips_especificaciones": meta_modelo["chips_especificaciones"],
                "clave_modelo": meta_modelo["clave_modelo"],
            }
        )

    filtrados = filtrar_dicts_relevantes(resultados, query)
    if categoria_limpia in {
        "computo",
        "smartphones",
        "hogar",
        "herramientas",
        "super-mascotas",
    }:
        filtrados = [
            o for o in filtrados if o.get("categoria_ui") == categoria_limpia
        ]
    filtrados.sort(
        key=lambda o: (o.get("precio_gtq", 0.0), o.get("costo_real_gtq", 0.0))
    )
    return filtrados


async def _consultar_ofertas_con_resiliencia(
    query: str = "",
    tienda_slug: str = "",
    categoria_ui: str = "",
    timeout_s: float = 5.5,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Lee exclusivamente desde Neon DB en milisegundos con caché TTL en memoria (45s) y timeout
    estricto (`5.5s`) para evitar cualquier bloqueo o error 502 en Render.
    Si el término buscado no está precargado en Neon DB, activa en <2 ms el respaldo rápido
    en memoria sin congelar la interfaz.
    """
    clave_cache = (
        (query or "").strip().lower(),
        (tienda_slug or "").strip().lower(),
        (categoria_ui or "").strip().lower(),
    )
    ahora = time.monotonic()
    entrada_cache = _CACHE_LECTURA_NEON.get(clave_cache)
    if entrada_cache and (ahora - entrada_cache[0]) < CACHE_NEON_TTL_SEGUNDOS:
        return [dict(item) for item in entrada_cache[1]], False, None

    error_db: str | None = None
    ofertas_neon: list[dict[str, Any]] = []
    try:
        repositorio = PostgresOfertaRepository()
        ofertas_neon = await asyncio.wait_for(
            asyncio.to_thread(
                repositorio.buscar_ofertas_comparadas,
                query,
                tienda_slug,
                categoria_ui,
            ),
            timeout=timeout_s,
        )
        if ofertas_neon:
            _CACHE_LECTURA_NEON[clave_cache] = (
                ahora,
                [dict(item) for item in ofertas_neon],
            )
            return ofertas_neon, False, None
    except asyncio.TimeoutError:
        logger.warning(
            "Timeout preventivo (%.1fs) leyendo Neon DB para '%s'; activando respaldo instantáneo.",
            timeout_s,
            query,
        )
    except Exception as error:
        logger.error("Error consultando Neon DB: %s", error)
        error_db = str(error)

    ofertas_respaldo = _buscar_respaldo_rapido_en_memoria(
        query=query, tienda_slug=tienda_slug, categoria_ui=categoria_ui
    )
    return ofertas_respaldo, bool(ofertas_respaldo), error_db


async def _ejecutar_scraper_seguro(
    scraper: Any, nombre_tienda: str, termino: str, timeout_s: float = 12.0
) -> tuple[list[OfertaLocal], str | None]:
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
    """Endpoint de salud para el balanceador de Render y UptimeRobot."""
    return {"status": "ok", "service": "tecHunter", "version": "5.2.0"}


@app.post("/api/analytics/event")
async def api_registrar_evento_analitica(
    request: Request,
    payload: AnalyticsEventRequest,
) -> dict[str, Any]:
    """
    Registra un evento de analítica web descartando automáticamente bots y monitores.
    """
    ua = request.headers.get("user-agent", "")
    evento = gestor_analitica.registrar_evento(
        tipo=payload.tipo,
        query=payload.query,
        tienda=payload.tienda,
        titulo=payload.titulo,
        url_destino=payload.url_destino,
        precio_gtq=payload.precio_gtq,
        user_agent=ua,
    )
    return {
        "status": "ok" if evento is not None else "ignored_bot",
        "evento": evento,
    }


@app.get("/api/analytics/summary")
async def api_resumen_analitica(
    request: Request,
    admin: str = Query(
        default="",
        description="Token secreto de administrador (ej. ?admin=secreto) o cookie de sesión",
    ),
) -> dict[str, Any]:
    """
    Endpoint PRIVADO de analítica web.
    Solo accesible para el administrador mediante `?admin=secreto` (o `ADMIN_ANALYTICS_TOKEN`),
    cookie `techunter_admin` o cabecera `X-Admin-Token`.
    """
    if not _verificar_acceso_admin(request, admin_param=admin):
        raise HTTPException(
            status_code=403,
            detail="Acceso privado restringido al administrador de tecHunter GT.",
        )
    return gestor_analitica.obtener_resumen()


@app.get("/api/seed-status")
async def api_seed_status(
    request: Request,
    admin: str = Query(default=""),
) -> dict[str, Any]:
    """
    Expone el estado del Worker de Precarga Inteligente (3x/día) y el cruce de las 24 tiendas activas.
    Las métricas de analítica solo se incluyen si la petición está autenticada como admin.
    """
    cruce = cruzar_matriz_tiendas_y_prioridades()
    todos_seed = obtener_todos_los_productos_semilla()
    es_admin = _verificar_acceso_admin(request, admin_param=admin)
    respuesta: dict[str, Any] = {
        "version": "5.2.0",
        "total_productos_semilla": len(todos_seed),
        "categorias_semilla": {
            cat: len(items) for cat, items in seed_list_guatemala.items()
        },
        "scrapers_recien_activados_v5_1": list(SCRAPERS_NUEVOS_ACTIVOS_V5_1.keys()),
        "scrapers_recien_activados_v5_2": list(SCRAPERS_NUEVOS_ACTIVOS_V5_2.keys()),
        "worker_precarga": ESTADO_WORKER_PRECARGA,
        "matriz_tiendas": cruce,
    }
    if es_admin:
        respuesta["analitica_resumen"] = gestor_analitica.obtener_resumen(top_n=10)
    return respuesta


@app.get("/", response_class=HTMLResponse)
async def vista_comparador(
    request: Request,
    q: str = Query(default="", description="Término de búsqueda en Neon DB"),
    tienda: str = Query(
        default="",
        description="Filtro por tienda: istore, epa, novex, intelaf, office-depot, tecno-facil, la-curacao, tropigas, tienda-claro, tienda-tigo, pricesmart, siman, elektra, walmart, paiz, maxi-despensa, cemaco, pacifiko, la-torre, tiendas-max o kemik",
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
    admin: str = Query(
        default="",
        description="Token privado de administrador para visualizar métricas (ej. ?admin=secreto)",
    ),
) -> HTMLResponse:
    cat_limpia = cat.strip().lower()
    ua = request.headers.get("user-agent", "")
    gestor_analitica.registrar_visita(
        query=q,
        categoria=cat_limpia,
        tienda=tienda.strip().lower(),
        user_agent=ua,
        metodo_http=request.method,
    )

    quiere_logout_admin = admin.strip().lower() in {"logout", "off", "0"}
    es_admin = (
        False
        if quiere_logout_admin
        else _verificar_acceso_admin(request, admin_param=admin)
    )

    ofertas_totales, respaldo_rapido_activo, error_db = (
        await _consultar_ofertas_con_resiliencia(
            query=q, tienda_slug=tienda, categoria_ui=""
        )
    )

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

    resumen = _calcular_resumen(ofertas_totales, query=q)
    resumen_visible = _calcular_resumen(ofertas_visibles, query=q)
    resumen["mejor_oferta"] = resumen_visible["mejor_oferta"]
    resumen["ahorro_maximo_gtq"] = resumen_visible["ahorro_maximo_gtq"]

    destacar_ztech = _es_busqueda_computo_ztech(q, cat_limpia)
    cruce_tiendas = cruzar_matriz_tiendas_y_prioridades()
    ga_measurement_id = os.environ.get("GA_MEASUREMENT_ID", "").strip()

    response = templates.TemplateResponse(
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
            "respaldo_rapido_activo": respaldo_rapido_activo,
            "destacar_ztech": destacar_ztech,
            "siguientes_tiendas": cruce_tiendas["siguientes_3_alta_prioridad"],
            "es_admin": es_admin,
            "visitas_totales": gestor_analitica.visitas_totales if es_admin else None,
            "clics_salientes_totales": gestor_analitica.clics_salientes_totales
            if es_admin
            else None,
            "pings_bots_ignorados": gestor_analitica.pings_bots_ignorados
            if es_admin
            else None,
            "ga_measurement_id": ga_measurement_id,
            "error_db": error_db,
        },
    )

    if quiere_logout_admin:
        response.delete_cookie(COOKIE_ADMIN_NAME)
    elif es_token_admin_valido(admin):
        response.set_cookie(
            key=COOKIE_ADMIN_NAME,
            value=admin.strip(),
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
        )
    return response


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
        ofertas, respaldo_rapido_activo, _ = await _consultar_ofertas_con_resiliencia(
            query=q, tienda_slug=tienda, categoria_ui=cat
        )
        gama_limpia = gama.strip().lower()
        if gama_limpia in {"profesional", "media", "entrada"}:
            ofertas = [o for o in ofertas if o.get("gama_slug") == gama_limpia]
        return {
            "query": q,
            "tienda": tienda,
            "categoria_ui": cat,
            "gama": gama_limpia,
            "respaldo_rapido_activo": respaldo_rapido_activo,
            "destacar_ztech": _es_busqueda_computo_ztech(q, cat),
            "resumen": _calcular_resumen(ofertas, query=q),
            "ofertas": ofertas,
        }
    except Exception as error:
        logger.error("Error en GET /api/ofertas: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/escanear")
async def api_escanear_en_vivo(payload: EscanearRequest) -> JSONResponse:
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
            "modo": "background_worker_v5_1",
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
