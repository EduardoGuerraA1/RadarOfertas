"""
Punto de entrada principal (Orquestador) de tecHunter GT v5.2 / RadarOfertas.
Coordina la ejecución concurrente de los 24 scrapers locales en Guatemala:
  - Rech Guatemala (rech.com.gt)
  - Click Guatemala (click.gt)
  - Tera Guatemala (tera.gt)
  - Tienda Tigo GT (tienda.tigo.com.gt)
  - Office Depot GT (officedepot.com.gt)
  - Almacenes Tropigas GT (almacenestropigas.com/guatemala)
  - iStore / iShop GT (ishop.gt)
  - EPA Guatemala (gt.epaenlinea.com)
  - Novex Guatemala (novex.com.gt)
  - Intelaf (intelaf.com)
  - Tecno Fácil (tecnofacil.com.gt)
  - La Curacao (lacuracaonline.com/guatemala)
  - Tienda Claro GT (claro.com.gt)
  - PriceSmart GT (pricesmart.com/en-GT)
  - Tiendas Oficiales (Siman, Elektra, iShop)
  - Grupo Walmart (walmart.com.gt, paiz.com.gt y maxidespensa.com.gt)
  - Cemaco (cemaco.com)
  - Pacifiko (pacifiko.com)
  - Supermercados La Torre (latorre.com.gt)
  - Tiendas Max (max.com.gt)
  - Kemik (kemik.gt)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    extraer_especificaciones_y_gama,
    filtrar_ofertas_relevantes,
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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tecHunter.main")


def _detectar_categoria(query: str, categoria_arg: str) -> str:
    if categoria_arg.strip():
        return categoria_arg.strip().lower()
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
        "tapo",
        "ezviz",
        "camara de seguridad",
    )
    if any(p in q_lower for p in palabras_hogar):
        return "hogar"

    return "tecnologia"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Orquestador principal de tecHunter GT v5.2 "
            "(24 tiendas activas incluyendo Rech, Click Guatemala, Tera, Tigo, Office Depot y Tropigas)."
        )
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="laptop",
        help="Término de búsqueda (ej. 'macbook air m2', 'taladro', 'iphone 16', 'refrigeradora mabe')",
    )
    parser.add_argument(
        "--categoria",
        default="",
        help="Slug de la categoría en base de datos (se autodetecta 'hogar', 'mascotas' o 'tecnologia' si se omite)",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=10,
        help="Cantidad máxima de ofertas a mostrar en el ranking comparativo (por defecto: 10)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre navegador Chromium visible (headless=False) en Kemik/Max para resolver Cloudflare en entorno local",
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Ejecuta todas las APIs y scrapers en vivo sin requerir navegador Chromium para Kemik/Max",
    )
    parser.add_argument(
        "--sin-db",
        action="store_true",
        help="Solo ejecuta los scrapers y compara en consola sin insertar en Neon DB",
    )
    return parser.parse_args()


PAYLOAD_SIMULADO_KEMIK = [
    {
        "@type": "Product",
        "name": "Logitech G29 Driving Force Volante de Carreras y Pedales para PS5, PS4 y PC",
        "sku": "LOG-941-000110",
        "url": "/producto/logitech-g29-driving-force-volante-de-carreras-ps5-ps4-pc",
        "image": [
            "https://images.kemik.gt/2023/08/LOG-941-000110-1.jpg",
            "https://images.kemik.gt/2023/08/LOG-941-000110-2.jpg",
        ],
        "offers": {
            "@type": "Offer",
            "priceCurrency": "GTQ",
            "price": "2699.00",
            "availability": "https://schema.org/InStock",
        },
    },
]

PAYLOAD_SIMULADO_MAX_GRAPHQL = [
    {
        "name": "Volante Logitech G29 Driving Force para PlayStation y PC",
        "sku": "941-000110",
        "url_key": "volante-logitech-g29-driving-force-playstation-pc",
        "url_suffix": ".html",
        "small_image": {
            "url": "https://www.max.com.gt/media/catalog/product/9/4/941-000110_1.jpg"
        },
        "price_range": {
            "minimum_price": {
                "final_price": {"value": 2799.00, "currency": "GTQ"}
            }
        },
    },
]


def mostrar_comparativa_en_consola(
    termino: str,
    listas_ofertas: list[list[OfertaLocal]],
    limite: int,
) -> list[OfertaLocal]:
    brutas = [oferta for sublista in listas_ofertas for oferta in sublista]
    relevantes = [
        o
        for o in filtrar_ofertas_relevantes(brutas, termino)
        if o.precio_gtq > 0 and o.estado_precio_membresia != "oculto_requiere_login"
    ]
    todas_ordenadas = sorted(relevantes, key=lambda o: o.precio_gtq)

    print("\n" + "=" * 110)
    print(f" RADAR COMPARADOR TECHUNTER GT v5.2 (24 TIENDAS) | Búsqueda: '{termino}'")
    print(
        f" Resumen: "
        f"Rech ({sum(1 for o in todas_ordenadas if o.tienda == 'Rech')}) | "
        f"Click ({sum(1 for o in todas_ordenadas if o.tienda == 'Click Guatemala')}) | "
        f"Tera ({sum(1 for o in todas_ordenadas if o.tienda == 'Tera')}) | "
        f"Tigo ({sum(1 for o in todas_ordenadas if o.tienda == 'Tienda Tigo')}) | "
        f"Office Depot ({sum(1 for o in todas_ordenadas if o.tienda == 'Office Depot')}) | "
        f"Tropigas ({sum(1 for o in todas_ordenadas if o.tienda == 'Tropigas')}) | "
        f"EPA ({sum(1 for o in todas_ordenadas if o.tienda == 'EPA')}) | "
        f"Novex ({sum(1 for o in todas_ordenadas if o.tienda == 'Novex')}) | "
        f"iStore ({sum(1 for o in todas_ordenadas if o.tienda in {'iStore', 'iShop'})}) | "
        f"Intelaf ({sum(1 for o in todas_ordenadas if o.tienda == 'Intelaf')}) | "
        f"La Curacao ({sum(1 for o in todas_ordenadas if o.tienda == 'La Curacao')}) | "
        f"Claro ({sum(1 for o in todas_ordenadas if o.tienda == 'Tienda Claro')}) | "
        f"Tecno Fácil ({sum(1 for o in todas_ordenadas if o.tienda == 'Tecno Fácil')}) | "
        f"PriceSmart ({sum(1 for o in todas_ordenadas if o.tienda == 'PriceSmart')}) | "
        f"Total ({len(todas_ordenadas)} de {len(brutas)} brutas)"
    )
    print("=" * 110)

    if not todas_ordenadas:
        print("No se encontraron ofertas principales en ninguna tienda.")
        return []

    mejor_oferta = todas_ordenadas[0]
    print(
        f"🏆 MEJOR PRECIO DETECTADO: Q{mejor_oferta.precio_gtq:,.2f} en [{mejor_oferta.tienda}] "
        f"-> {mejor_oferta.titulo}"
    )
    print("=" * 110)

    for i, oferta in enumerate(todas_ordenadas[:limite], 1):
        meta = extraer_especificaciones_y_gama(oferta.titulo, float(oferta.precio_gtq))
        etiqueta = " ⭐ [MEJOR PRECIO]" if i == 1 else ""
        nota_socio = " [SOCIO PRICESMART]" if oferta.requiere_membresia else ""
        chips_str = " · ".join(meta["chips_especificaciones"])
        print(
            f"[{i}] [{oferta.tienda.upper()}] [{meta['gama']}]{nota_socio}{etiqueta} {oferta.titulo}"
        )
        print(f"    Precio : Q{oferta.precio_gtq:,.2f} | Specs: {chips_str}")
        print(f"    URL    : {oferta.url}")
        print("-" * 110)

    return todas_ordenadas


def guardar_en_base_de_datos(
    ofertas: list[OfertaLocal], categoria_slug: str
) -> None:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        logger.warning(
            "DATABASE_URL no está definida en .env. Se omitió la inserción en Neon DB."
        )
        return

    repositorio = PostgresOfertaRepository(database_url=database_url)
    insertados = repositorio.guardar_ofertas(ofertas, categoria_slug=categoria_slug)
    print(
        f"\n✅ Base de Datos (Neon): {insertados} nuevos cambios de precio registrados en "
        f"`historial_precios` (de {len(ofertas)} productos evaluados, categoría: {categoria_slug})."
    )


async def ejecutar_orquestador() -> None:
    args = parse_args()
    termino = args.query
    categoria = _detectar_categoria(termino, args.categoria)

    kemik_scraper = KemikScraper(headless=not args.headed)
    pacifiko_scraper = PacifikoScraper()
    super_scraper = SuperScraper()
    max_scraper = MaxScraper(
        headless=not args.headed, usar_playwright_fallback=not args.simular
    )
    tecnofacil_scraper = TecnoFacilScraper(
        headless=not args.headed, usar_playwright_fallback=False
    )
    cemaco_scraper = CemacoScraper()
    walmart_scraper = WalmartScraper()
    oficiales_scraper = TiendasOficialesScraper()
    pricesmart_scraper = PriceSmartScraper()
    intelaf_scraper = IntelafScraper(headless=not args.headed)
    lacuracao_scraper = LaCuracaoScraper()
    claro_scraper = ClaroScraper()
    istore_scraper = IStoreScraper()
    epa_scraper = EpaScraper()
    novex_scraper = NovexScraper()
    tigo_scraper = TigoScraper(simular=args.simular)
    officedepot_scraper = OfficeDepotScraper(simular=args.simular)
    tropigas_scraper = TropigasScraper(simular=args.simular)
    rech_scraper = RechScraper(simular=args.simular)
    click_scraper = ClickScraper(simular=args.simular)
    tera_scraper = TeraScraper(simular=args.simular)
    guatemaladigital_scraper = GuatemalaDigitalScraper(simular=args.simular)

    scrapers_en_vivo = [
        guatemaladigital_scraper.buscar_producto(termino),
        pacifiko_scraper.buscar_producto(termino),
        super_scraper.buscar_producto(termino),
        tecnofacil_scraper.buscar_producto(termino),
        cemaco_scraper.buscar_producto(termino),
        walmart_scraper.buscar_producto(termino),
        oficiales_scraper.buscar_producto(termino),
        pricesmart_scraper.buscar_producto(termino),
        intelaf_scraper.buscar_producto(termino),
        lacuracao_scraper.buscar_producto(termino),
        claro_scraper.buscar_producto(termino),
        istore_scraper.buscar_producto(termino),
        epa_scraper.buscar_producto(termino),
        novex_scraper.buscar_producto(termino),
        tigo_scraper.buscar_producto(termino),
        officedepot_scraper.buscar_producto(termino),
        tropigas_scraper.buscar_producto(termino),
        rech_scraper.buscar_producto(termino),
        click_scraper.buscar_producto(termino),
        tera_scraper.buscar_producto(termino),
    ]

    if args.simular:
        listas = list(await asyncio.gather(*scrapers_en_vivo))
        termino_lower = termino.lower()
        ofertas_kemik = (
            [
                oferta
                for item in PAYLOAD_SIMULADO_KEMIK
                if (oferta := kemik_scraper._mapear_producto_ld_a_oferta(item))
                is not None
            ]
            if "logitech" in termino_lower or "volante" in termino_lower
            else []
        )
        items_max_filtrados = [
            item
            for item in PAYLOAD_SIMULADO_MAX_GRAPHQL
            if any(tok in item["name"].lower() for tok in termino_lower.split())
        ]
        ofertas_max = max_scraper.parsear_respuesta_graphql(
            {"data": {"products": {"items": items_max_filtrados}}}
        )
        listas.extend([ofertas_kemik, ofertas_max])
    else:
        listas = list(
            await asyncio.gather(
                kemik_scraper.buscar_producto(termino),
                max_scraper.buscar_producto(termino),
                *scrapers_en_vivo,
            )
        )

    ofertas_unificadas = mostrar_comparativa_en_consola(
        termino, listas, args.limite
    )
    if ofertas_unificadas and not args.sin_db:
        guardar_en_base_de_datos(ofertas_unificadas, categoria)


if __name__ == "__main__":
    asyncio.run(ejecutar_orquestador())