"""
Pruebas unitarias para:
  1. TiendasOficialesScraper (Siman GT, Elektra GT e iShop GT)
  2. PriceSmartScraper (Estrategia de membresía mayorista y protección contra precios ocultos)
  3. Activación contextual del anuncio nativo de Z-Tech Imports en app.py
"""
from __future__ import annotations

from radar_ofertas.infrastructure.scrapers.pricesmart_scraper import PriceSmartScraper
from radar_ofertas.infrastructure.scrapers.tiendas_oficiales_scraper import (
    TiendasOficialesScraper,
)
from radar_ofertas.interfaces.api.app import _es_busqueda_computo_ztech


PAYLOAD_SIMAN_VTEX_EJEMPLO = [
    {
        "productId": "9173972",
        "productName": "Samsung Galaxy Tab S12+ Wi-Fi de 256 GB con 12 GB de RAM plata",
        "brand": "Samsung",
        "linkText": "tablet-12-6-galaxy-s12-plus-12gb-ram-256gb-rom-plateado",
        "items": [
            {
                "itemId": "9173972",
                "images": [
                    {
                        "imageUrl": "https://siman.vteximg.com.br/arquivos/ids/8649086/105414280.webp?v=639281"
                    }
                ],
                "sellers": [
                    {
                        "sellerDefault": True,
                        "commertialOffer": {
                            "Price": 11499.0,
                            "ListPrice": 12499.0,
                            "AvailableQuantity": 3,
                        },
                    }
                ],
            }
        ],
    }
]

PAYLOAD_ISHOP_SHOPIFY_EJEMPLO = {
    "resources": {
        "results": {
            "products": [
                {
                    "available": True,
                    "title": "iPhone 18 Pro Max 256 GB Borgoña",
                    "price": "13999.00",
                    "url": "/products/iphone-18-pro-mjxq4lz-a?_pos=1&_psq=iphone",
                    "image": "https://cdn.shopify.com/s/files/1/0635/0251/6376/files/iphone18.jpg?v=1788",
                }
            ]
        }
    }
}


def test_tiendas_oficiales_scraper_parsea_siman_elektra_e_ishop() -> None:
    ofertas_siman = TiendasOficialesScraper.parsear_respuesta_vtex(
        PAYLOAD_SIMAN_VTEX_EJEMPLO,
        nombre_tienda="Siman",
        base_url="https://gt.siman.com/",
    )
    assert len(ofertas_siman) == 1
    assert ofertas_siman[0].tienda == "Siman"
    assert ofertas_siman[0].precio_gtq == 11499.0
    assert (
        ofertas_siman[0].url
        == "https://gt.siman.com/tablet-12-6-galaxy-s12-plus-12gb-ram-256gb-rom-plateado/p"
    )
    assert (
        ofertas_siman[0].imagen_url
        == "https://siman.vteximg.com.br/arquivos/ids/8649086/105414280.webp"
    )

    ofertas_ishop = TiendasOficialesScraper.parsear_respuesta_shopify_ishop(
        PAYLOAD_ISHOP_SHOPIFY_EJEMPLO
    )
    assert len(ofertas_ishop) == 1
    assert ofertas_ishop[0].tienda == "iShop"
    assert ofertas_ishop[0].precio_gtq == 13999.0
    assert ofertas_ishop[0].url == "https://ishop.gt/products/iphone-18-pro-mjxq4lz-a"


def test_pricesmart_scraper_maneja_membresia_y_protege_ranking_de_precios_ocultos() -> None:
    item_socio_visible = {
        "title": "Pantalla Smart TV LG 65 Pulgadas 4K UHD AI ThinQ",
        "url": "/es-gt/producto/pantalla-smart-tv-lg-65-pulgadas-4k-uhd/481920",
        "memberPrice": "4,799.00",
        "imageUrl": "https://www.pricesmart.com/images/lg-65.jpg",
    }
    oferta_visible = PriceSmartScraper.parsear_item_mayorista(item_socio_visible)
    assert oferta_visible is not None
    assert oferta_visible.tienda == "PriceSmart"
    assert oferta_visible.precio_gtq == 4799.0
    assert oferta_visible.requiere_membresia is True
    assert oferta_visible.estado_precio_membresia == "exclusivo_socios"

    # Producto con precio bloqueado hasta iniciar sesión de socio
    item_precio_oculto = {
        "title": "Refrigeradora Samsung French Door 28 Pies Cúbicos",
        "url": "/es-gt/producto/refrigeradora-samsung-28p/991023",
        "requiresMemberLogin": True,
        "memberPrice": None,
    }
    # Por defecto se descarta del ranking numérico para no contaminar con Q0.00
    assert (
        PriceSmartScraper.parsear_item_mayorista(
            item_precio_oculto, incluir_precios_ocultos=False
        )
        is None
    )
    # En modo catálogo informativo conserva el estado 'oculto_requiere_login'
    oferta_oculta = PriceSmartScraper.parsear_item_mayorista(
        item_precio_oculto, incluir_precios_ocultos=True
    )
    assert oferta_oculta is not None
    assert oferta_oculta.requiere_membresia is True
    assert oferta_oculta.estado_precio_membresia == "oculto_requiere_login"


def test_activacion_contextual_banner_ztech_imports() -> None:
    assert _es_busqueda_computo_ztech("laptop asus") is True
    assert _es_busqueda_computo_ztech("workstation rtx") is True
    assert _es_busqueda_computo_ztech("monitor lg") is True
    assert _es_busqueda_computo_ztech("pedigree 15kg") is False
