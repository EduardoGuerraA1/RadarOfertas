from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.infrastructure.scrapers.super_scraper import SuperScraper

PAYLOAD_MUESTRA_VTEX_LA_TORRE = [
    {
        "productId": "1047",
        "productName": "Alimento Perro Pequeño Res Pedigree",
        "brand": "PEDIGREE",
        "link": "https://www.latorre.com.gt/alimento-perro-pequeno-res-pedigree-109341/p",
        "Contenido Neto": ["100gr."],
        "items": [
            {
                "itemId": "1046",
                "images": [
                    {
                        "imageUrl": "https://latorremx.vteximg.com.br/arquivos/ids/164518/109341-frontal.jpg"
                    }
                ],
                "sellers": [
                    {
                        "commertialOffer": {
                            "Price": 7.10,
                            "AvailableQuantity": 100,
                        }
                    }
                ],
            }
        ],
    },
    {
        "productId": "2048",
        "productName": "Alimento para Perro Adulto Purina Dog Chow 20kg",
        "brand": "PURINA",
        "link": "/alimento-perro-adulto-purina-dog-chow-20kg/p",
        "Contenido Neto": ["20kg"],
        "items": [
            {
                "itemId": "2048",
                "images": [
                    {
                        "imageUrl": "https://latorremx.vteximg.com.br/arquivos/ids/200001/purina-20kg.jpg"
                    }
                ],
                "sellers": [
                    {
                        "commertialOffer": {
                            "Price": 389.50,
                            "AvailableQuantity": 15,
                        }
                    }
                ],
            }
        ],
    },
    {
        "productId": "9999",
        "productName": "Producto Agotado Sin Stock",
        "link": "/agotado/p",
        "items": [
            {
                "sellers": [
                    {
                        "commertialOffer": {
                            "Price": 50.0,
                            "AvailableQuantity": 0,
                        }
                    }
                ]
            }
        ],
    },
]


def test_parsear_respuesta_vtex_extrae_ofertas_la_torre():
    ofertas = SuperScraper.parsear_respuesta_vtex(PAYLOAD_MUESTRA_VTEX_LA_TORRE)

    assert len(ofertas) == 2
    assert all(isinstance(o, OfertaLocal) for o in ofertas)

    primera = ofertas[0]
    assert primera.tienda == "La Torre"
    assert primera.titulo == "Alimento Perro Pequeño Res Pedigree (100gr.)"
    assert primera.precio_gtq == 7.10
    assert (
        primera.url
        == "https://www.latorre.com.gt/alimento-perro-pequeno-res-pedigree-109341/p"
    )
    assert (
        primera.imagen_url
        == "https://latorremx.vteximg.com.br/arquivos/ids/164518/109341-frontal.jpg"
    )

    segunda = ofertas[1]
    assert segunda.tienda == "La Torre"
    assert segunda.titulo == "Alimento para Perro Adulto Purina Dog Chow 20kg"
    assert segunda.precio_gtq == 389.50
    assert (
        segunda.url
        == "https://www.latorre.com.gt/alimento-perro-adulto-purina-dog-chow-20kg/p"
    )


def test_parsear_respuesta_vtex_json_invalido_retorna_vacio():
    assert SuperScraper.parsear_respuesta_vtex("") == []
    assert SuperScraper.parsear_respuesta_vtex("{malformado") == []
