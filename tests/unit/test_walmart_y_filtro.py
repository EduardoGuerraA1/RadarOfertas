"""
Pruebas unitarias para WalmartScraper (Grupo Walmart GT: Walmart, Paiz y Maxi Despensa)
y para el Filtro Inteligente Anti-Ruido (filtro_relevancia.py).
"""
from __future__ import annotations

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.domain.services.filtro_relevancia import (
    es_oferta_relevante,
    filtrar_ofertas_relevantes,
)
from radar_ofertas.infrastructure.scrapers.walmart_scraper import WalmartScraper


PAYLOAD_WALMART_VTEX_EJEMPLO = [
    {
        "productId": "113138",
        "productName": "Pedigree Adulto 13 Mas 2 kg Bonus 15kg",
        "brand": "PEDIGREE",
        "linkText": "pedigree-adulto-13-mas-2-kg-bonus-15kg-gt4690-4-4",
        "link": "https://www.walmart.com.gt/pedigree-adulto-13-mas-2-kg-bonus-15kg-gt4690-4-4/p",
        "items": [
            {
                "itemId": "113138",
                "images": [
                    {
                        "imageUrl": "https://walmartgt.vteximg.com.br/arquivos/ids/983901/pedigree-15kg.jpg?v=63911804"
                    }
                ],
                "sellers": [
                    {
                        "sellerDefault": True,
                        "commertialOffer": {
                            "Price": 200.0,
                            "ListPrice": 225.0,
                            "AvailableQuantity": 100,
                        },
                    }
                ],
            }
        ],
    }
]


def test_walmart_scraper_parsea_vtex_para_walmart_paiz_y_maxi_despensa() -> None:
    ofertas_wm = WalmartScraper.parsear_respuesta_vtex(
        PAYLOAD_WALMART_VTEX_EJEMPLO,
        nombre_tienda="Walmart",
        base_url="https://www.walmart.com.gt/",
    )
    ofertas_paiz = WalmartScraper.parsear_respuesta_vtex(
        PAYLOAD_WALMART_VTEX_EJEMPLO,
        nombre_tienda="Paiz",
        base_url="https://www.paiz.com.gt/",
    )
    ofertas_maxi = WalmartScraper.parsear_respuesta_vtex(
        PAYLOAD_WALMART_VTEX_EJEMPLO,
        nombre_tienda="Maxi Despensa",
        base_url="https://www.maxidespensa.com.gt/",
    )

    assert len(ofertas_wm) == 1
    assert ofertas_wm[0].tienda == "Walmart"
    assert ofertas_wm[0].precio_gtq == 200.0
    assert (
        ofertas_wm[0].url
        == "https://www.walmart.com.gt/pedigree-adulto-13-mas-2-kg-bonus-15kg-gt4690-4-4/p"
    )
    assert (
        ofertas_wm[0].imagen_url
        == "https://walmartgt.vteximg.com.br/arquivos/ids/983901/pedigree-15kg.jpg"
    )

    assert ofertas_paiz[0].tienda == "Paiz"
    assert ofertas_paiz[0].url.startswith("https://www.paiz.com.gt/")
    assert ofertas_maxi[0].tienda == "Maxi Despensa"
    assert ofertas_maxi[0].url.startswith("https://www.maxidespensa.com.gt/")


def test_filtro_inteligente_anti_ruido_descarta_accesorios_y_conserva_dispositivos() -> None:
    # Búsqueda de smartwatch principal
    assert es_oferta_relevante(
        "Samsung Galaxy Watch 7 40mm Bluetooth Smartwatch", "galaxy watch"
    )
    assert not es_oferta_relevante(
        "Silicone Sport Band for Samsung Galaxy Watch Ultra 47mm", "galaxy watch"
    )
    assert not es_oferta_relevante(
        "Tensea 2PCS Screen Protector Case for Galaxy Watch 7", "galaxy watch"
    )
    assert not es_oferta_relevante(
        "Correa de Silicona para Reloj Inteligente", "galaxy watch"
    )

    # Si el usuario busca explícitamente 'correa galaxy watch', sí permite correas
    assert es_oferta_relevante(
        "Correa de Silicona para Samsung Galaxy Watch", "correa galaxy watch"
    )

    # Búsqueda de taladro principal descarta carbones y mandriles
    ofertas = [
        OfertaLocal(
            tienda="Cemaco",
            titulo="Set de 2 Carbones para Taladro Tal-3/8A2",
            precio_gtq=17.99,
            url="https://www.cemaco.com/carbones/p",
            imagen_url="",
        ),
        OfertaLocal(
            tienda="Cemaco",
            titulo="Taladro Percutor 1/2 plg 700W - Truper",
            precio_gtq=449.99,
            url="https://www.cemaco.com/taladro-truper/p",
            imagen_url="",
        ),
    ]
    filtradas = filtrar_ofertas_relevantes(ofertas, "taladro")
    assert len(filtradas) == 1
    assert filtradas[0].titulo == "Taladro Percutor 1/2 plg 700W - Truper"
