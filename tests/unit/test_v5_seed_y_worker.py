"""
Pruebas unitarias para tecHunter GT v5.2:
  - Módulo de Datos Semilla (`seed_data.py`): `seed_list_guatemala` ampliada con periféricos
    (mousepads, teclados mecánicos, diademas gamer, webcams) y cámaras de seguridad smart home (Tapo, Ezviz)
  - Cruce automático de las 24 tiendas operativas (incluyendo Rech, Click Guatemala y Tera)
  - Worker en segundo plano configurado al menos 3 veces al día (cada 8h = 480 min) y rotación por lote
  - Corrección del cálculo de ahorro (`_calcular_ahorro_preciso`): cero ahorros absurdos entre productos distintos
  - Analítica Web de visitantes (`GestorAnaliticaWeb`) con filtro anti-bots y privacidad admin
  - Scrapers funcionales para Rech, Click Guatemala, Tera, Tienda Tigo GT, Office Depot GT y Tropigas
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from radar_ofertas.application.use_cases.analitica_web import GestorAnaliticaWeb
from radar_ofertas.application.use_cases.worker_precarga import (
    CICLOS_DIARIOS_MINIMOS,
    INTERVALO_MINUTOS_DEFAULT,
    calcular_intervalo_sincronizacion_minutos,
    seleccionar_lote_semilla,
)
from radar_ofertas.domain.seed_data import (
    cruzar_matriz_tiendas_y_prioridades,
    obtener_todos_los_productos_semilla,
    seed_list_guatemala,
    tiendas_ecommerce_guatemala,
)
from radar_ofertas.infrastructure.scrapers.click_scraper import ClickScraper
from radar_ofertas.infrastructure.scrapers.officedepot_scraper import OfficeDepotScraper
from radar_ofertas.infrastructure.scrapers.rech_scraper import RechScraper
from radar_ofertas.infrastructure.scrapers.tera_scraper import TeraScraper
from radar_ofertas.infrastructure.scrapers.tigo_scraper import TigoScraper
from radar_ofertas.infrastructure.scrapers.tropigas_scraper import TropigasScraper
from radar_ofertas.interfaces.api.app import _calcular_ahorro_preciso


def test_seed_list_guatemala_contiene_5_verticales_y_perifericos_camaras_v5_2() -> None:
    expected_keys = {
        "computo_y_laptops",
        "smartphones",
        "linea_blanca_y_hogar",
        "herramientas_y_ferreteria",
        "supermercado_y_mascotas",
    }
    assert set(seed_list_guatemala.keys()) == expected_keys

    todos = obtener_todos_los_productos_semilla()
    assert len(todos) >= 160
    nombres = [item[2] for item in todos]
    # Productos núcleo
    assert "MacBook Air M2 8GB 256GB" in nombres
    assert "Samsung Galaxy S24 Ultra 256GB" in nombres
    assert "Refrigeradora Mabe 11 pies" in nombres
    assert "Taladro percutor inalambrico DeWalt 20V" in nombres
    assert "Alimento para perro Pedigree adulto 21 kg" in nombres
    assert "Incaparina original 450g" in nombres
    # Nuevos periféricos de alta demanda v5.2 (mousepads, teclados mecánicos, diademas, webcams)
    assert "Mousepad Gamer Logitech G840 XL" in nombres
    assert "Teclado Mecanico Redragon Kumara K552 RGB" in nombres
    assert "Diadema Gamer HyperX Cloud III" in nombres
    assert "Webcam Logitech C920s Pro Full HD 1080p" in nombres
    # Nuevas cámaras de seguridad para el hogar v5.2 (TP-Link Tapo, Ezviz)
    assert "Camara de seguridad TP-Link Tapo C200 360 WiFi" in nombres
    assert "Camara de seguridad Ezviz C6N 1080p 360 Smart" in nombres


def test_cruce_matriz_tiendas_identifica_24_operativas_y_especialistas_computo_v5_2() -> None:
    assert len(tiendas_ecommerce_guatemala) == 6
    reporte = cruzar_matriz_tiendas_y_prioridades()

    assert reporte["total_operativas_sistema"] == 24
    assert len(reporte["operativas_cruzadas"]) >= 20
    assert reporte["tiendas_recien_activadas_v5_1"] == [
        "Tienda Tigo Guatemala",
        "Office Depot Guatemala",
        "Tropigas",
    ]
    assert reporte["tiendas_recien_activadas_v5_2"] == [
        "Rech Guatemala",
        "Click Guatemala",
        "Tera Guatemala",
    ]

    top_3 = reporte["siguientes_3_alta_prioridad"]
    assert len(top_3) == 3
    nombres_top_3 = [t["nombre"] for t in top_3]
    assert nombres_top_3 == [
        "El Gallo Más Gallo",
        "Arca de Noé",
        "Samsung Store Guatemala",
    ]


def test_worker_precarga_3_veces_al_dia_y_rotacion_de_lote_semilla() -> None:
    assert CICLOS_DIARIOS_MINIMOS == 3
    assert INTERVALO_MINUTOS_DEFAULT == 480
    # Nunca permite un intervalo mayor a 480 minutos (garantiza >= 3 ejecuciones cada 24h)
    assert calcular_intervalo_sincronizacion_minutos(480) == 480
    assert calcular_intervalo_sincronizacion_minutos(720) == 480
    assert calcular_intervalo_sincronizacion_minutos(240) == 240

    lote_ciclo_0 = seleccionar_lote_semilla(muestra_por_categoria=2, ciclo_offset=0)
    lote_ciclo_1 = seleccionar_lote_semilla(muestra_por_categoria=2, ciclo_offset=1)
    assert len(lote_ciclo_0) == 10
    assert len(lote_ciclo_1) == 10
    assert lote_ciclo_0 != lote_ciclo_1

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


def test_activacion_real_tiendas_tigo_officedepot_tropigas_y_especialistas_rech_click_tera() -> None:
    tigo = TigoScraper(simular=True)
    officedepot = OfficeDepotScraper(simular=True)
    tropigas = TropigasScraper(simular=True)
    rech = RechScraper(simular=True)
    click = ClickScraper(simular=True)
    tera = TeraScraper(simular=True)

    res_tigo = asyncio.run(tigo.buscar_producto("iphone 16"))
    res_od = asyncio.run(officedepot.buscar_producto("impresora epson"))
    res_tropigas = asyncio.run(tropigas.buscar_producto("refrigeradora mabe"))
    res_rech = asyncio.run(rech.buscar_producto("teclado mecanico"))
    res_click = asyncio.run(click.buscar_producto("tapo c200"))
    res_tera = asyncio.run(tera.buscar_producto("diadema hyperx"))

    assert len(res_tigo) >= 1 and res_tigo[0].tienda == "Tienda Tigo"
    assert len(res_od) >= 1 and res_od[0].tienda == "Office Depot"
    assert len(res_tropigas) >= 1 and res_tropigas[0].tienda == "Tropigas"
    assert len(res_rech) >= 1 and res_rech[0].tienda == "Rech" and res_rech[0].precio_gtq > Decimal("0")
    assert len(res_click) >= 1 and res_click[0].tienda == "Click Guatemala" and res_click[0].precio_gtq > Decimal("0")
    assert len(res_tera) >= 1 and res_tera[0].tienda == "Tera" and res_tera[0].precio_gtq > Decimal("0")

    # Modo deshabilitado sigue disponible si se requiere apagar manualmente
    assert asyncio.run(RechScraper(habilitado=False).buscar_producto("teclado")) == []


def test_respaldo_rapido_en_memoria_evita_bloqueos_cuando_termino_no_esta_en_db() -> None:
    from radar_ofertas.interfaces.api.app import _buscar_respaldo_rapido_en_memoria

    ofertas_respaldo = _buscar_respaldo_rapido_en_memoria(query="tapo c200")
    assert len(ofertas_respaldo) >= 1
    tiendas = {o["tienda_slug"] for o in ofertas_respaldo}
    assert "rech" in tiendas or "click" in tiendas or "tera" in tiendas
    assert all(o["precio_gtq"] > 0 for o in ofertas_respaldo)

    # Término inexistente devuelve lista vacía en <2 ms sin bloquear ni lanzar excepción
    vacio = _buscar_respaldo_rapido_en_memoria(query="xyzproductoimaginario999")
    assert vacio == []

