"""
Capa de Interfaces (Web / API) de tecHunter GT v5.3 con FastAPI + Jinja2.

Arquitectura v5.3 (App Shell <100ms, Skeleton Loading, CSS Estático y Búsqueda en Vivo Anti-502):
  - Ruta `GET /` desacoplada de consultas SQL bloqueantes: entrega el App Shell HTML con
    Skeleton Screens en milisegundos (<100 ms), mientras el frontend hidrata asíncronamente
    con `fetch` a `GET /api/ofertas` (paginado por defecto a los primeros 28 productos destacados).
  - TTL de `_CACHE_LECTURA_NEON` ampliado a 5 minutos (`300.0s`) con refresco preventivo
    en segundo plano (`stale-while-revalidate`) para absorber el cold start de Neon DB.
  - Endpoint ultraligero `GET /health` que responde `200 OK` sin tocar la base de datos.
  - Recursos estáticos optimizados servidos desde `/static/styles.css` sin `cdn.tailwindcss.com`.
  - Endpoint `POST /api/buscar-en-vivo` con `asyncio.wait` / `asyncio.gather` y timeout global
    estricto de 6 segundos, normalización con `resolver_url_saliente_segura` y persistencia
    automática en Neon DB.
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
from fastapi.staticfiles import StaticFiles
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
    es_oferta_relevante,
    extraer_especificaciones_y_gama,
    filtrar_dicts_relevantes,
    resolver_url_saliente_segura,
    son_productos_estrictamente_identicos,
)
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

logger = logging.getLogger("tecHunter.api")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """
    Mantiene el proceso web de Render 100% ligero y dedicado a entregas de App Shell en <100 ms
    y lecturas cacheadas sobre Neon DB (evitando 502 / lags por contención de CPU/RAM).
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
            "Worker en segundo plano de tecHunter GT v5.4 programado exitosamente (cada %s min / >=3x al día).",
            intervalo_configurado,
        )
    try:
        yield
    finally:
        if tarea_worker and not tarea_worker.done():
            tarea_worker.cancel()


app = FastAPI(
    title="tecHunter GT v5.4 — Comparador Instantáneo en Guatemala",
    description=(
        "Plataforma de comparación de precios con 25 tiendas activas (incluyendo Guatemala Digital), "
        "Arquitectura App Shell (<100 ms), caché TTL 5 min y búsqueda en vivo anti-502 (timeout 9s)."
    ),
    version="5.4.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
    "vivobook",
    "zenbook",
    "oled",
    "lenovo",
    "legion",
    "thinkpad",
    "hp",
    "dell",
    "alienware",
    "msi",
    "acer",
    "razer",
    "canon",
    "nikon",
    "sony",
    "alpha",
    "rebel",
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

# Scrapers de las olas v5.1, v5.2 y v5.4 100% activos en producción
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

SCRAPERS_NUEVOS_ACTIVOS_V5_4: dict[str, Any] = {
    "guatemaladigital": GuatemalaDigitalScraper(habilitado=True),
}

# Configuración de paginación y timeouts v5.4 (9 segundos asíncronos controlados)
PAGINACION_DESTACADOS_DEFAULT: int = 28
TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S: float = 9.0


class EscanearRequest(BaseModel):
    query: str = ""
    categoria: str = ""


class BuscarEnVivoRequest(BaseModel):
    query: str = ""
    tienda: str = ""
    categoria: str = ""
    gama: str = ""
    orden: str = "final"
    limit: int = PAGINACION_DESTACADOS_DEFAULT


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
            "total_guatemaladigital": 0,
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
        "total_guatemaladigital": sum(
            1 for o in ofertas if o["tienda_slug"] == "guatemaladigital"
        ),
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


# Caché en memoria v5.4: TTL de 5 minutos (300s) con refresco en segundo plano
# para absorber por completo cualquier cold start de Neon DB.
_CACHE_LECTURA_NEON: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}
CACHE_NEON_TTL_SEGUNDOS: float = 300.0
CACHE_NEON_REFRESH_BG_SEGUNDOS: float = 150.0
_TAREAS_REFRESCO_CACHE_EN_CURSO: set[tuple[str, str, str]] = set()

_CATALOGOS_MEMORIA_INSTANTANEA: tuple[Any, ...] = (
    GuatemalaDigitalScraper(simular=True),
    KemikScraper(usar_playwright=False, simular=True),
    PacifikoScraper(simular=True),
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


def _transformar_ofertas_locales_a_dicts(
    ofertas_locales: list[OfertaLocal],
    query: str = "",
    tienda_limpia: str = "",
    categoria_limpia: str = "",
    etiqueta_origen: str = "Respaldo Instantáneo GT",
) -> list[dict[str, Any]]:
    """Convierte una lista de `OfertaLocal` en diccionarios enriquecidos y filtrados por relevancia."""
    resultados: list[dict[str, Any]] = []
    vistas: set[tuple[str, str]] = set()
    for idx, oferta in enumerate(ofertas_locales, 1):
        precio_float = float(oferta.precio_gtq)
        if precio_float <= 0:
            continue
        slug_t = PostgresOfertaRepository._normalizar_slug_tienda(oferta.tienda)
        clave_unica = (slug_t, oferta.titulo.strip().lower())
        if clave_unica in vistas:
            continue
        vistas.add(clave_unica)

        if tienda_limpia:
            if tienda_limpia in {"istore", "ishop"} and slug_t not in {"istore", "ishop"}:
                continue
            elif tienda_limpia not in {"istore", "ishop"} and slug_t != tienda_limpia:
                continue

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
                "producto_id": f"live-{slug_t}-{idx}",
                "titulo": oferta.titulo,
                "marca": marca_str,
                "imagen_url": str(oferta.imagen_url or ""),
                "tienda_slug": slug_t,
                "tienda": oferta.tienda,
                "precio_gtq": precio_float,
                "costo_envio_gtq": costo_envio,
                "costo_real_gtq": costo_real,
                "url": resolver_url_saliente_segura(oferta.url, slug_t, oferta.titulo),
                "scraped_at": etiqueta_origen,
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

    return _transformar_ofertas_locales_a_dicts(
        ofertas_locales=ofertas_locales,
        query=query,
        tienda_limpia=tienda_limpia,
        categoria_limpia=categoria_limpia,
        etiqueta_origen="Respaldo Instantáneo GT",
    )


async def _refrescar_cache_neon_background(
    query: str,
    tienda_slug: str,
    categoria_ui: str,
    timeout_s: float = 5.5,
) -> None:
    """
    Refresca silenciosamente en segundo plano una entrada de `_CACHE_LECTURA_NEON`
    para absorber el cold start de Neon DB sin bloquear al usuario.
    """
    clave_cache = (
        (query or "").strip().lower(),
        (tienda_slug or "").strip().lower(),
        (categoria_ui or "").strip().lower(),
    )
    if clave_cache in _TAREAS_REFRESCO_CACHE_EN_CURSO:
        return
    _TAREAS_REFRESCO_CACHE_EN_CURSO.add(clave_cache)
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
                time.monotonic(),
                [dict(item) for item in ofertas_neon],
            )
    except Exception as exc:
        logger.debug("Refresco en segundo plano de caché Neon omitido: %s", exc)
    finally:
        _TAREAS_REFRESCO_CACHE_EN_CURSO.discard(clave_cache)


async def _consultar_ofertas_con_resiliencia(
    query: str = "",
    tienda_slug: str = "",
    categoria_ui: str = "",
    timeout_s: float = 5.5,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Lee desde Neon DB en milisegundos con caché TTL en memoria de 5 minutos (`300.0s`),
    refresco preventivo en segundo plano (`stale-while-revalidate`) y timeout estricto (`5.5s`).
    """
    clave_cache = (
        (query or "").strip().lower(),
        (tienda_slug or "").strip().lower(),
        (categoria_ui or "").strip().lower(),
    )
    ahora = time.monotonic()
    entrada_cache = _CACHE_LECTURA_NEON.get(clave_cache)
    if entrada_cache:
        edad_s = ahora - entrada_cache[0]
        if edad_s < CACHE_NEON_TTL_SEGUNDOS:
            if edad_s >= CACHE_NEON_REFRESH_BG_SEGUNDOS:
                asyncio.create_task(
                    _refrescar_cache_neon_background(
                        query, tienda_slug, categoria_ui, timeout_s=timeout_s
                    )
                )
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

    if query and query.strip():
        # Si es una búsqueda con término explícito y no está en Neon DB, verificar en catálogo
        # en memoria únicamente coincidencias estrictas. Si devuelve 0, el frontend activará
        # la búsqueda en vivo animada en POST /api/buscar-en-vivo.
        ofertas_respaldo = _buscar_respaldo_rapido_en_memoria(
            query=query, tienda_slug=tienda_slug, categoria_ui=categoria_ui
        )
        return ofertas_respaldo, bool(ofertas_respaldo), error_db

    ofertas_respaldo = _buscar_respaldo_rapido_en_memoria(
        query=query, tienda_slug=tienda_slug, categoria_ui=categoria_ui
    )
    return ofertas_respaldo, bool(ofertas_respaldo), error_db


def _construir_scrapers_busqueda_en_vivo(timeout_individual_s: int = 8) -> list[tuple[str, Any]]:
    """
    Construye la batería priorizada de scrapers activos en Guatemala para consultas en vivo paralelas.
    Prioriza los endpoints de búsqueda más rápidos y tolerantes (Guatemala Digital, Kemik HTTP,
    Pacifiko, Tiendas Max GraphQL/HTTP, Cemaco, Intelaf, Click Guatemala, Rech y Tera).
    """
    return [
        ("Guatemala Digital", GuatemalaDigitalScraper(timeout_s=timeout_individual_s)),
        (
            "Kemik",
            KemikScraper(
                headless=True,
                usar_playwright=False,
                timeout_s=timeout_individual_s,
            ),
        ),
        ("Pacifiko", PacifikoScraper(timeout_s=timeout_individual_s)),
        (
            "Tiendas Max",
            MaxScraper(
                headless=True,
                timeout_s=timeout_individual_s,
                usar_playwright_fallback=False,
            ),
        ),
        ("Cemaco", CemacoScraper(timeout_s=timeout_individual_s)),
        (
            "Intelaf",
            IntelafScraper(
                headless=True,
                timeout_s=timeout_individual_s,
                usar_playwright_fallback=False,
            ),
        ),
        ("Click Guatemala", ClickScraper(timeout_s=timeout_individual_s)),
        ("Rech", RechScraper(timeout_s=timeout_individual_s)),
        ("Tera", TeraScraper(timeout_s=timeout_individual_s)),
        ("Office Depot", OfficeDepotScraper(timeout_s=timeout_individual_s)),
        ("iStore", IStoreScraper(timeout_s=timeout_individual_s)),
        ("EPA", EpaScraper(timeout_s=timeout_individual_s)),
        ("Novex", NovexScraper(timeout_s=timeout_individual_s)),
        (
            "Tecno Fácil",
            TecnoFacilScraper(
                headless=True,
                timeout_s=timeout_individual_s,
                usar_playwright_fallback=False,
            ),
        ),
        ("La Curacao", LaCuracaoScraper(timeout_s=timeout_individual_s)),
        ("Tropigas", TropigasScraper(timeout_s=timeout_individual_s)),
        ("Tienda Claro", ClaroScraper(timeout_s=timeout_individual_s)),
        ("Tienda Tigo", TigoScraper(timeout_s=timeout_individual_s)),
        ("PriceSmart", PriceSmartScraper(timeout_s=timeout_individual_s)),
        ("Oficiales", TiendasOficialesScraper(timeout_s=timeout_individual_s)),
        ("Walmart Grupo", WalmartScraper(timeout_s=timeout_individual_s)),
        ("La Torre", SuperScraper()),
    ]


async def _ejecutar_scraper_seguro(
    scraper: Any, nombre_tienda: str, termino: str, timeout_s: float = 8.5
) -> tuple[list[OfertaLocal], str | None]:
    try:
        ofertas = await asyncio.wait_for(
            scraper.buscar_producto(termino), timeout=timeout_s
        )
        return list(ofertas or []), None
    except asyncio.TimeoutError:
        msg = f"{nombre_tienda}: tiempo de espera agotado ({timeout_s:.1f}s)"
        logger.debug(msg)
        return [], msg
    except Exception as error:
        msg = f"{nombre_tienda}: {error.__class__.__name__}"
        logger.debug("Fallo controlado en scraper %s: %s", nombre_tienda, error)
        return [], msg


async def ejecutar_busqueda_en_vivo_acotada(
    termino: str,
    scrapers: list[tuple[str, Any]] | None = None,
    timeout_global_s: float = TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S,
    persistir_en_db: bool = True,
    categoria_db: str = "",
    repositorio: PostgresOfertaRepository | None = None,
) -> dict[str, Any]:
    """
    Consulta en paralelo (`asyncio.wait` / `asyncio.gather`) los scrapers activos de Guatemala
    con un timeout global controlado de 9 segundos (`timeout_global_s=9.0`).
    Todo lo que responda dentro de ese límite:
      1. Es filtrado con `es_oferta_relevante`.
      2. Pasa por `resolver_url_saliente_segura` para garantizar cero enlaces 404/500.
      3. Se guarda automáticamente en Neon DB e invalida `_CACHE_LECTURA_NEON` para aparecer al instante.
      4. Si devuelve 0 resultados por bloqueos externos, guarda el término en la tabla
         `busquedas_pendientes` en Neon DB para que `worker_precarga.py` lo procese en su próxima corrida.
    """
    inicio = time.monotonic()
    termino_limpio = (termino or "").strip()
    if not termino_limpio:
        return {
            "ofertas_locales": [],
            "tiendas_con_resultados": [],
            "nuevas_guardadas_neon": 0,
            "registrada_en_busquedas_pendientes": False,
            "latencia_ms": 0.0,
        }

    lista_scrapers = scrapers if scrapers is not None else _construir_scrapers_busqueda_en_vivo(
        timeout_individual_s=max(1, int(timeout_global_s - 0.5))
    )
    timeout_por_tarea = max(0.2, timeout_global_s - 0.25)

    tareas = [
        asyncio.create_task(
            _ejecutar_scraper_seguro(
                scraper=sc,
                nombre_tienda=nombre,
                termino=termino_limpio,
                timeout_s=timeout_por_tarea,
            )
        )
        for nombre, sc in lista_scrapers
    ]

    ofertas_crudas: list[OfertaLocal] = []
    if tareas:
        terminadas, pendientes = await asyncio.wait(
            tareas, timeout=timeout_global_s
        )
        for tarea_pendiente in pendientes:
            tarea_pendiente.cancel()
        if pendientes:
            await asyncio.gather(*pendientes, return_exceptions=True)

        for tarea_lista in terminadas:
            try:
                lote, _ = tarea_lista.result()
                if lote:
                    ofertas_crudas.extend(lote)
            except Exception:
                continue

    ofertas_seguras: list[OfertaLocal] = []
    vistas: set[tuple[str, str]] = set()
    tiendas_con_resultados: set[str] = set()

    for oferta in ofertas_crudas:
        if float(oferta.precio_gtq) <= 0:
            continue
        if not es_oferta_relevante(oferta.titulo, termino_limpio):
            continue
        slug_t = PostgresOfertaRepository._normalizar_slug_tienda(oferta.tienda)
        url_segura = resolver_url_saliente_segura(
            oferta.url, slug_t, oferta.titulo
        )
        clave = (slug_t, oferta.titulo.strip().lower())
        if clave in vistas:
            continue
        vistas.add(clave)
        tiendas_con_resultados.add(oferta.tienda)
        ofertas_seguras.append(
            OfertaLocal(
                titulo=oferta.titulo,
                precio_gtq=oferta.precio_gtq,
                url=url_segura,
                imagen_url=oferta.imagen_url,
                tienda=oferta.tienda,
                requiere_membresia=getattr(oferta, "requiere_membresia", False),
                precio_regular_gtq=getattr(oferta, "precio_regular_gtq", None),
                etiqueta_membresia=getattr(oferta, "etiqueta_membresia", None),
                estado_precio_membresia=getattr(
                    oferta, "estado_precio_membresia", "publico"
                ),
            )
        )

    nuevas_guardadas = 0
    registrada_pendiente = False
    cat_destino = categoria_db or _detectar_categoria_por_query(termino_limpio)
    tiene_db = repositorio is not None or bool((os.environ.get("DATABASE_URL") or "").strip())

    if persistir_en_db and tiene_db:
        try:
            repo = repositorio or PostgresOfertaRepository()
            if ofertas_seguras:
                nuevas_guardadas = await asyncio.wait_for(
                    asyncio.to_thread(
                        repo.guardar_ofertas,
                        ofertas_seguras,
                        cat_destino,
                    ),
                    timeout=3.5,
                )
                _CACHE_LECTURA_NEON.clear()
            else:
                registrada_pendiente = await asyncio.wait_for(
                    asyncio.to_thread(
                        repo.registrar_busqueda_pendiente,
                        termino_limpio,
                        cat_destino,
                    ),
                    timeout=3.5,
                )
        except Exception as exc:
            logger.warning(
                "Persistencia en Neon DB tras búsqueda en vivo omitida (%s): %s",
                termino_limpio,
                exc,
            )

    latencia_ms = round((time.monotonic() - inicio) * 1000.0, 2)
    return {
        "ofertas_locales": ofertas_seguras,
        "tiendas_con_resultados": sorted(tiendas_con_resultados),
        "nuevas_guardadas_neon": nuevas_guardadas,
        "registrada_en_busquedas_pendientes": registrada_pendiente,
        "latencia_ms": latencia_ms,
    }


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Endpoint ultraligero de salud para Render y UptimeRobot.
    Responde 200 OK en <1 ms sin tocar Neon DB para mantener la instancia despierta.
    """
    return {
        "status": "ok",
        "service": "tecHunter GT",
        "version": "5.4.0",
        "db_touched": False,
    }


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
    Expone el estado del Worker de Precarga Inteligente (3x/día) y el cruce de las 25 tiendas activas.
    Las métricas de analítica solo se incluyen si la petición está autenticada como admin.
    """
    cruce = cruzar_matriz_tiendas_y_prioridades()
    todos_seed = obtener_todos_los_productos_semilla()
    es_admin = _verificar_acceso_admin(request, admin_param=admin)
    respuesta: dict[str, Any] = {
        "version": "5.4.0",
        "cache_neon_ttl_segundos": CACHE_NEON_TTL_SEGUNDOS,
        "total_productos_semilla": len(todos_seed),
        "categorias_semilla": {
            cat: len(items) for cat, items in seed_list_guatemala.items()
        },
        "scrapers_recien_activados_v5_1": list(SCRAPERS_NUEVOS_ACTIVOS_V5_1.keys()),
        "scrapers_recien_activados_v5_2": list(SCRAPERS_NUEVOS_ACTIVOS_V5_2.keys()),
        "scrapers_recien_activados_v5_4": list(SCRAPERS_NUEVOS_ACTIVOS_V5_4.keys()),
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
        description="Filtro por tienda: guatemaladigital, rech, click, tera, istore, epa, novex, intelaf, office-depot, tecno-facil, la-curacao, tropigas, tienda-claro, tienda-tigo, pricesmart, siman, elektra, walmart, paiz, maxi-despensa, cemaco, pacifiko, la-torre, tiendas-max o kemik",
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
    """
    Arquitectura App Shell + Skeleton Loading (v5.4):
    Desacopla la entrega del HTML inicial de la consulta SQL para responder en < 100 ms.
    Devuelve inmediatamente `index.html` con tarjetas esqueleto (Skeleton Screens), y el
    frontend invoca asíncronamente `GET /api/ofertas` (paginado a 28 productos destacados)
    para poblar los resultados sin riesgo de 502 en Render.
    """
    cat_limpia = cat.strip().lower()
    tienda_limpia = tienda.strip().lower()
    gama_limpia = gama.strip().lower()
    orden_limpio = orden.strip().lower()
    if orden_limpio not in {"final", "base"}:
        orden_limpio = "final"

    ua = request.headers.get("user-agent", "")
    gestor_analitica.registrar_visita(
        query=q,
        categoria=cat_limpia,
        tienda=tienda_limpia,
        user_agent=ua,
        metodo_http=request.method,
    )

    quiere_logout_admin = admin.strip().lower() in {"logout", "off", "0"}
    es_admin = (
        False
        if quiere_logout_admin
        else _verificar_acceso_admin(request, admin_param=admin)
    )

    clave_cache = (q.strip().lower(), tienda_limpia, "")
    entrada_caliente = _CACHE_LECTURA_NEON.get(clave_cache)
    if (
        entrada_caliente
        and (time.monotonic() - entrada_caliente[0]) < CACHE_NEON_TTL_SEGUNDOS
    ):
        resumen_inicial = _calcular_resumen(
            [dict(item) for item in entrada_caliente[1]], query=q
        )
    else:
        resumen_inicial = _calcular_resumen([], query=q)

    destacar_ztech = _es_busqueda_computo_ztech(q, cat_limpia)
    cruce_tiendas = cruzar_matriz_tiendas_y_prioridades()
    ga_measurement_id = os.environ.get("GA_MEASUREMENT_ID", "").strip()

    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "query": q,
            "tienda_activa": tienda_limpia,
            "categoria_activa": cat_limpia,
            "gama_activa": gama_limpia,
            "orden_activo": orden_limpio,
            "ofertas": [],
            "resumen": resumen_inicial,
            "app_shell_mode": True,
            "paginacion_limit": PAGINACION_DESTACADOS_DEFAULT,
            "respaldo_rapido_activo": False,
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
            "error_db": None,
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
    orden: str = Query(
        default="final",
        description="Criterio de ordenamiento: 'final' (con envío) o 'base' (lista)",
    ),
    limit: int = Query(
        default=PAGINACION_DESTACADOS_DEFAULT,
        ge=1,
        le=120,
        description="Límite paginado de productos destacados (por defecto 28, rango 24-32 recomendado)",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Desplazamiento para paginación",
    ),
) -> dict[str, Any]:
    """
    Endpoint asíncrono consumido por el App Shell (`index.html`) al terminar de pintar la pantalla.
    Devuelve el resumen global de contadores y las primeras `limit` (28) ofertas destacadas.
    """
    try:
        cat_limpia = cat.strip().lower()
        gama_limpia = gama.strip().lower()
        orden_limpio = orden.strip().lower()
        if orden_limpio not in {"final", "base"}:
            orden_limpio = "final"

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

        if gama_limpia in {"profesional", "media", "entrada"}:
            ofertas_visibles = [
                o for o in ofertas_visibles if o.get("gama_slug") == gama_limpia
            ]

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

        ofertas_paginadas = ofertas_visibles[offset : offset + limit]

        return {
            "version": "5.4.0",
            "query": q,
            "tienda": tienda,
            "categoria_ui": cat_limpia,
            "gama": gama_limpia,
            "orden": orden_limpio,
            "limit": limit,
            "offset": offset,
            "total_disponibles": len(ofertas_visibles),
            "respaldo_rapido_activo": respaldo_rapido_activo,
            "error_db": error_db,
            "destacar_ztech": _es_busqueda_computo_ztech(q, cat_limpia),
            "resumen": resumen,
            "ofertas": ofertas_paginadas,
        }
    except Exception as error:
        logger.error("Error en GET /api/ofertas: %s", error)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/buscar-en-vivo")
async def api_buscar_en_vivo(payload: BuscarEnVivoRequest) -> JSONResponse:
    """
    Búsqueda en Vivo Fuera de la DB con Timeout Asíncrono Controlado de 9 Segundos (Anti-502).
    Prioriza los scrapers más rápidos y tolerantes (Guatemala Digital, Kemik, Pacifiko, Max,
    Cemaco, Intelaf, Click, Rech, Tera), pasa cada resultado por `resolver_url_saliente_segura`,
    guarda automáticamente en Neon DB e invalida la caché de lectura.
    Si devuelve 0 resultados por bloqueos externos, registra el término en `busquedas_pendientes`.
    """
    termino = (payload.query or "").strip()
    if not termino:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "detail": "Debes indicar un término para buscar en vivo en tiendas.",
                "ofertas": [],
                "total": 0,
            },
        )

    tienda_limpia = (payload.tienda or "").strip().lower()
    if tienda_limpia == "tecnofacil":
        tienda_limpia = "tecno-facil"
    cat_limpia = (payload.categoria or "").strip().lower()
    gama_limpia = (payload.gama or "").strip().lower()
    orden_limpio = (payload.orden or "final").strip().lower()
    if orden_limpio not in {"final", "base"}:
        orden_limpio = "final"
    limit = max(1, min(int(payload.limit or PAGINACION_DESTACADOS_DEFAULT), 120))

    resultado_vivo = await ejecutar_busqueda_en_vivo_acotada(
        termino=termino,
        timeout_global_s=TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S,
        persistir_en_db=True,
    )

    ofertas_dicts = _transformar_ofertas_locales_a_dicts(
        ofertas_locales=resultado_vivo["ofertas_locales"],
        query=termino,
        tienda_limpia=tienda_limpia,
        categoria_limpia="",
        etiqueta_origen="En Vivo · Guardado en Neon DB",
    )

    if cat_limpia in {
        "computo",
        "smartphones",
        "hogar",
        "herramientas",
        "super-mascotas",
    }:
        ofertas_visibles = [
            o for o in ofertas_dicts if o.get("categoria_ui") == cat_limpia
        ]
    else:
        ofertas_visibles = list(ofertas_dicts)

    if gama_limpia in {"profesional", "media", "entrada"}:
        ofertas_visibles = [
            o for o in ofertas_visibles if o.get("gama_slug") == gama_limpia
        ]

    if orden_limpio == "base":
        ofertas_visibles.sort(
            key=lambda o: (o.get("precio_gtq", 0.0), o.get("costo_real_gtq", 0.0))
        )
    else:
        ofertas_visibles.sort(
            key=lambda o: (o.get("costo_real_gtq", 0.0), o.get("precio_gtq", 0.0))
        )

    resumen = _calcular_resumen(ofertas_dicts, query=termino)
    resumen_visible = _calcular_resumen(ofertas_visibles, query=termino)
    resumen["mejor_oferta"] = resumen_visible["mejor_oferta"]
    resumen["ahorro_maximo_gtq"] = resumen_visible["ahorro_maximo_gtq"]

    ofertas_paginadas = ofertas_visibles[:limit]

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "version": "5.4.0",
            "modo": "live_parallel_9s",
            "timeout_global_s": TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S,
            "query": termino,
            "tienda": tienda_limpia,
            "categoria_ui": cat_limpia,
            "gama": gama_limpia,
            "orden": orden_limpio,
            "latencia_ms": resultado_vivo["latencia_ms"],
            "nuevas_guardadas_neon": resultado_vivo["nuevas_guardadas_neon"],
            "registrada_en_busquedas_pendientes": resultado_vivo[
                "registrada_en_busquedas_pendientes"
            ],
            "tiendas_con_resultados": resultado_vivo["tiendas_con_resultados"],
            "total_disponibles": len(ofertas_visibles),
            "destacar_ztech": _es_busqueda_computo_ztech(termino, cat_limpia),
            "resumen": resumen,
            "ofertas": ofertas_paginadas,
        },
    )


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
            "modo": "background_worker_v5_4",
            "nuevas_ofertas": 0,
            "query": termino,
            "categoria": categoria,
            "detail": (
                "Tarea encolada en el Worker en Segundo Plano; "
                "usa POST /api/buscar-en-vivo para consulta interactiva en 9 segundos."
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
