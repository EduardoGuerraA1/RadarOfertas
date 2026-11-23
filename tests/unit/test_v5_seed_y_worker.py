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
    # Fotografía y Laptops Pro/OLED v5.4
    assert "Canon EOS Rebel T7" in nombres
    assert "Canon R100" in nombres
    assert "Sony Alpha a6400" in nombres
    assert "Nikon D3500" in nombres
    assert "ASUS VivoBook Pro 15 OLED" in nombres
    assert "ASUS Zenbook OLED" in nombres
    assert "Lenovo Legion" in nombres


def test_cruce_matriz_tiendas_identifica_25_operativas_y_guatemaladigital_v5_4() -> None:
    assert len(tiendas_ecommerce_guatemala) == 6
    reporte = cruzar_matriz_tiendas_y_prioridades()

    assert reporte["total_operativas_sistema"] == 25
    assert len(reporte["operativas_cruzadas"]) >= 21
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
    assert reporte["tiendas_recien_activadas_v5_4"] == [
        "Guatemaladigital",
    ]
    nombres_foto_tech = {
        t["nombre"] for t in reporte["tiendas_especializadas_fotografia_y_tecnologia"]
    }
    assert {
        "iShop Guatemala",
        "iCon Guatemala",
        "Macrosistemas",
        "Spirit Computación",
        "Guatemaladigital",
    }.issubset(nombres_foto_tech)

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


def test_urls_salientes_seguras_rech_click_tera_redirigen_a_busqueda_oficial() -> None:
    from radar_ofertas.domain.services.filtro_relevancia import (
        construir_url_busqueda_tienda,
        resolver_url_saliente_segura,
    )

    # 1. URLs sintéticas o potencialmente rotas (/producto/ o dominio antiguo tera.gt)
    # se convierten automáticamente a la búsqueda oficial codificada de cada tienda
    url_click = resolver_url_saliente_segura(
        "https://www.click.gt/producto/mousepad-razer-gigantus-v2-large",
        "click",
        "Mousepad Gamer Razer Gigantus V2 Large",
    )
    assert url_click.startswith("https://www.click.gt/buscar?q=")
    assert "Razer" in url_click and "Gigantus" in url_click

    url_rech = resolver_url_saliente_segura(
        "https://www.rech.com.gt/producto/mousepad-razer-gigantus-v2-large",
        "rech",
        "Mousepad Gamer Razer Gigantus V2 Large",
    )
    assert url_rech.startswith("https://www.rech.com.gt/?s=")
    assert "post_type=product" in url_rech

    url_tera = resolver_url_saliente_segura(
        "https://www.tera.gt/producto/mousepad-razer-gigantus-v2-large",
        "tera",
        "Mousepad Gamer Razer Gigantus V2 Large",
    )
    assert url_tera.startswith("https://www.tera.com.gt/?s=")
    assert "post_type=product" in url_tera

    # 2. Todos los resultados de los scrapers Rech, Click y Tera entregan URLs de búsqueda válidas
    for scraper, prefijo_esperado in (
        (RechScraper(simular=True), "https://www.rech.com.gt/?s="),
        (ClickScraper(simular=True), "https://www.click.gt/buscar?q="),
        (TeraScraper(simular=True), "https://www.tera.com.gt/?s="),
    ):
        ofertas = asyncio.run(scraper.buscar_producto("Razer Gigantus V2 Large"))
        assert len(ofertas) == 1
        assert ofertas[0].url.startswith(prefijo_esperado)
        assert "/producto/" not in ofertas[0].url

    assert construir_url_busqueda_tienda("click", "Razer Gigantus V2 Large").startswith(
        "https://www.click.gt/buscar?q="
    )


def test_blindaje_matching_productos_estrictamente_identicos_gigantus_v2_large() -> None:
    from radar_ofertas.domain.services.filtro_relevancia import (
        es_oferta_relevante,
        filtrar_dicts_relevantes,
        son_productos_estrictamente_identicos,
    )
    from radar_ofertas.interfaces.api.app import _calcular_ahorro_preciso

    query_exacta = "Mousepad Razer Gigantus V2 Large"

    # Solo el producto idéntico (mismo tipo=mousepad, marca=razer, modelo=gigantus v2, talla=large) pasa el filtro
    assert es_oferta_relevante(
        "Mousepad Gamer Razer Gigantus V2 Large Tela Micro-Tejida", query_exacta
    ) is True
    assert es_oferta_relevante(
        "Mousepad Gamer Logitech G840 XL Cloth 900x400mm", query_exacta
    ) is False
    assert es_oferta_relevante(
        "Mousepad Gamer HyperX Fury S Pro Speed Edition XL", query_exacta
    ) is False
    assert es_oferta_relevante(
        "Mousepad Gamer Razer Gigantus V2 Medium", query_exacta
    ) is False
    assert es_oferta_relevante(
        "Teclado Mecanico Razer BlackWidow V4 Green Switch RGB", query_exacta
    ) is False

    # Comparación estricta entre ofertas de distintas tiendas
    gigantus_rech = {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Tela Micro-Tejida",
        "tienda_slug": "rech",
        "precio_gtq": 165.00,
        "categoria_ui": "computo",
        "gama_slug": "entrada",
    }
    gigantus_click = {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Large Base Antideslizante",
        "tienda_slug": "click",
        "precio_gtq": 185.00,
        "categoria_ui": "computo",
        "gama_slug": "entrada",
    }
    gigantus_medium_otro = {
        "titulo": "Mousepad Gamer Razer Gigantus V2 Medium",
        "tienda_slug": "tera",
        "precio_gtq": 125.00,
        "categoria_ui": "computo",
        "gama_slug": "entrada",
    }
    logitech_g840 = {
        "titulo": "Mousepad Gamer Logitech G840 XL Cloth",
        "tienda_slug": "kemik",
        "precio_gtq": 395.00,
        "categoria_ui": "computo",
        "gama_slug": "media",
    }

    assert son_productos_estrictamente_identicos(gigantus_rech, gigantus_click) is True
    assert son_productos_estrictamente_identicos(gigantus_rech, gigantus_medium_otro) is False
    assert son_productos_estrictamente_identicos(gigantus_rech, logitech_g840) is False

    # El cálculo de ahorro solo cruza los dos Razer Gigantus V2 Large (185 - 165 = Q20.00)
    # e ignora por completo el Logitech G840 XL de Q395.00
    lote = [gigantus_rech, gigantus_click, logitech_g840]
    filtrados = filtrar_dicts_relevantes(lote, query_exacta)
    assert len(filtrados) == 2
    ahorro = _calcular_ahorro_preciso(filtrados, query=query_exacta)
    assert ahorro == 20.00
    assert gigantus_rech["ahorro_gtq"] == 20.00
    assert gigantus_click["ahorro_gtq"] == 0.0


def test_v5_4_app_shell_skeleton_loading_css_estatico_y_health_ultraligero() -> None:
    from fastapi.testclient import TestClient
    from radar_ofertas.interfaces.api.app import (
        CACHE_NEON_TTL_SEGUNDOS,
        PAGINACION_DESTACADOS_DEFAULT,
        TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S,
        app,
    )

    # 1. Validar constantes arquitectónicas v5.4 (TTL 5m, paginación 28, timeout vivo 9s)
    assert CACHE_NEON_TTL_SEGUNDOS == 300.0
    assert 24 <= PAGINACION_DESTACADOS_DEFAULT <= 32
    assert TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S == 9.0

    client = TestClient(app)

    # 2. Endpoint ultraligero GET /health sin tocar base de datos
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    datos_health = resp_health.json()
    assert datos_health["status"] == "ok"
    assert datos_health["version"] == "5.4.0"
    assert datos_health["db_touched"] is False

    # 3. Recurso estático minificado /static/styles.css servido directamente
    resp_css = client.get("/static/styles.css")
    assert resp_css.status_code == 200
    assert ".skeleton-shimmer" in resp_css.text
    assert ".live-progress-bar" in resp_css.text
    assert ".apple-card" in resp_css.text

    # 4. GET / entrega inmediatamente el App Shell v5.4 con Skeleton Cards y sin cdn.tailwindcss.com
    resp_home = client.get("/?q=Canon+EOS+Rebel+T7")
    assert resp_home.status_code == 200
    html = resp_home.text
    assert "cdn.tailwindcss.com" not in html
    assert '/static/styles.css?v=5.4.0' in html
    assert 'id="skeleton-grid"' in html
    assert 'class="skeleton-card' in html
    assert "Consultando catálogos en vivo en Guatemala..." in html
    assert "/api/buscar-en-vivo" in html
    assert "hidratarAppShellDesdeNeon()" in html
    assert "GT v5.4" in html


def test_v5_4_busqueda_en_vivo_integracion_simulada_canon_t7_sony_vivobook_oled_y_cola_pendientes(
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient
    from radar_ofertas.infrastructure.scrapers.click_scraper import ClickScraper
    from radar_ofertas.infrastructure.scrapers.guatemaladigital_scraper import (
        GuatemalaDigitalScraper,
    )
    from radar_ofertas.infrastructure.scrapers.intelaf_scraper import IntelafScraper
    from radar_ofertas.infrastructure.scrapers.kemik_scraper import KemikScraper
    from radar_ofertas.infrastructure.scrapers.pacifiko_scraper import PacifikoScraper
    from radar_ofertas.interfaces.api import app as app_module
    from radar_ofertas.interfaces.api.app import (
        app,
        ejecutar_busqueda_en_vivo_acotada,
    )

    # Configurar batería rápida simulada para la prueba de integración de POST /api/buscar-en-vivo
    def _scrapers_simulados_v5_4(timeout_individual_s: int = 8):
        return [
            ("Guatemala Digital", GuatemalaDigitalScraper(simular=True)),
            ("Kemik", KemikScraper(usar_playwright=False, simular=True)),
            ("Pacifiko", PacifikoScraper(simular=True)),
            ("Intelaf", IntelafScraper(usar_playwright_fallback=False)),
            ("Click Guatemala", ClickScraper(simular=True)),
        ]

    monkeypatch.setattr(
        app_module, "_construir_scrapers_busqueda_en_vivo", _scrapers_simulados_v5_4
    )
    monkeypatch.setenv("DATABASE_URL", "")

    client = TestClient(app)

    # 1. Prueba de integración para 'canon t7'
    resp_canon = client.post("/api/buscar-en-vivo", json={"query": "canon t7"})
    assert resp_canon.status_code == 200
    data_canon = resp_canon.json()
    assert data_canon["status"] == "ok"
    assert data_canon["version"] == "5.4.0"
    assert data_canon["timeout_global_s"] == 9.0
    assert len(data_canon["ofertas"]) >= 3
    tiendas_canon = {o["tienda"] for o in data_canon["ofertas"]}
    assert "Guatemala Digital" in tiendas_canon
    assert "Kemik" in tiendas_canon or "Pacifiko" in tiendas_canon
    assert all("t7" in o["titulo"].lower() for o in data_canon["ofertas"])
    for o in data_canon["ofertas"]:
        if o["tienda_slug"] == "guatemaladigital":
            assert o["url"].startswith("https://guatemaladigital.com/Busqueda?Busqueda=")

    # 2. Prueba de integración para 'asus vivobook pro 15 oled'
    resp_asus = client.post(
        "/api/buscar-en-vivo", json={"query": "asus vivobook pro 15 oled"}
    )
    assert resp_asus.status_code == 200
    data_asus = resp_asus.json()
    assert len(data_asus["ofertas"]) >= 3
    assert all(
        "vivobook" in o["titulo"].lower() and "oled" in o["titulo"].lower()
        for o in data_asus["ofertas"]
    )

    # 3. Prueba de integración para 'sony'
    resp_sony = client.post("/api/buscar-en-vivo", json={"query": "sony"})
    assert resp_sony.status_code == 200
    data_sony = resp_sony.json()
    assert len(data_sony["ofertas"]) >= 2
    assert all("sony" in o["titulo"].lower() for o in data_sony["ofertas"])

    # 4. Cuando una búsqueda devuelve 0 resultados, se registra en busquedas_pendientes
    terminos_pendientes_registrados: list[tuple[str, str]] = []

    class _RepoMockPendientes:
        def guardar_ofertas(self, ofertas, categoria_slug="tecnologia") -> int:
            return len(ofertas)

        def registrar_busqueda_pendiente(
            self, termino: str, categoria_slug: str = "tecnologia"
        ) -> bool:
            terminos_pendientes_registrados.append((termino, categoria_slug))
            return True

    res_vacio = asyncio.run(
        ejecutar_busqueda_en_vivo_acotada(
            termino="producto inexistente xyz98765",
            scrapers=[("Guatemala Digital", GuatemalaDigitalScraper(simular=True))],
            timeout_global_s=1.0,
            persistir_en_db=True,
            repositorio=_RepoMockPendientes(),  # type: ignore[arg-type]
        )
    )
    assert res_vacio["ofertas_locales"] == []
    assert res_vacio["registrada_en_busquedas_pendientes"] is True
    assert terminos_pendientes_registrados == [
        ("producto inexistente xyz98765", "tecnologia")
    ]




