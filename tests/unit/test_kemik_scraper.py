import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper


def test_mapear_producto_ld_con_url_relativa_y_lista_de_imagenes():
    producto_ld = {
        "@type": "Product",
        "name": "  Logitech G213 Prodigy Teclado Gaming  ",
        "url": "/producto/logitech-g213-prodigy",
        "image": [
            "https://images.kemik.gt/img1.jpg",
            "https://images.kemik.gt/img2.jpg",
        ],
        "offers": {"@type": "Offer", "price": "449.00", "priceCurrency": "GTQ"},
    }

    oferta = KemikScraper._mapear_producto_ld_a_oferta(producto_ld)

    assert isinstance(oferta, OfertaLocal)
    assert oferta.tienda == "Kemik"
    assert oferta.titulo == "Logitech G213 Prodigy Teclado Gaming"
    assert oferta.precio_gtq == 449.00
    assert oferta.url == "https://www.kemik.gt/producto/logitech-g213-prodigy"
    assert oferta.imagen_url == "https://images.kemik.gt/img1.jpg"


def test_mapear_producto_ld_con_offers_en_lista_y_low_price():
    producto_ld = {
        "@type": "Product",
        "name": "Redragon Kumara K552",
        "url": "https://www.kemik.gt/producto/redragon-kumara-k552",
        "image": {"@type": "ImageObject", "url": "/images/k552.jpg"},
        "offers": [{"@type": "AggregateOffer", "lowPrice": 325.5}],
    }

    oferta = KemikScraper._mapear_producto_ld_a_oferta(producto_ld)

    assert isinstance(oferta, OfertaLocal)
    assert oferta.precio_gtq == 325.5
    assert oferta.imagen_url == "https://www.kemik.gt/images/k552.jpg"


def test_mapear_producto_ld_incompleto_retorna_none():
    assert KemikScraper._mapear_producto_ld_a_oferta({"name": "Sin URL ni precio"}) is None
    assert (
        KemikScraper._mapear_producto_ld_a_oferta(
            {"name": "Sin precio", "url": "/prod/1", "offers": {}}
        )
        is None
    )


def test_extraer_item_list_json_ld_filtra_bloque_correcto():
    bloque_organizacion = json.dumps({"@type": "Organization", "name": "Kemik"})
    bloque_item_list = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "item": {"@type": "Product", "name": "Teclado 1", "url": "/p/1"},
                }
            ],
        }
    )

    locator_mock = MagicMock()
    locator_mock.all_text_contents = AsyncMock(
        return_value=["{json_invalido", bloque_organizacion, bloque_item_list]
    )
    page_mock = MagicMock()
    page_mock.locator.return_value = locator_mock

    import asyncio

    items = asyncio.run(KemikScraper._extraer_item_list_json_ld(page_mock))
    assert len(items) == 1
    assert items[0]["name"] == "Teclado 1"
