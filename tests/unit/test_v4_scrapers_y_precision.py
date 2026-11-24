"""
Pruebas unitarias para tecHunter GT v4.0:
  - Scrapers de iStore (ishop.gt), EPA Guatemala (gt.epaenlinea.com) y Novex (novex.com.gt)
  - Motor de Precisión de Modelos y Clasificación por Gamas (`filtro_relevancia.py`)
  - Clasificación de categorías UI para ferretería y cómputo
"""
from __future__ import annotations

from decimal import Decimal

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    coincide_modelo_especifico,
    es_oferta_relevante,
    extraer_especificaciones_y_gama,
    filtrar_ofertas_relevantes,
)
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.epa_scraper import EpaScraper
from radar_ofertas.infrastructure.scrapers.istore_scraper import IStoreScraper
from radar_ofertas.infrastructure.scrapers.novex_scraper import NovexScraper


def test_istore_scraper_parsea_shopify_json() -> None:
    scraper = IStoreScraper()
    payload = {
        "resources": {
            "results": {
                "products": [
                    {
                        "title": 'Apple MacBook Air 13" Chip M2 8GB RAM 256GB SSD Medianoche',
                        "price": "8999.00",
                        "url": "/products/macbook-air-13-chip-m2-256gb?variant=123",
                        "image": "//ishop.gt/cdn/shop/files/macbook_m2.jpg",
                    }
                ]
            }
        }
    }
    ofertas = scraper.parsear_respuesta_shopify(payload)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "iStore"
    assert ofertas[0].precio_gtq == Decimal("8999.00")
    assert ofertas[0].url == "https://ishop.gt/products/macbook-air-13-chip-m2-256gb"
    assert ofertas[0].imagen_url.startswith("https://ishop.gt/")


def test_epa_scraper_parsea_graphql_magento() -> None:
    scraper = EpaScraper()
    payload = {
        "data": {
            "products": {
                "items": [
                    {
                        "name": "TALADRO PERCUTOR BOSCH GSB20-2 800W 1/2\"",
                        "sku": "0835558",
                        "url_key": "0835558-taladro-percutor-bosch-gsb20-2",
                        "small_image": {
                            "url": "https://gt.epaenlinea.com/media/catalog/product/b/o/bosch.jpg"
                        },
                        "price_range": {
                            "minimum_price": {
                                "final_price": {"value": 1999, "currency": "GTQ"}
                            }
                        },
                    }
                ]
            }
        }
    }
    ofertas = scraper.parsear_respuesta_graphql(payload)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "EPA"
    assert ofertas[0].precio_gtq == Decimal("1999.00")
    assert ofertas[0].url == "https://gt.epaenlinea.com/0835558-taladro-percutor-bosch-gsb20-2.html"


def test_novex_scraper_parsea_html_real() -> None:
    scraper = NovexScraper()
    html = """
    <div class="product-item">
      <h3><a href="/catalogo/29140/taladro_dewalt_dcd776.html">Taladro Percutor Inalámbrico DeWalt DCD776C2 20V Max</a></h3>
      <span class="price">Q 1,395.00</span>
      <img src="/images/items/large/29140.jpg" />
    </div>
    """
    ofertas_html = scraper.parsear_html(html)
    assert len(ofertas_html) == 1
    assert ofertas_html[0].tienda == "Novex"
    assert ofertas_html[0].precio_gtq == Decimal("1395.00")
    assert ofertas_html[0].url == "https://www.novex.com.gt/catalogo/29140/taladro_dewalt_dcd776.html"


def test_motor_precision_modelos_evita_comparacion_dispareja() -> None:
    ofertas_mixtas = [
        OfertaLocal(
            titulo='Apple MacBook Air 13" Chip M2 8GB RAM 256GB SSD',
            precio_gtq=Decimal("8999.00"),
            url="https://ishop.gt/products/macbook-air-m2",
            imagen_url="https://ishop.gt/img/m2.jpg",
            tienda="iStore",
        ),
        OfertaLocal(
            titulo='HP Stream 14" Intel Celeron N4020 4GB RAM 64GB eMMC',
            precio_gtq=Decimal("1899.00"),
            url="https://www.pacifiko.com/hp-stream-14",
            imagen_url="https://www.pacifiko.com/img/hp.jpg",
            tienda="Pacifiko",
        ),
        OfertaLocal(
            titulo='Funda Protectora Estuche para MacBook Air M2 13"',
            precio_gtq=Decimal("199.00"),
            url="https://www.kemik.gt/funda-macbook",
            imagen_url="https://www.kemik.gt/img/funda.jpg",
            tienda="Kemik",
        ),
    ]

    filtradas = filtrar_ofertas_relevantes(ofertas_mixtas, "MacBook Air M2")
    assert len(filtradas) == 1
    assert filtradas[0].tienda == "iStore"
    assert "MacBook Air" in filtradas[0].titulo

    # También para herramientas específicas: "Taladro DeWalt DCD776"
    assert coincide_modelo_especifico(
        "Taladro Percutor Inalámbrico DeWalt DCD776C2 20V Max", "Taladro DeWalt DCD776"
    )
    assert not es_oferta_relevante(
        "Taladro Rotomartillo Pretul 500W 3/8 Básica", "Taladro DeWalt DCD776"
    )


def test_clasificacion_gamas_y_chips_especificaciones() -> None:
    alta = extraer_especificaciones_y_gama(
        "Laptop ASUS TUF Gaming A15 Ryzen 7 7735HS RTX 4050 16GB RAM 512GB SSD",
        precio_gtq=7999.0,
        categoria_ui="computo",
    )
    assert alta["gama"] == "Profesional · Alta Gama"
    assert alta["gama_slug"] == "profesional"
    assert any("RYZEN 7" in c.upper() for c in alta["chips_especificaciones"])
    assert any("RTX 4050" in c.upper() for c in alta["chips_especificaciones"])

    entrada = extraer_especificaciones_y_gama(
        "Laptop HP Stream 14 Intel Celeron N4020 4GB RAM 64GB",
        precio_gtq=1899.0,
        categoria_ui="computo",
    )
    assert entrada["gama"] == "Entrada · Básica"
    assert entrada["gama_slug"] == "entrada"

    media = extraer_especificaciones_y_gama(
        "Laptop Lenovo IdeaPad Slim 3 Intel Core i5-12450H 8GB RAM 512GB SSD",
        precio_gtq=4499.0,
        categoria_ui="computo",
    )
    assert media["gama"] == "Media · Productividad"
    assert media["gama_slug"] == "media"


def test_clasificar_categoria_ui_reconoce_epa_y_novex() -> None:
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Taladro Percutor Bosch GSB 20-2 800W", "epa"
        )
        == "herramientas"
    )
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Hidrolavadora Karcher K2 1600 PSI", "novex"
        )
        == "herramientas"
    )
