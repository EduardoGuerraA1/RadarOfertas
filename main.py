"""
Punto de entrada principal (Orquestador) de tecHunter / RadarOfertas.
Coordina la ejecución concurrente de los scrapers locales:
  - Kemik (kemik.gt)
  - Pacifiko (pacifiko.com)
  - Supermercados La Torre (latorre.com.gt)
Compara los precios en Quetzales (GTQ) y persiste de forma unificada en Neon DB
respetando la arquitectura limpia (Clean Architecture).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Asegurar que Python encuentre el paquete dentro de src/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper

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
    return "tecnologia"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Orquestador principal de tecHunter "
            "(Kemik + Pacifiko + Supermercados La Torre -> Comparación + Neon DB)."
        )
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="pedigree",
        help="Término de búsqueda (ej. 'pedigree', 'purina', 'volante logitech')",
    )
    parser.add_argument(
        "--categoria",
        default="",
        help="Slug de la categoría en base de datos (se autodetecta 'mascotas' o 'tecnologia' si se omite)",
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
        help="Abre navegador Chromium visible (headless=False) en Kemik para resolver Cloudflare en entorno local",
    )
    parser.add_argument(
        "--simular",
        action="store_true",
        help="Ejecuta La Torre y Pacifiko en vivo + respaldo JSON-LD de Kemik si Cloudflare bloquea IPs cloud",
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
    {
        "@type": "Product",
        "name": "Logitech Driving Force Shifter Palanca de Cambios para Volante G29 y G920",
        "sku": "LOG-941-000119",
        "url": "https://www.kemik.gt/producto/logitech-driving-force-shifter-palanca-cambios-g29-g920",
        "image": "/images/catalog/log-shifter-g29.jpg",
        "offers": [
            {
                "@type": "Offer",
                "priceCurrency": "GTQ",
                "price": 649.00,
            }
        ],
    },
]


def mostrar_comparativa_en_consola(
    termino: str,
    ofertas_kemik: list[OfertaLocal],
    ofertas_pacifiko: list[OfertaLocal],
    ofertas_super: list[OfertaLocal],
    limite: int,
) -> list[OfertaLocal]:
    """
    Ordena y muestra las ofertas de todas las tiendas de menor a mayor precio
    y retorna la lista unificada ordenada.
    """
    todas_ordenadas = sorted(
        [*ofertas_kemik, *ofertas_pacifiko, *ofertas_super],
        key=lambda o: o.precio_gtq,
    )

    print("\n" + "=" * 88)
    print(f" RADAR COMPARADOR TECHUNTER (GT) | Búsqueda: '{termino}'")
    print(
        f" Resumen por tienda: Kemik ({len(ofertas_kemik)}) | "
        f"Pacifiko ({len(ofertas_pacifiko)}) | "
        f"La Torre ({len(ofertas_super)}) | "
        f"Total ({len(todas_ordenadas)})"
    )
    print("=" * 88)

    if not todas_ordenadas:
        print("No se encontraron ofertas en ninguna tienda.")
        return []

    mejor_oferta = todas_ordenadas[0]
    print(
        f"🏆 MEJOR PRECIO DETECTADO: Q{mejor_oferta.precio_gtq:,.2f} en [{mejor_oferta.tienda}] "
        f"-> {mejor_oferta.titulo}"
    )
    print("=" * 88)

    for i, oferta in enumerate(todas_ordenadas[:limite], 1):
        etiqueta = " ⭐ [MEJOR PRECIO]" if i == 1 else ""
        print(f"[{i}] [{oferta.tienda.upper()}]{etiqueta} {oferta.titulo}")
        print(f"    Precio : Q{oferta.precio_gtq:,.2f}")
        print(f"    URL    : {oferta.url}")
        print(f"    Imagen : {oferta.imagen_url}")
        print("-" * 88)

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

    logger.info(
        "Conectando a Neon DB para registrar %d ofertas unificadas (categoría='%s')...",
        len(ofertas),
        categoria_slug,
    )
    repositorio = PostgresOfertaRepository(database_url=database_url)
    insertados = repositorio.guardar_ofertas(ofertas, categoria_slug=categoria_slug)
    print(
        f"\n✅ Base de Datos (Neon): Se inyectaron {insertados} ofertas unificadas en "
        f"`productos` e `historial_precios` (categoría: {categoria_slug})."
    )


async def ejecutar_orquestador() -> None:
    args = parse_args()
    termino = args.query
    categoria = _detectar_categoria(termino, args.categoria)

    logger.info(
        "Iniciando orquestador multicapa tecHunter para el término: '%s' (categoría: '%s')",
        termino,
        categoria,
    )
    kemik_scraper = KemikScraper(headless=not args.headed)
    pacifiko_scraper = PacifikoScraper()
    super_scraper = SuperScraper()

    try:
        if args.simular:
            logger.info(
                "Modo --simular activo: consultando La Torre y Pacifiko en vivo..."
            )
            ofertas_pacifiko, ofertas_super = await asyncio.gather(
                pacifiko_scraper.buscar_producto(termino),
                super_scraper.buscar_producto(termino),
            )
            ofertas_kemik = (
                [
                    oferta
                    for item in PAYLOAD_SIMULADO_KEMIK
                    if (oferta := kemik_scraper._mapear_producto_ld_a_oferta(item))
                    is not None
                ]
                if "logitech" in termino.lower() or "volante" in termino.lower()
                else []
            )
        else:
            ofertas_kemik, ofertas_pacifiko, ofertas_super = await asyncio.gather(
                kemik_scraper.buscar_producto(termino),
                pacifiko_scraper.buscar_producto(termino),
                super_scraper.buscar_producto(termino),
            )

        ofertas_unificadas = mostrar_comparativa_en_consola(
            termino, ofertas_kemik, ofertas_pacifiko, ofertas_super, args.limite
        )

        if not ofertas_unificadas:
            print(
                f"\n⚠️ No se encontraron ofertas para '{termino}' en ninguna tienda.\n"
                f'💡 Prueba ejecutando: python main.py "{termino}" --headed'
            )
            return

        if not args.sin_db:
            guardar_en_base_de_datos(ofertas_unificadas, categoria)

    except Exception as error:
        logger.error("Error crítico en el orquestador: %s", error)
        raise


if __name__ == "__main__":
    asyncio.run(ejecutar_orquestador())