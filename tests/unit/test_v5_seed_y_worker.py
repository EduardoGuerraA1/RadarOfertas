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


def test_v5_5_tolerancia_cero_datos_sinteticos_y_parsers_reales_tiendas() -> None:
    from radar_ofertas.infrastructure.scrapers.guatemaladigital_scraper import (
        GuatemalaDigitalScraper,
    )

    tigo = TigoScraper()
    officedepot = OfficeDepotScraper()
    tropigas = TropigasScraper()
    rech = RechScraper()
    click = ClickScraper()
    tera = TeraScraper()
    gd = GuatemalaDigitalScraper()

    # 1. En modo simular=True o cuando una tienda no responde, los scrapers deben devolver [] (prohibido inventar datos)
    assert asyncio.run(TigoScraper(simular=True).buscar_producto("iphone 16")) == []
    assert asyncio.run(OfficeDepotScraper(simular=True).buscar_producto("impresora")) == []
    assert asyncio.run(TropigasScraper(simular=True).buscar_producto("refrigeradora")) == []
    assert asyncio.run(RechScraper(simular=True).buscar_producto("teclado")) == []
    assert asyncio.run(ClickScraper(simular=True).buscar_producto("mousepad")) == []
    assert asyncio.run(TeraScraper(simular=True).buscar_producto("diadema")) == []
    assert asyncio.run(GuatemalaDigitalScraper(simular=True).buscar_producto("canon t7")) == []
    assert asyncio.run(RechScraper(habilitado=False).buscar_producto("teclado")) == []

    # 2. Parsers reales extraen únicamente URLs directas de producto (https://...), imagen y precio real
    res_gd = gd.parsear_respuesta_api(
        {
            "Response": [
                {
                    "Articulos": [
                        {
                            "CodigoProducto": 16123991,
                            "Descripcion": "Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP con Lente 18-55mm",
                            "Precio": 4195.0,
                            "Foto": "https://m.media-amazon.com/images/I/71EWRyqzw0L._AC_SL1500_.jpg",
                        }
                    ]
                }
            ]
        }
    )
    assert len(res_gd) == 1
    assert res_gd[0].tienda == "Guatemala Digital"
    assert res_gd[0].url == "https://guatemaladigital.com/Producto/16123991"
    assert res_gd[0].imagen_url.startswith("https://m.media-amazon.com/")

    res_click = click.parsear_respuesta_catalogo(
        {
            "resources": {
                "results": {
                    "products": [
                        {
                            "title": "Mousepad Gamer Razer Gigantus V2 Large",
                            "price": "175.00",
                            "url": "/products/mousepad-razer-gigantus-v2-large?variant=99",
                            "image": "//cdn.shopify.com/s/files/1/gigantus.jpg",
                        }
                    ]
                }
            }
        }
    )
    assert len(res_click) == 1
    assert res_click[0].tienda == "Click Guatemala"
    assert res_click[0].url == "https://click.gt/products/mousepad-razer-gigantus-v2-large"
    assert res_click[0].imagen_url.startswith("https://cdn.shopify.com/")

    res_rech = rech.parsear_html(
        """
        <div class="item">
          <a href="detalle_producto.php?id=8028"><img src="https://intech.com.gt/sU/files/articulos_thumbs_300/6794.jpg" /></a>
          <a href="detalle_producto.php?id=8028">Mousepad Gamer Razer Gigantus V2 Large</a>
          <span>Q165.00</span>
        </div>
        """
    )
    assert len(res_rech) == 1
    assert res_rech[0].tienda == "Rech"
    assert res_rech[0].url == "https://rech.com.gt/detalle_producto.php?id=8028"
    assert res_rech[0].precio_gtq == Decimal("165.00")

    res_tigo = tigo.parsear_respuesta_catalogo(
        {
            "items": [
                {
                    "name": "Apple iPhone 16 128GB Negro",
                    "price": "7899.00",
                    "url": "https://tienda.tigo.com.gt/smartphones/iphone-16-128gb-negro",
                    "image": "https://tienda.tigo.com.gt/media/iphone16.jpg",
                }
            ]
        }
    )
    assert len(res_tigo) == 1 and res_tigo[0].tienda == "Tienda Tigo"

    res_od = officedepot.parsear_respuesta_hybris(
        {
            "products": [
                {
                    "name": "Impresora Epson EcoTank L3250",
                    "price": {"value": "1649.00"},
                    "url": "/officedepotGuatemala/es/p/100098412",
                    "image": "https://www.officedepot.com.gt/medias/100098412.jpg",
                }
            ]
        }
    )
    assert len(res_od) == 1 and res_od[0].tienda == "Office Depot"

    res_tropigas = tropigas.parsear_respuesta_unicomer(
        [
            {
                "productName": "Refrigeradora Mabe 11 Pies RMA1130JM0",
                "link": "https://www.almacenestropigas.com/guatemala/refrigeradora-mabe-11-pies-rma1130jm0/p",
                "items": [
                    {
                        "images": [{"imageUrl": "https://almacenestropigas.vteximg.com.br/arquivos/ids/155555/mabe.jpg"}],
                        "sellers": [{"commertialOffer": {"Price": 3199.00}}],
                    }
                ],
            }
        ]
    )
    assert len(res_tropigas) == 1 and res_tropigas[0].tienda == "Tropigas"

    res_tera = tera.parsear_respuesta_catalogo(
        {
            "items": [
                {
                    "name": "Diadema Gamer HyperX Cloud III",
                    "price": "799.00",
                    "url": "https://www.tera.com.gt/producto/diadema-hyperx-cloud-iii",
                    "image": "https://www.tera.com.gt/img/cloud3.jpg",
                }
            ]
        }
    )
    assert len(res_tera) == 1 and res_tera[0].tienda == "Tera"


def test_respaldo_rapido_en_memoria_desactivado_por_tolerancia_cero_v5_5() -> None:
    from radar_ofertas.interfaces.api.app import _buscar_respaldo_rapido_en_memoria

    # En v5.5 está prohibido devolver datos estáticos inventados desde memoria
    assert _buscar_respaldo_rapido_en_memoria(query="tapo c200") == []
    assert _buscar_respaldo_rapido_en_memoria(query="xyzproductoimaginario999") == []


def test_validacion_estricta_urls_directas_rechaza_plantillas_de_busqueda_v5_5() -> None:
    from radar_ofertas.domain.services.filtro_relevancia import (
        es_url_producto_directa_valida,
        resolver_url_saliente_segura,
    )

    # 1. URLs directas reales de producto son válidas
    assert es_url_producto_directa_valida("https://click.gt/products/mouse-pad-razer-sphex-v3-small") is True
    assert es_url_producto_directa_valida("https://rech.com.gt/detalle_producto.php?id=8028") is True
    assert es_url_producto_directa_valida("https://guatemaladigital.com/Producto/14399878") is True
    assert es_url_producto_directa_valida("https://www.pacifiko.com/compras-en-linea/laptop-hp&pid=YjU4ZTk1N2") is True

    # 2. Plantillas de búsqueda adivinadas que producen 404 o páginas genéricas son rechazadas
    assert es_url_producto_directa_valida("https://www.click.gt/buscar?q=Canon+T7") is False
    assert es_url_producto_directa_valida("https://www.kemik.gt/busqueda?q=Canon+T7") is False
    assert es_url_producto_directa_valida("https://www.intelaf.com/buscar/?q=Canon+T7") is False
    assert es_url_producto_directa_valida("https://www.rech.com.gt/?s=Mousepad&post_type=product") is False
    assert es_url_producto_directa_valida("https://guatemaladigital.com/Busqueda?Busqueda=Canon+T7") is False
    assert es_url_producto_directa_valida("https://www.pacifiko.com/compras-en-linea/Canon+EOS+Rebel+T7") is False

    # 3. resolver_url_saliente_segura conserva la URL directa en HTTPS sin reescribirla a una búsqueda falsa
    assert (
        resolver_url_saliente_segura("http://click.gt/products/laptop-asus", "click", "Laptop ASUS")
        == "https://click.gt/products/laptop-asus"
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


def test_v5_5_app_shell_skeleton_loading_css_estatico_y_health_ultraligero() -> None:
    from fastapi.testclient import TestClient
    from radar_ofertas.interfaces.api.app import (
        CACHE_NEON_TTL_SEGUNDOS,
        PAGINACION_DESTACADOS_DEFAULT,
        TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S,
        app,
    )

    # 1. Validar constantes arquitectónicas v5.5 (TTL 5m, paginación 28, timeout vivo 9s)
    assert CACHE_NEON_TTL_SEGUNDOS == 300.0
    assert 24 <= PAGINACION_DESTACADOS_DEFAULT <= 32
    assert TIMEOUT_GLOBAL_BUSQUEDA_VIVO_S == 9.0

    client = TestClient(app)

    # 2. Endpoint ultraligero GET /health sin tocar base de datos
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    datos_health = resp_health.json()
    assert datos_health["status"] == "ok"
    assert datos_health["version"] == "5.5.0"
    assert datos_health["db_touched"] is False

    # 3. Recurso estático minificado /static/styles.css servido directamente
    resp_css = client.get("/static/styles.css")
    assert resp_css.status_code == 200
    assert ".skeleton-shimmer" in resp_css.text
    assert ".live-progress-bar" in resp_css.text
    assert ".apple-card" in resp_css.text

    # 4. GET / entrega inmediatamente el App Shell v5.5 con Skeleton Cards y sin cdn.tailwindcss.com
    resp_home = client.get("/?q=Canon+EOS+Rebel+T7")
    assert resp_home.status_code == 200
    html = resp_home.text
    assert "cdn.tailwindcss.com" not in html
    assert '/static/styles.css?v=5.5.0' in html
    assert 'id="skeleton-grid"' in html
    assert 'class="skeleton-card' in html
    assert "Consultando catálogos en vivo en Guatemala..." in html
    assert "/api/buscar-en-vivo" in html
    assert "hidratarAppShellDesdeNeon()" in html
    assert "GT v5.5" in html


def test_v5_5_busqueda_en_vivo_urls_directas_reales_y_cola_pendientes(
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient
    from radar_ofertas.domain.entities.oferta_local import OfertaLocal
    from radar_ofertas.interfaces.api import app as app_module
    from radar_ofertas.interfaces.api.app import (
        app,
        ejecutar_busqueda_en_vivo_acotada,
    )

    class _ScraperRealMock:
        def __init__(self, tienda: str, lotes: list[OfertaLocal]) -> None:
            self.tienda = tienda
            self.lotes = lotes

        async def buscar_producto(self, query: str) -> list[OfertaLocal]:
            return self.lotes

    def _scrapers_mock_v5_5(timeout_individual_s: int = 8):
        return [
            (
                "Guatemala Digital",
                _ScraperRealMock(
                    "Guatemala Digital",
                    [
                        OfertaLocal(
                            titulo="Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP con Lente 18-55mm",
                            precio_gtq=Decimal("4195.00"),
                            url="https://guatemaladigital.com/Producto/16123991",
                            imagen_url="https://m.media-amazon.com/images/I/71EWRyqzw0L._AC_SL1500_.jpg",
                            tienda="Guatemala Digital",
                        )
                    ],
                ),
            ),
            (
                "Pacifiko",
                _ScraperRealMock(
                    "Pacifiko",
                    [
                        OfertaLocal(
                            titulo="Cámara Digital Canon EOS Rebel T7 DSLR 24.1MP Wi-Fi",
                            precio_gtq=Decimal("4350.00"),
                            url="https://www.pacifiko.com/compras-en-linea/camara-canon-eos-rebel-t7&pid=YjU4ZTk1N2",
                            imagen_url="https://img.pacifiko.com/PROD/resize/1/500x500/canon_t7.jpg",
                            tienda="Pacifiko",
                        )
                    ],
                ),
            ),
            (
                "Click Guatemala",
                _ScraperRealMock(
                    "Click Guatemala",
                    [
                        # Si un scraper devuelve una URL de búsqueda falsa (/buscar?q=...), el motor v5.5 la rechaza
                        OfertaLocal(
                            titulo="Cámara Digital Canon EOS Rebel T7 Falsa",
                            precio_gtq=Decimal("3999.00"),
                            url="https://www.click.gt/buscar?q=Canon+T7",
                            imagen_url="",
                            tienda="Click Guatemala",
                        )
                    ],
                ),
            ),
        ]

    monkeypatch.setattr(
        app_module, "_construir_scrapers_busqueda_en_vivo", _scrapers_mock_v5_5
    )
    monkeypatch.setenv("DATABASE_URL", "")

    client = TestClient(app)

    resp_canon = client.post("/api/buscar-en-vivo", json={"query": "canon t7"})
    assert resp_canon.status_code == 200
    data_canon = resp_canon.json()
    assert data_canon["status"] == "ok"
    assert data_canon["version"] == "5.5.0"
    assert len(data_canon["ofertas"]) == 2
    tiendas_canon = {o["tienda"] for o in data_canon["ofertas"]}
    assert tiendas_canon == {"Guatemala Digital", "Pacifiko"}
    # La oferta con URL de búsqueda (/buscar?q=...) fue rechazada por es_url_producto_directa_valida
    assert "Click Guatemala" not in tiendas_canon
    for o in data_canon["ofertas"]:
        assert o["url"].startswith("https://")
        assert "/buscar?q=" not in o["url"]

    # Cuando una búsqueda devuelve 0 resultados reales, se registra en busquedas_pendientes
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
            scrapers=[("Kemik", _ScraperRealMock("Kemik", []))],
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




