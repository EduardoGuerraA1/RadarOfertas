"""
Pruebas unitarias para tecHunter GT v5.0:
  - Módulo de Datos Semilla (`seed_data.py`): `seed_list_guatemala` y `tiendas_ecommerce_guatemala`
  - Cruce automático de las 18 tiendas operativas e identificación del Top 3 de alta prioridad
  - Selección de lotes en `worker_precarga.py`
  - Corrección del cálculo de ahorro (`_calcular_ahorro_preciso`): cero ahorros absurdos entre productos distintos
  - Analítica Web de visitantes (`GestorAnaliticaWeb`)
  - Esqueletos de scrapers para Tienda Tigo GT, Office Depot GT y Tropigas
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from radar_ofertas.application.use_cases.analitica_web import GestorAnaliticaWeb
from radar_ofertas.application.use_cases.worker_precarga import seleccionar_lote_semilla
from radar_ofertas.domain.seed_data import (
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
    tiendas_ecommerce_guatemala,
)
from radar_ofertas.infrastructure.scrapers.officedepot_scraper import OfficeDepotScraper
from radar_ofertas.infrastructure.scrapers.tigo_scraper import TigoScraper
from radar_ofertas.infrastructure.scrapers.tropigas_scraper import TropigasScraper
from radar_ofertas.interfaces.api.app import _calcular_ahorro_preciso


def test_seed_list_guatemala_contiene_5_verticales_y_productos_clave() -> None:
    expected_keys = {
        "computo_y_laptops",
        "smartphones",
        "linea_blanca_y_hogar",
        "herramientas_y_ferreteria",
        "supermercado_y_mascotas",
    }
    assert set(seed_list_guatemala.keys()) == expected_keys

    todos = obtener_todos_los_productos_semilla()
    assert len(todos) >= 130
    nombres = [item[2] for item in todos]
    assert "MacBook Air M2 8GB 256GB" in nombres
    assert "Samsung Galaxy S24 Ultra 256GB" in nombres
    assert "Refrigeradora Mabe 11 pies" in nombres
    assert "Taladro percutor inalambrico DeWalt 20V" in nombres
    assert "Alimento para perro Pedigree adulto 21 kg" in nombres
    assert "Incaparina original 450g" in nombres


def test_cruce_matriz_tiendas_identifica_21_operativas_y_3_recien_activadas_v5_1() -> None:
    assert len(tiendas_ecommerce_guatemala) == 6
    reporte = cruzar_matriz_tiendas_y_prioridades()

    assert reporte["total_operativas_sistema"] == 21
    assert len(reporte["operativas_cruzadas"]) >= 17
    assert reporte["tiendas_recien_activadas_v5_1"] == [
        "Tienda Tigo Guatemala",
        "Office Depot Guatemala",
        "Tropigas",
    ]

    top_3 = reporte["siguientes_3_alta_prioridad"]
    assert len(top_3) == 3
    nombres_top_3 = [t["nombre"] for t in top_3]
    assert nombres_top_3 == [
        "El Gallo Más Gallo",
        "Arca de Noé",
        "Samsung Store Guatemala",
    ]


def test_worker_precarga_selecciona_lote_por_muestra_y_categoria() -> None:
    lote_muestra = seleccionar_lote_semilla(muestra_por_categoria=2)
    assert len(lote_muestra) == 10

    lote_herramientas = seleccionar_lote_semilla(
        categoria_filtro="herramientas_y_ferreteria", limite_total=5
    )
    assert len(lote_herramientas) == 5
    assert all(cat_db == "hogar" for _, cat_db, _ in lote_herramientas)


def test_calculo_ahorro_no_mezcla_productos_distintos_ni_genera_ahorros_absurdos() -> None:
    # Caso 1: Bug reportado en producción (Alimento Fiel Amigo 1lb de Q4.25 vs artículo caro de Q49,089.25)
    ofertas_dispares = [
        {
            "producto_id": "prod-1",
            "titulo": "Alimento para perro Fiel amigo sabor pollo y vegetales - 1 lb",
            "tienda_slug": "maxi-despensa",
            "tienda": "Maxi Despensa",
            "precio_gtq": 4.25,
            "costo_real_gtq": 39.25,
            "categoria_ui": "super-mascotas",
            "gama_slug": "media",
            "clave_modelo": "super-mascotas:media",
        },
        {
            "producto_id": "prod-2",
            "titulo": "Suministro Industrial Mayorista Pallet Completo",
            "tienda_slug": "pacifiko",
            "tienda": "Pacifiko",
            "precio_gtq": 49089.25,
            "costo_real_gtq": 49124.25,
            "categoria_ui": "super-mascotas",
            "gama_slug": "media",
            "clave_modelo": "super-mascotas:media",
        },
    ]
    ahorro_dispar = _calcular_ahorro_preciso(ofertas_dispares, query="")
    assert ahorro_dispar == 0.0
    assert ofertas_dispares[0]["ahorro_gtq"] == 0.0

    # Caso 2: Mismo producto real en dos tiendas (Logitech G29 en Kemik Q2,699 vs Pacifiko Q2,995)
    ofertas_mismo_producto = [
        {
            "producto_id": "g29-kemik",
            "titulo": "Volante Logitech G29 Driving Force para PS5 PS4 y PC",
            "tienda_slug": "kemik",
            "tienda": "Kemik",
            "precio_gtq": 2699.00,
            "costo_real_gtq": 2734.00,
            "categoria_ui": "computo",
            "gama_slug": "profesional",
            "clave_modelo": "g29",
        },
        {
            "producto_id": "g29-pacifiko",
            "titulo": "Logitech G29 Driving Force Volante de Carreras para PlayStation y PC",
            "tienda_slug": "pacifiko",
            "tienda": "Pacifiko",
            "precio_gtq": 2995.00,
            "costo_real_gtq": 3030.00,
            "categoria_ui": "computo",
            "gama_slug": "profesional",
            "clave_modelo": "g29",
        },
    ]
    ahorro_real = _calcular_ahorro_preciso(
        ofertas_mismo_producto, query="volante logitech"
    )
    assert ahorro_real == 296.00
    assert ofertas_mismo_producto[0]["ahorro_gtq"] == 296.00
    assert ofertas_mismo_producto[1]["ahorro_gtq"] == 0.0


def test_gestor_analitica_web_filtra_bots_uptimerobot_y_valida_token_admin() -> None:
    from radar_ofertas.application.use_cases.analitica_web import (
        es_bot_o_monitor,
        es_token_admin_valido,
    )

    analitica = GestorAnaliticaWeb()
    ua_humano = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15"
    ua_uptimerobot = "Mozilla/5.0+(compatible; UptimeRobot/2.0; http://www.uptimerobot.com/)"

    assert es_bot_o_monitor(ua_uptimerobot) is True
    assert es_bot_o_monitor(ua_humano, metodo_http="HEAD") is True
    assert es_bot_o_monitor(ua_humano, metodo_http="GET") is False

    # 2 visitas humanas reales
    assert analitica.registrar_visita(
        query="MacBook Air M2",
        categoria="computo",
        user_agent=ua_humano,
        metodo_http="GET",
    ) is True
    assert analitica.registrar_visita(
        query="MacBook Air M2",
        categoria="computo",
        user_agent=ua_humano,
        metodo_http="GET",
    ) is True

    # Pings de UptimeRobot y HEAD son descartados automáticamente
    assert analitica.registrar_visita(
        query="",
        user_agent=ua_uptimerobot,
        metodo_http="GET",
    ) is False
    assert analitica.registrar_visita(
        query="",
        user_agent=ua_humano,
        metodo_http="HEAD",
    ) is False

    analitica.registrar_evento(
        tipo="outbound_click",
        query="MacBook Air M2",
        tienda="iStore",
        titulo='Apple MacBook Air 13" M2',
        url_destino="https://ishop.gt/products/macbook-air-m2",
        precio_gtq=8999.00,
        user_agent=ua_humano,
    )
    # Evento desde bot ignorado
    analitica.registrar_evento(
        tipo="outbound_click",
        query="MacBook Air M2",
        tienda="iStore",
        titulo='Apple MacBook Air 13" M2',
        url_destino="https://ishop.gt/products/macbook-air-m2",
        precio_gtq=8999.00,
        user_agent=ua_uptimerobot,
    )

    resumen = analitica.obtener_resumen()
    assert resumen["visitas_totales"] == 2
    assert resumen["pings_bots_ignorados"] == 3
    assert resumen["busquedas_totales"] == 2
    assert resumen["clics_salientes_totales"] == 1
    assert resumen["top_terminos_busqueda"][0] == {
        "termino": "macbook air m2",
        "busquedas": 2,
    }
    assert resumen["clics_salientes_por_tienda"][0] == {
        "tienda": "iStore",
        "clics": 1,
    }

    assert es_token_admin_valido("secreto") is True
    assert es_token_admin_valido("publico_invalido") is False


def test_activacion_real_3_tiendas_prioritarias_tigo_officedepot_tropigas() -> None:
    tigo = TigoScraper(simular=True)
    officedepot = OfficeDepotScraper(simular=True)
    tropigas = TropigasScraper(simular=True)

    res_tigo = asyncio.run(tigo.buscar_producto("iphone 16"))
    res_od = asyncio.run(officedepot.buscar_producto("impresora epson"))
    res_tropigas = asyncio.run(tropigas.buscar_producto("refrigeradora mabe"))

    assert len(res_tigo) >= 1
    assert res_tigo[0].tienda == "Tienda Tigo"
    assert res_tigo[0].precio_gtq > Decimal("0")

    assert len(res_od) >= 1
    assert res_od[0].tienda == "Office Depot"
    assert res_od[0].precio_gtq > Decimal("0")

    assert len(res_tropigas) >= 1
    assert res_tropigas[0].tienda == "Tropigas"
    assert res_tropigas[0].precio_gtq > Decimal("0")

    # Modo deshabilitado sigue disponible si se requiere apagar manualmente
    assert asyncio.run(TigoScraper(habilitado=False).buscar_producto("iphone 16")) == []

    ofertas_tigo = tigo.parsear_respuesta_catalogo(
        {
            "items": [
                {
                    "name": "iPhone 16 128GB Prepago Tigo",
                    "price": "7999.00",
                    "url": "/iphone-16-128gb",
                    "image": "https://tienda.tigo.com.gt/img/ip16.jpg",
                }
            ]
        }
    )
    assert len(ofertas_tigo) == 1
    assert ofertas_tigo[0].tienda == "Tienda Tigo"
    assert ofertas_tigo[0].precio_gtq == Decimal("7999.00")

    ofertas_od = officedepot.parsear_respuesta_hybris(
        {
            "products": [
                {
                    "name": "Impresora Epson EcoTank L3250 Wi-Fi",
                    "price": {"value": 1699.00},
                    "url": "/officedepotGuatemala/es/p/100200",
                }
            ]
        }
    )
    assert len(ofertas_od) == 1
    assert ofertas_od[0].tienda == "Office Depot"

    ofertas_tropigas = tropigas.parsear_respuesta_unicomer(
        {
            "items": [
                {
                    "name": "Refrigeradora Mabe 11 Pies RMA1130JM",
                    "price": 3299.00,
                    "url": "/refrigeradora-mabe-11-pies",
                }
            ]
        }
    )
    assert len(ofertas_tropigas) == 1
    assert ofertas_tropigas[0].tienda == "Tropigas"
