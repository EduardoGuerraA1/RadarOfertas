"""
Pruebas unitarias para la expansión tecHunter v3.0:
  - IntelafScraper (intelaf.com — Hardware, componentes y laptops)
  - TecnoFacilScraper (tecnofacil.com.gt — Cuotas y electrodomésticos)
  - LaCuracaoScraper (lacuracaonline.com/guatemala — Adobe LiveSearch GraphQL)
  - ClaroScraper (claro.com.gt — Salesforce Commerce Cloud y Catálogo Prepago)
  - PriceSmartScraper (pricesmart.com/en-GT — Bloomreach Discovery API con etiqueta de socio)
  - Clasificador de Categorías Principales (`computo`, `smartphones`, `hogar`, `herramientas`, `super-mascotas`)
"""
from __future__ import annotations

from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)
from radar_ofertas.infrastructure.scrapers.claro_scraper import ClaroScraper
from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
from radar_ofertas.infrastructure.scrapers.lacuracao_scraper import LaCuracaoScraper
from radar_ofertas.infrastructure.scrapers.pricesmart_scraper import PriceSmartScraper
from radar_ofertas.infrastructure.scrapers.tecnofacil_scraper import TecnoFacilScraper


def test_intelaf_scraper_parsea_html_y_json_real() -> None:
    html_intelaf = """
    <div class="product-card">
      <a href="/precios_stock_detallado/asus-ux3405ca">
        <img src="/images/productos/gran/asus-ux3405ca.jpg" />
        <h3 class="descripcion">Notebook ASUS Zenbook UX3405CA Core Ultra 9 32GB 1TB SSD</h3>
      </a>
      <span class="precio-normal">Precio normal Q19,409</span>
      <span class="precio-promo">Promo ASUS Q17,798</span>
    </div>
    """
    ofertas_html = IntelafScraper.parsear_html_busqueda(html_intelaf)
    assert len(ofertas_html) == 1
    assert ofertas_html[0].tienda == "Intelaf"
    assert ofertas_html[0].precio_gtq == 17798.00
    assert (
        ofertas_html[0].url
        == "https://www.intelaf.com/precios_stock_detallado/asus-ux3405ca"
    )

    ofertas_json = IntelafScraper.parsear_json_productos(
        [
            {
                "codigo": "asus-ux3405ca",
                "titulo": "Notebook ASUS Zenbook UX3405CA Core Ultra 9 32GB 1TB SSD",
                "precio_efectivo_gtq": 17798.00,
                "url": "https://www.intelaf.com/precios_stock_detallado/asus-ux3405ca",
                "imagen_url": "https://www.intelaf.com/images/productos/gran/asus-ux3405ca.jpg",
            }
        ]
    )
    assert len(ofertas_json) == 1
    assert ofertas_json[0].tienda == "Intelaf"
    assert ofertas_json[0].precio_gtq == 17798.00


def test_tecnofacil_scraper_parsea_graphql_real() -> None:
    payload = {
        "data": {
            "products": {
                "items": [
                    {
                        "name": "Refrigeradora Samsung Top Mount 14 pies RT38DG6224S9",
                        "sku": "RT38DG6224S9",
                        "url_key": "refrigeradora-samsung-top-mount-13-pies-con-wifi-samsung-rt38dg6224s9",
                        "small_image": {
                            "url": "https://www.tecnofacil.com.gt/media/catalog/product/r/t/rt38dg6224s9_1.jpg"
                        },
                        "price_range": {
                            "minimum_price": {
                                "final_price": {"value": 5295.00, "currency": "GTQ"}
                            }
                        },
                    }
                ]
            }
        }
    }
    ofertas = TecnoFacilScraper.parsear_respuesta_graphql(payload)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "Tecno Fácil"
    assert ofertas[0].precio_gtq == 5295.00
    assert ofertas[0].url.startswith("https://www.tecnofacil.com.gt/")


def test_lacuracao_scraper_parsea_adobe_livesearch() -> None:
    payload_livesearch = {
        "data": {
            "productSearch": {
                "items": [
                    {
                        "product": {
                            "name": "Refrigeradora Samsung 11 Pies Top Mount RT31DG5124S9AP",
                            "sku": "465335500012",
                            "canonical_url": "//www.lacuracaonline.com/guatemala/refrigeradora-samsung-rt31dg5124s9ap/p",
                            "small_image": {
                                "url": "//www.lacuracaonline.com/media/catalog/product/6/0/6001040433_1.jpg"
                            },
                            "price_range": {
                                "minimum_price": {
                                    "final_price": {"value": 3198.0, "currency": "GTQ"}
                                }
                            },
                        },
                        "productView": {"inStock": True},
                    }
                ]
            }
        }
    }
    ofertas = LaCuracaoScraper.parsear_respuesta_livesearch(payload_livesearch)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "La Curacao"
    assert ofertas[0].precio_gtq == 3198.00
    assert (
        ofertas[0].url
        == "https://www.lacuracaonline.com/guatemala/refrigeradora-samsung-rt31dg5124s9ap/p"
    )
    assert ofertas[0].imagen_url.startswith("https://www.lacuracaonline.com/")


def test_claro_scraper_parsea_hits_sfcc_y_catalogo_prepago() -> None:
    hits_sfcc = [
        {
            "productId": "I02.7033.374",
            "productName": "Samsung Galaxy S25 Ultra",
            "hitType": "product",
            "price": 7009,
            "c_cen_storage": "256 GB",
            "c_slugUrl": "/personas/tiendaenlinea/product/telefonos/samsung-galaxy-s25-ultra/I02.7033.374.html",
            "image": {
                "link": "https://sf-api-prd.claro.com.gt/on/demandware.static/s25ultra.png"
            },
            "c_custom": {"id": "I02.7033.374", "salePrice": 6999, "listPrice": 7999},
        },
        # Hit tipo master con salePrice=0 (contenedor de plan) debe ignorarse
        {
            "productId": "I.7033.237",
            "productName": "Samsung Galaxy S25 Ultra",
            "hitType": "master",
            "price": 1210,
            "c_custom": {"salePrice": 0, "listPrice": 0},
        },
    ]
    ofertas = ClaroScraper.parsear_hits_sfcc(hits_sfcc)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "Tienda Claro"
    assert ofertas[0].precio_gtq == 6999.00
    assert "256 GB" in ofertas[0].titulo
    assert ofertas[0].url.startswith("https://www.claro.com.gt/personas/tiendaenlinea/")

    html_prepago = """
    <div class="c51_v2InfoCarText">
      <h3>Samsung A06</h3>
      <table><tr><td>128GB + 4GB RAM</td></tr></table>
      <div class="c51_v2InfoCarPrice">Precio <strong>Q699</strong> Antes <del>Q799</del></div>
      <div id="ImagenesComponenteC51"><img data-src="/portal/gt/samsung-a06.png" /></div>
    </div>
    """
    ofertas_prep = ClaroScraper.parsear_html_tienda_claro(html_prepago)
    assert len(ofertas_prep) == 1
    assert ofertas_prep[0].tienda == "Tienda Claro"
    assert ofertas_prep[0].precio_gtq == 699.00


def test_pricesmart_scraper_parsea_bloomreach_en_centavos_con_etiqueta_socio() -> None:
    payload_bloomreach = {
        "response": {
            "docs": [
                {
                    "pid": "521813",
                    "title": 'Dell 15.6" Pulgadas Portátil AMD Ryzen 7 16GB / 512GB',
                    "brand": "Dell",
                    "availability_GT": "true",
                    "inventory_GT": "in stock",
                    "price_GT": 579995.0,
                    "slug": "dell-15-6-pulgadas-laptop-amd-ryzen-7-521813",
                    "thumb_image": "https://d31f1ehqijlcua.cloudfront.net/laptop_521813.jpg",
                },
                {
                    "pid": "11077",
                    "title": "Producto Agotado en GT",
                    "availability_GT": "true",
                    "inventory_GT": "out of stock",
                    "price_GT": 16495.0,
                    "slug": "producto-agotado-11077",
                },
            ]
        }
    }
    ofertas = PriceSmartScraper.parsear_respuesta_bloomreach(payload_bloomreach)
    assert len(ofertas) == 1
    assert ofertas[0].tienda == "PriceSmart"
    assert ofertas[0].precio_gtq == 5799.95
    assert ofertas[0].requiere_membresia is True
    assert ofertas[0].estado_precio_membresia == "exclusivo_socios"
    assert (
        ofertas[0].url
        == "https://www.pricesmart.com/en-GT/product/dell-15-6-pulgadas-laptop-amd-ryzen-7-521813/521813"
    )


def test_clasificador_categorias_principales_v3() -> None:
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Notebook ASUS VivoBook Ryzen 5 16GB SSD", "intelaf"
        )
        == "computo"
    )
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Samsung Galaxy S25 Ultra 256GB", "tienda-claro"
        )
        == "smartphones"
    )
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Refrigeradora Mabe 18 Pies No Frost", "la-curacao"
        )
        == "hogar"
    )
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Taladro Rotomartillo Inalámbrico DeWalt 20V", "cemaco"
        )
        == "herramientas"
    )
    assert (
        PostgresOfertaRepository.clasificar_categoria_ui(
            "Alimento Para Perro Pedigree Adulto 20Kg", "la-torre"
        )
        == "super-mascotas"
    )
