"""
Pruebas unitarias para MaxScraper (Tiendas Max / Tecno Fácil - Magento 2 GraphQL y HTML/JSON-LD).
"""
from __future__ import annotations

from radar_ofertas.infrastructure.scrapers.max_scraper import MaxScraper


ITEMS_GRAPHQL_MAX = [
    {
        "name": "Samsung Galaxy Watch 7 40mm Bluetooth Smartwatch Verde",
        "sku": "SM-L300NZGAAXO",
        "url_key": "samsung-galaxy-watch-7-40mm-bluetooth-smartwatch-verde",
        "url_suffix": ".html",
        "small_image": {
            "url": "https://www.max.com.gt/media/catalog/product/s/m/sm-l300nzgaaxo_1.jpg"
        },
        "price_range": {
            "minimum_price": {
                "final_price": {"value": 2199.00, "currency": "GTQ"}
            }
        },
    },
    {
        "name": "Volante Logitech G29 Driving Force para PlayStation y PC",
        "sku": "941-000110",
        "url_key": "volante-logitech-g29-driving-force-playstation-pc",
        "url_suffix": ".html",
        "small_image": {
            "url": "/media/catalog/product/9/4/941-000110_1.jpg"
        },
        "price_range": {
            "minimum_price": {
                "final_price": {"value": 2799.00, "currency": "GTQ"}
            }
        },
    },
]

HTML_MAGENTO_MAX = """
<div class="products wrapper grid products-grid">
  <li class="item product product-item">
    <div class="product-item-info">
      <a class="product-item-link" href="/samsung-galaxy-watch-fe-40mm-negro.html?___SID=U">
        Samsung Galaxy Watch FE 40mm Negro
      </a>
      <img class="product-image-photo" data-src="/media/catalog/product/g/w/gw-fe.jpg" />
      <span class="price-wrapper" data-price-amount="1499.00">
        <span class="price">Q1,499.00</span>
      </span>
    </div>
  </li>
</div>
"""


def test_max_scraper_mapea_graphql_correctamente() -> None:
    scraper = MaxScraper(usar_playwright_fallback=False)
    ofertas = scraper.parsear_respuesta_graphql(
        {"data": {"products": {"items": ITEMS_GRAPHQL_MAX}}}
    )

    assert len(ofertas) == 2
    assert ofertas[0].tienda == "Tiendas Max"
    assert ofertas[0].titulo == "Samsung Galaxy Watch 7 40mm Bluetooth Smartwatch Verde"
    assert ofertas[0].precio_gtq == 2199.00
    assert (
        ofertas[0].url
        == "https://www.max.com.gt/samsung-galaxy-watch-7-40mm-bluetooth-smartwatch-verde.html"
    )
    assert (
        ofertas[1].imagen_url
        == "https://www.max.com.gt/media/catalog/product/9/4/941-000110_1.jpg"
    )


def test_max_scraper_extrae_html_magento_y_limpia_urls() -> None:
    scraper = MaxScraper(usar_playwright_fallback=False)
    ofertas = scraper.parsear_html_busqueda(HTML_MAGENTO_MAX)

    assert len(ofertas) == 1
    oferta = ofertas[0]
    assert oferta.tienda == "Tiendas Max"
    assert oferta.titulo == "Samsung Galaxy Watch FE 40mm Negro"
    assert oferta.precio_gtq == 1499.00
    assert oferta.url == "https://www.max.com.gt/samsung-galaxy-watch-fe-40mm-negro.html"
    assert oferta.imagen_url == "https://www.max.com.gt/media/catalog/product/g/w/gw-fe.jpg"
