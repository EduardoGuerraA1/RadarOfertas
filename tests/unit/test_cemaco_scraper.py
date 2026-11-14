"""
Pruebas unitarias para CemacoScraper (VTEX Catalog API de Cemaco Guatemala)
y resiliencia del endpoint /api/escanear.
"""
from __future__ import annotations

import asyncio

from radar_ofertas.infrastructure.scrapers.cemaco_scraper import CemacoScraper
from radar_ofertas.interfaces.api.app import _ejecutar_scraper_seguro


PAYLOAD_VTEX_CEMACO_EJEMPLO = [
    {
        "productId": "1093560",
        "productName": "<VF>#Rotomartillo 1/2 plg 550W - Pretul",
        "brand": "Pretul",
        "link": "https://www.cemaco.com/<vf>#rotomartillo-12-plg-550w---pretul-1093560/p",
        "linkText": "<vf>#rotomartillo-12-plg-550w---pretul-1093560",
        "items": [
            {
                "itemId": "1093560",
                "images": [
                    {
                        "imageUrl": "https://cemacogt.vteximg.com.br/arquivos/ids/411456/1093560_1.jpg?v=638000"
                    }
                ],
                "sellers": [
                    {
                        "sellerDefault": True,
                        "commertialOffer": {
                            "Price": 249.99,
                            "ListPrice": 299.99,
                            "AvailableQuantity": 15,
                        },
                    }
                ],
            }
        ],
    },
    {
        "productId": "1021242",
        "productName": "Taladro percutor 1/2 plg 700W - Truper",
        "brand": "Truper",
        "link": "https://www.cemaco.com/taladro-percutor-12-plg-700w---truper-1021242/p",
        "items": [
            {
                "itemId": "1021242",
                "images": [
                    {
                        "imageUrl": "https://cemacogt.vteximg.com.br/arquivos/ids/312000/1021242_1.jpg"
                    }
                ],
                "sellers": [
                    {
                        "sellerDefault": True,
                        "commertialOffer": {
                            "Price": 449.99,
                            "ListPrice": 499.99,
                            "AvailableQuantity": 8,
                        },
                    }
                ],
            }
        ],
    },
]


def test_cemaco_scraper_limpia_prefijos_erp_y_extrae_precios() -> None:
    scraper = CemacoScraper()
    ofertas = scraper.parsear_respuesta_vtex(PAYLOAD_VTEX_CEMACO_EJEMPLO)

    assert len(ofertas) == 2

    primera = ofertas[0]
    assert primera.tienda == "Cemaco"
    assert primera.titulo == "Rotomartillo 1/2 plg 550W - Pretul"
    assert primera.precio_gtq == 249.99
    assert primera.url == "https://www.cemaco.com/#rotomartillo-12-plg-550w---pretul-1093560/p" or "rotomartillo-12-plg-550w---pretul-1093560/p" in primera.url
    assert "<vf>" not in primera.url.lower()
    assert primera.imagen_url.startswith("https://cemacogt.vteximg.com.br/arquivos/ids/411456/1093560_1.jpg")


def test_ejecutar_scraper_seguro_aisla_excepciones_y_timeouts() -> None:
    class ScraperFallido:
        async def buscar_producto(self, termino: str):
            raise RuntimeError("Error simulado de Cloudflare / Playwright")

    class ScraperLento:
        async def buscar_producto(self, termino: str):
            await asyncio.sleep(5)
            return []

    ofertas_err, msg_err = asyncio.run(
        _ejecutar_scraper_seguro(ScraperFallido(), "Kemik", "volante", timeout_s=1.0)
    )
    assert ofertas_err == []
    assert msg_err is not None and "Kemik" in msg_err

    ofertas_timeout, msg_timeout = asyncio.run(
        _ejecutar_scraper_seguro(ScraperLento(), "Tiendas Max", "galaxy", timeout_s=0.1)
    )
    assert ofertas_timeout == []
    assert msg_timeout is not None and "tiempo de espera agotado" in msg_timeout
