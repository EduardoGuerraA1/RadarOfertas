"""
Punto de entrada principal (Orquestador) de tecHunter / RadarOfertas.
Coordina la ejecución de scrapers y la persistencia en Neon DB (PostgreSQL)
respetando la arquitectura limpia (Clean Architecture).
"""
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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tecHunter.main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orquestador principal de tecHunter (Scraping + Persistencia en Neon DB)."
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="volante logitech",
        help="Término de búsqueda (por defecto: 'volante logitech')",
    )
    parser.add_argument(
        "--categoria",
        default="tecnologia",
        help="Slug de la categoría en base de datos (por defecto: 'tecnologia')",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=10,
        help="Cantidad máxima de ofertas a mostrar en consola (por defecto: 10)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Abre navegador Chromium visible (headless=False) para resolver Cloudflare en entorno local",
    )
    parser.add_argument(
        "--sin-db",
        action="store_true",
        help="Solo ejecuta el scraper e imprime en consola sin insertar en Neon DB",
    )
    return parser.parse_args()


def mostrar_ofertas_en_consola(
    termino: str, ofertas: list[OfertaLocal], limite: int
) -> None:
    print("\n" + "=" * 80)
    print(f" RESULTADOS DE TECHUNTER - KEMIK | Búsqueda: '{termino}'")
    print(f" Total de ofertas encontradas: {len(ofertas)} (mostrando {min(limite, len(ofertas))})")
    print("=" * 80)

    for i, oferta in enumerate(ofertas[:limite], 1):
        print(f"[{i}] {oferta.titulo}")
        print(f"    Tienda : {oferta.tienda}")
        print(f"    Precio : Q{oferta.precio_gtq:,.2f}")
        print(f"    URL    : {oferta.url}")
        print(f"    Imagen : {oferta.imagen_url}")
        print("-" * 80)


def guardar_en_base_de_datos(
    ofertas: list[OfertaLocal], categoria_slug: str
) -> None:
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        logger.warning(
            "DATABASE_URL no está definida en .env. Se omitió la inserción en Neon DB."
        )
        return

    logger.info("Conectando a Neon DB para registrar %d ofertas...", len(ofertas))
    repositorio = PostgresOfertaRepository(database_url=database_url)
    insertados = repositorio.guardar_ofertas(ofertas, categoria_slug=categoria_slug)
    print(
        f"\n✅ Base de Datos (Neon): Se insertaron {insertados} registros en "
        "`productos` e `historial_precios`."
    )


async def ejecutar_orquestador() -> None:
    args = parse_args()
    termino = args.query

    logger.info("Iniciando orquestador tecHunter para el término: '%s'", termino)
    scraper = KemikScraper(headless=not args.headed)

    try:
        ofertas = await scraper.buscar_producto(termino)

        if not ofertas:
            print(
                f"\n⚠️ No se encontraron ofertas para '{termino}'.\n"
                "Si estás ejecutando en tu máquina local y Cloudflare bloquea el modo headless, "
                "prueba ejecutando:\n"
                f'  python main.py "{termino}" --headed'
            )
            return

        mostrar_ofertas_en_consola(termino, ofertas, args.limite)

        if not args.sin_db:
            guardar_en_base_de_datos(ofertas, args.categoria)

    except Exception as error:
        logger.error("Error crítico en el orquestador: %s", error)
        raise


if __name__ == "__main__":
    asyncio.run(ejecutar_orquestador())