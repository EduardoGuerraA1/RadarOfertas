"""
Módulo de Datos Semilla y Matriz de E-Commerce de Guatemala (tecHunter GT v5.0).

Contiene:
1. `seed_list_guatemala`: Matriz oficial de productos de alta demanda en Guatemala
   organizada en los 5 verticales estratégicos (Cómputo y Laptops, Smartphones,
   Línea Blanca y Hogar, Herramientas y Ferretería, Supermercado y Mascotas).
2. `tiendas_ecommerce_guatemala`: Matriz integral de tiendas e-commerce en Guatemala
   clasificada en 6 segmentos de mercado.
3. Funciones de cruce automático (`cruzar_matriz_tiendas_y_prioridades`) que comparan
   la matriz nacional contra las 18 tiendas actualmente operativas en tecHunter GT
   e identifican las siguientes 3 tiendas de alta prioridad para desarrollo.
"""
from __future__ import annotations

from typing import Any

seed_list_guatemala: dict[str, list[str]] = {
    "computo_y_laptops": [
        # Apple
        "MacBook Air M1 8GB 256GB",
        "MacBook Air M2 8GB 256GB",
        "MacBook Air M3 16GB 512GB",
        "MacBook Pro M3 14 pulgadas",
        "iPad 10ma generacion 64GB",
        "iPad Air M2 11 pulgadas",
        # Laptops Gaming (Alta rotación en Guatemala)
        "Laptop Asus TUF Gaming F15 RTX 3050",
        "Laptop Asus TUF Gaming A15 Ryzen 7",
        "Laptop Asus ROG Strix G16",
        "Laptop Acer Nitro V 15 RTX 4050",
        "Laptop Acer Nitro 5 Core i5",
        "Laptop HP Victus 15 Ryzen 5",
        "Laptop HP Victus 16 Core i7",
        "Laptop Lenovo LOQ 15 RTX 4050",
        "Laptop MSI Thin GF63 Core i5",
        # Laptops Productividad / Estudio / Oficina
        "Laptop HP Pavilion 15 Core i5",
        "Laptop HP 250 G9 Core i5",
        "Laptop HP 15 Ryzen 5 16GB",
        "Laptop Lenovo IdeaPad Slim 3 Core i5",
        "Laptop Lenovo IdeaPad 1 Ryzen 5",
        "Laptop Lenovo ThinkPad E14 Core i7",
        "Laptop Dell Inspiron 15 3520 Core i5",
        "Laptop Dell Latitude 3440 Core i5",
        "Laptop Asus VivoBook 15 Core i5",
        # Periféricos y Monitores de alta demanda
        "Monitor Gamer Samsung Odyssey G3 24 pulgadas",
        "Monitor LG UltraGear 24 pulgadas 144Hz",
        "Monitor Dell 24 pulgadas IPS",
        "Impresora Epson EcoTank L3250",
        "Impresora Canon Pixma G3110",
        "Impresora HP Smart Tank 580",
        "Disco Solido SSD Kingston NV2 1TB",
        "Memoria RAM DDR4 16GB laptop",
        # Mousepads Gamer y Profesionales (v5.2)
        "Mousepad Gamer Logitech G840 XL",
        "Mousepad Gamer HyperX Fury S Pro XL",
        "Mousepad Gamer Razer Gigantus V2 Large",
        "Mousepad Gamer Corsair MM300 Pro Extendido",
        "Mousepad Redragon Flick XL",
        # Teclados Mecánicos (v5.2)
        "Teclado Mecanico Logitech G Pro X TKL",
        "Teclado Mecanico Redragon Kumara K552 RGB",
        "Teclado Mecanico HyperX Alloy Origins Core",
        "Teclado Mecanico Razer BlackWidow V4",
        "Teclado Mecanico Keychron K2 Wireless",
        # Diademas Gamer / Headsets (v5.2)
        "Diadema Gamer HyperX Cloud III",
        "Diadema Gamer Logitech G733 Lightspeed Wireless",
        "Diadema Gamer Logitech G435 Bluetooth",
        "Diadema Gamer Razer BlackShark V2 X",
        "Diadema Gamer Redragon Zeus X H510",
        # Webcams Streaming y Oficina (v5.2)
        "Webcam Logitech C920s Pro Full HD 1080p",
        "Webcam Logitech Brio 4K Ultra HD",
        "Webcam Logitech C270 HD",
        "Webcam Razer Kiyo X Full HD",
    ],
    "smartphones": [
        # Apple iPhone
        "iPhone 13 128GB",
        "iPhone 14 128GB",
        "iPhone 15 128GB",
        "iPhone 15 Pro Max 256GB",
        "iPhone 16 128GB",
        "iPhone 16 Pro 256GB",
        "iPhone 16 Pro Max 256GB",
        # Samsung Galaxy (Series S y A dominan el mercado GT)
        "Samsung Galaxy S23 FE 128GB",
        "Samsung Galaxy S24 256GB",
        "Samsung Galaxy S24 Ultra 256GB",
        "Samsung Galaxy S24 Ultra 512GB",
        "Samsung Galaxy A55 5G 256GB",
        "Samsung Galaxy A35 5G 128GB",
        "Samsung Galaxy A25 5G 128GB",
        "Samsung Galaxy A15 128GB",
        "Samsung Galaxy A05s 128GB",
        # Xiaomi / Redmi / Poco
        "Xiaomi Redmi Note 13 256GB",
        "Xiaomi Redmi Note 13 Pro 5G 256GB",
        "Xiaomi Redmi Note 13 Pro Plus 512GB",
        "Xiaomi Redmi 13C 256GB",
        "Xiaomi 14T 512GB",
        "Xiaomi Poco X6 Pro 5G 512GB",
        "Xiaomi Poco M6 Pro 256GB",
        # Honor (Fuerte crecimiento en retail GT)
        "Honor Magic 6 Lite 256GB",
        "Honor X8b 256GB",
        "Honor X7b 256GB",
        "Honor 200 Lite 256GB",
        "Honor 200 5G 256GB",
        # Motorola
        "Motorola Edge 40 Neo 256GB",
        "Motorola Edge 50 Fusion 256GB",
        "Motorola Moto G84 5G 256GB",
        "Motorola Moto G54 5G 256GB",
        "Motorola Moto G24 Power 256GB",
    ],
    "linea_blanca_y_hogar": [
        # Refrigeradoras (En GT se busca mucho por pies cúbicos y Top Mount / Side by Side)
        "Refrigeradora Mabe 11 pies",
        "Refrigeradora Mabe 14 pies No Frost",
        "Refrigeradora LG 11 pies Top Freezer",
        "Refrigeradora LG 14 pies Inverter",
        "Refrigeradora LG Side by Side 22 pies",
        "Refrigeradora Samsung 11 pies Digital Inverter",
        "Refrigeradora Samsung 14 pies Top Mount",
        "Refrigeradora Samsung Bespoke Side by Side",
        "Refrigeradora Whirlpool 14 pies",
        "Congelador horizontal Mabe 7 pies",
        # Estufas (En Guatemala predominan las de gas de 20 y 30 pulgadas)
        "Estufa de gas Mabe 30 pulgadas",
        "Estufa de gas Mabe 20 pulgadas",
        "Estufa de gas Whirlpool 30 pulgadas",
        "Estufa de gas LG 30 pulgadas",
        "Estufa de gas Frigidaire 30 pulgadas",
        "Estufa electrica Mabe 30 pulgadas",
        # Lavadoras y Secadoras (Muy buscadas por capacidad en libras o kg)
        "Lavadora Mabe 18 kg",
        "Lavadora Mabe 20 kg Aqua Saver",
        "Lavadora LG 19 kg Carga Superior",
        "Lavadora LG 22 kg Inverter",
        "Lavadora Samsung 19 kg Wobble",
        "Lavadora Samsung 22 kg Digital Inverter",
        "Lavadora Whirlpool 18 kg",
        "Torre de lavado LG WashTower",
        "Secadora de gas Mabe 20 kg",
        # Microondas y Pequeños Electrodomésticos
        "Horno microondas LG 1.1 pies",
        "Horno microondas Samsung 1.1 pies",
        "Horno microondas Panasonic 1.2 pies",
        "Horno microondas Whirlpool 1.1 pies",
        "Freidora de aire Ninja 4 cuartos",
        "Freidora de aire Oster 4 litros",
        "Licuadora Oster reversible",
        "Cafetera Oster 12 tazas",
        "Aspiradora robot Xiaomi",
        # Cámaras de Seguridad para el Hogar / Smart Home (v5.2)
        "Camara de seguridad TP-Link Tapo C200 360 WiFi",
        "Camara de seguridad TP-Link Tapo C210 2K 3MP",
        "Camara de seguridad exterior TP-Link Tapo C310",
        "Camara de seguridad exterior TP-Link Tapo C500 360",
        "Camara de seguridad Ezviz C6N 1080p 360 Smart",
        "Camara de seguridad exterior Ezviz H8C 2K Pan Tilt",
        "Camara de seguridad exterior Ezviz C3TN Color Night",
        "Camara de seguridad Xiaomi Smart Camera C300 2K",
        "Camara de seguridad Nexxt Solutions Smart WiFi",
    ],
    "herramientas_y_ferreteria": [
        # Taladros y Rotomartillos
        "Taladro percutor inalambrico DeWalt 20V",
        "Taladro atornillador DeWalt 20V brushless",
        "Taladro percutor Milwaukee M18",
        "Taladro percutor Bosch GSB 13 RE",
        "Taladro inalambrico Bosch 18V",
        "Taladro percutor Truper 1/2 pulgada",
        "Taladro inalambrico Truper 20V",
        "Taladro percutor Stanley 1/2 pulgada",
        "Rotomartillo SDS Plus DeWalt",
        "Rotomartillo Bosch GBH 2-26",
        # Esmeriladoras (Pulidoras)
        "Esmeriladora angular DeWalt 4 1/2 pulgadas",
        "Esmeriladora angular Bosch 4 1/2 pulgadas",
        "Esmeriladora angular Milwaukee 4 1/2 pulgadas",
        "Esmeriladora angular Truper 4 1/2 pulgadas",
        "Esmeriladora angular Stanley 4 1/2 pulgadas",
        # Sierras
        "Sierra circular DeWalt 7 1/4 pulgadas",
        "Sierra circular Bosch 7 1/4 pulgadas",
        "Sierra circular Truper 7 1/4 pulgadas",
        "Sierra caladora Bosch",
        "Sierra caladora DeWalt",
        "Sierra ingletadora DeWalt 12 pulgadas",
        # Herramienta Manual, Medición y Equipos
        "Juego de herramientas mecanicas Stanley",
        "Juego de herramientas Truper 100 piezas",
        "Nivel laser Bosch",
        "Nivel laser DeWalt",
        "Soldadora inverter Truper",
        "Compresor de aire Truper 25 litros",
        "Hidrolavadora Karcher K2",
        "Hidrolavadora Karcher K3",
        "Hidrolavadora Truper",
    ],
    "supermercado_y_mascotas": [
        # Alimento para Perros (En GT se mide por libras o kilogramos según marca)
        "Alimento para perro Pedigree adulto 21 kg",
        "Alimento para perro Pedigree cachorro 4 kg",
        "Alimento para perro Purina Dog Chow adulto 21 kg",
        "Alimento para perro Purina Dog Chow cachorro 8 kg",
        "Alimento para perro Purina Pro Plan adulto 15 kg",
        "Alimento para perro Beneful 15 kg",
        "Alimento para perro Rufo 40 libras",
        "Alimento para perro Rambo 44 libras",
        "Alimento para perro Royal Canin",
        # Alimento para Gatos
        "Alimento para gato Whiskas 10 kg",
        "Alimento para gato Purina Cat Chow 8 kg",
        "Alimento para gato Felix 10 kg",
        "Arena para gato Scoop Away",
        "Arena para gato Tidy Cats",
        # Café (Categoría estrella en Guatemala)
        "Cafe molido Incaparina",
        "Cafe molido El Cafetalito 400g",
        "Cafe molido Quetzal 400g",
        "Cafe molido Leon 400g",
        "Cafe soluble Nescafe Clasico 200g",
        "Cafe soluble Musun",
        "Cafe en grano Antigua Guatemala",
        # Abarrotes Básicos y Canasta Básica GT
        "Incaparina original 450g",
        "Frijoles volteados Ducal 29 oz",
        "Frijoles negros Malher",
        "Arroz blanco Gallo Dorado 5 libras",
        "Aceite vegetal Ideal 3 litros",
        "Aceite Olmeca 3 litros",
        "Azucar Caña Real 2.5 kg",
        "Leche entera Dos Pinos 1 litro",
        "Leche entera Trebolac 1 litro",
        "Atun en agua Mazatun",
        "Salsa de tomate Naturas",
        "Cereal Corn Flakes Kellogg's",
    ],
}

tiendas_ecommerce_guatemala: dict[str, list[dict[str, Any]]] = {
    "1_departamentales_y_marketplaces": [
        # Los agregadores y tiendas por departamento con mayor catálogo transversal
        {
            "nombre": "Max Distelsa",
            "url": "https://www.max.com.gt",
            "verticales": ["computo", "smartphones", "linea_blanca", "gaming"],
        },
        {
            "nombre": "Kemik",
            "url": "https://www.kemik.gt",
            "verticales": ["computo", "smartphones", "hogar", "mascotas", "herramientas"],
        },
        {
            "nombre": "Pacifiko",
            "url": "https://www.pacifiko.com",
            "verticales": ["computo", "smartphones", "hogar", "mascotas", "supermercado"],
        },
        {
            "nombre": "Cemaco",
            "url": "https://www.cemaco.com",
            "verticales": ["hogar", "linea_blanca", "herramientas", "mascotas"],
        },
        {
            "nombre": "Siman Guatemala",
            "url": "https://gt.siman.com",
            "verticales": ["smartphones", "linea_blanca", "hogar", "computo"],
        },
        {
            "nombre": "Elektra Guatemala",
            "url": "https://www.elektra.com.gt",
            "verticales": ["smartphones", "linea_blanca", "computo", "motos"],
        },
        {
            "nombre": "La Curacao",
            "url": "https://www.lacuracaonline.com/guatemala",
            "verticales": ["linea_blanca", "smartphones", "computo", "hogar"],
        },
        {
            "nombre": "Tropigas",
            "url": "https://www.almacenestropigas.com/guatemala",
            "verticales": ["linea_blanca", "smartphones", "hogar"],
        },
        {
            "nombre": "El Gallo Más Gallo",
            "url": "https://www.elgallomasgallo.com.gt",
            "verticales": ["linea_blanca", "smartphones", "computo"],
        },
        {
            "nombre": "Agencias Way",
            "url": "https://agenciasway.com.gt",
            "verticales": ["linea_blanca", "smartphones", "hogar"],
        },
    ],
    "2_especialistas_computo_y_tecnologia": [
        # Clave para comparar precios agresivos en hardware, laptops y componentes
        {
            "nombre": "Intelaf",
            "url": "https://www.intelaf.com",
            "verticales": ["computo", "smartphones", "gaming"],
        },
        {
            "nombre": "Macrosistemas",
            "url": "https://www.macrosistemas.com",
            "verticales": ["computo", "gaming", "oficina"],
        },
        {
            "nombre": "Click Guatemala",
            "url": "https://www.click.gt",
            "verticales": ["computo", "smartphones", "gaming"],
        },
        {
            "nombre": "iShop Guatemala",
            "url": "https://ishop.gt",
            "verticales": ["apple", "smartphones", "computo"],
        },
        {
            "nombre": "iCon Guatemala",
            "url": "https://icongt.com",
            "verticales": ["apple", "smartphones", "computo"],
        },
        {
            "nombre": "TechStore Guatemala",
            "url": "https://techstore.com.gt",
            "verticales": ["computo", "gaming"],
        },
        {
            "nombre": "Rech Guatemala",
            "url": "https://www.rech.com.gt",
            "verticales": ["computo", "gaming", "perifericos"],
        },
        {
            "nombre": "Tera Guatemala",
            "url": "https://www.tera.gt",
            "verticales": ["computo", "gaming", "componentes"],
        },
        {
            "nombre": "Spirit Computación",
            "url": "https://www.spiritcomputacion.com",
            "verticales": ["computo", "oficina"],
        },
        {
            "nombre": "Guatemaladigital",
            "url": "https://guatemaladigital.com",
            "verticales": ["computo", "smartphones", "herramientas", "importacion"],
        },
    ],
    "3_telefonia_y_tiendas_oficiales": [
        # Referencia obligatoria para precios base y promociones de operadoras/fabricantes
        {
            "nombre": "Tienda Claro Guatemala",
            "url": "https://tiendaenlinea.claro.com.gt",
            "verticales": ["smartphones"],
        },
        {
            "nombre": "Tienda Tigo Guatemala",
            "url": "https://tienda.tigo.com.gt",
            "verticales": ["smartphones"],
        },
        {
            "nombre": "Samsung Store Guatemala",
            "url": "https://shop.samsung.com/latin/gt",
            "verticales": ["smartphones", "linea_blanca", "computo"],
        },
        {
            "nombre": "Xiaomi Store Guatemala",
            "url": "https://xiaomistore.com.gt",
            "verticales": ["smartphones", "hogar"],
        },
        {
            "nombre": "Fónika",
            "url": "https://fonika.gt",
            "verticales": ["smartphones"],
        },
    ],
    "4_ferreteria_y_construccion": [
        # Alta dispersión de precios en herramienta eléctrica y equipamiento
        {
            "nombre": "Ferretería EPA",
            "url": "https://gt.epa.biz",
            "verticales": ["herramientas", "hogar"],
        },
        {
            "nombre": "Novex Guatemala",
            "url": "https://novex.com.gt",
            "verticales": ["herramientas", "hogar"],
        },
        {
            "nombre": "El Volcán",
            "url": "https://elvolcan.com.gt",
            "verticales": ["herramientas", "industrial"],
        },
        {
            "nombre": "Ferretería Lewonski",
            "url": "https://lewonski.com",
            "verticales": ["herramientas", "industrial"],
        },
        {
            "nombre": "Construred / Ferreterías locales",
            "url": "https://www.ferreteriaelglobo.com",
            "verticales": ["herramientas"],
        },
    ],
    "5_supermercados_y_consumo_masivo": [
        # Alta frecuencia de compra y sensibilidad al precio en canasta básica
        {
            "nombre": "Walmart Guatemala",
            "url": "https://www.walmart.com.gt",
            "verticales": ["supermercado", "mascotas", "linea_blanca", "smartphones"],
        },
        {
            "nombre": "Paiz Guatemala",
            "url": "https://www.paiz.com.gt",
            "verticales": ["supermercado", "mascotas"],
        },
        {
            "nombre": "Supermercados La Torre",
            "url": "https://www.latorre.com.gt",
            "verticales": ["supermercado", "mascotas"],
        },
        {
            "nombre": "Supermercados Suma",
            "url": "https://www.supermercadossuma.com",
            "verticales": ["supermercado", "mascotas"],
        },
        {
            "nombre": "Pricesmart Guatemala",
            "url": "https://www.pricesmart.com/site/gt/es",
            "verticales": ["supermercado", "linea_blanca", "computo", "mascotas"],
        },
    ],
    "6_especialistas_mascotas_y_nicho": [
        # Ideales para cruzar contra supermercados en alimento de perro/gato
        {
            "nombre": "Arca de Noé",
            "url": "https://arcadenoe.com.gt",
            "verticales": ["mascotas"],
        },
        {
            "nombre": "La Casa del Perro",
            "url": "https://lacasadelperro.com.gt",
            "verticales": ["mascotas"],
        },
        {
            "nombre": "Petco Guatemala",
            "url": "https://www.petco.com.gt",
            "verticales": ["mascotas"],
        },
        {
            "nombre": "Office Depot Guatemala",
            "url": "https://www.officedepot.com.gt",
            "verticales": ["computo", "oficina"],
        },
    ],
}

# Las 24 tiendas actualmente operativas en tecHunter GT v5.2 (con su slug en Neon DB)
TIENDAS_OPERATIVAS_TECHUNTER: tuple[dict[str, str], ...] = (
    {"slug": "tiendas-max", "nombre": "Tiendas Max", "alias_matriz": "Max Distelsa", "url": "https://www.max.com.gt"},
    {"slug": "tecno-facil", "nombre": "Tecno Fácil", "alias_matriz": "Tecno Fácil (Grupo Distelsa)", "url": "https://www.tecnofacil.com.gt"},
    {"slug": "kemik", "nombre": "Kemik", "alias_matriz": "Kemik", "url": "https://www.kemik.gt"},
    {"slug": "pacifiko", "nombre": "Pacifiko", "alias_matriz": "Pacifiko", "url": "https://www.pacifiko.com"},
    {"slug": "cemaco", "nombre": "Cemaco", "alias_matriz": "Cemaco", "url": "https://www.cemaco.com"},
    {"slug": "siman", "nombre": "Siman", "alias_matriz": "Siman Guatemala", "url": "https://gt.siman.com"},
    {"slug": "elektra", "nombre": "Elektra", "alias_matriz": "Elektra Guatemala", "url": "https://www.elektra.com.gt"},
    {"slug": "la-curacao", "nombre": "La Curacao", "alias_matriz": "La Curacao", "url": "https://www.lacuracaonline.com/guatemala"},
    {"slug": "tropigas", "nombre": "Tropigas", "alias_matriz": "Tropigas", "url": "https://www.almacenestropigas.com/guatemala"},
    {"slug": "intelaf", "nombre": "Intelaf", "alias_matriz": "Intelaf", "url": "https://www.intelaf.com"},
    {"slug": "rech", "nombre": "Rech", "alias_matriz": "Rech Guatemala", "url": "https://www.rech.com.gt"},
    {"slug": "click", "nombre": "Click Guatemala", "alias_matriz": "Click Guatemala", "url": "https://www.click.gt"},
    {"slug": "tera", "nombre": "Tera", "alias_matriz": "Tera Guatemala", "url": "https://www.tera.gt"},
    {"slug": "office-depot", "nombre": "Office Depot", "alias_matriz": "Office Depot Guatemala", "url": "https://www.officedepot.com.gt"},
    {"slug": "istore", "nombre": "iStore", "alias_matriz": "iShop Guatemala", "url": "https://ishop.gt"},
    {"slug": "ishop", "nombre": "iShop", "alias_matriz": "iShop Guatemala", "url": "https://ishop.gt"},
    {"slug": "tienda-claro", "nombre": "Tienda Claro", "alias_matriz": "Tienda Claro Guatemala", "url": "https://www.claro.com.gt"},
    {"slug": "tienda-tigo", "nombre": "Tienda Tigo", "alias_matriz": "Tienda Tigo Guatemala", "url": "https://tienda.tigo.com.gt"},
    {"slug": "epa", "nombre": "EPA", "alias_matriz": "Ferretería EPA", "url": "https://gt.epaenlinea.com"},
    {"slug": "novex", "nombre": "Novex", "alias_matriz": "Novex Guatemala", "url": "https://www.novex.com.gt"},
    {"slug": "walmart", "nombre": "Walmart", "alias_matriz": "Walmart Guatemala", "url": "https://www.walmart.com.gt"},
    {"slug": "paiz", "nombre": "Paiz", "alias_matriz": "Paiz Guatemala", "url": "https://www.paiz.com.gt"},
    {"slug": "maxi-despensa", "nombre": "Maxi Despensa", "alias_matriz": "Maxi Despensa (Grupo Walmart)", "url": "https://www.maxidespensa.com.gt"},
    {"slug": "la-torre", "nombre": "La Torre", "alias_matriz": "Supermercados La Torre", "url": "https://www.latorre.com.gt"},
    {"slug": "pricesmart", "nombre": "PriceSmart", "alias_matriz": "Pricesmart Guatemala", "url": "https://www.pricesmart.com/en-GT"},
)

MAPEO_CATEGORIA_SEED_A_DB: dict[str, str] = {
    "computo_y_laptops": "tecnologia",
    "smartphones": "tecnologia",
    "linea_blanca_y_hogar": "hogar",
    "herramientas_y_ferreteria": "hogar",
    "supermercado_y_mascotas": "mascotas",
}


def obtener_todos_los_productos_semilla() -> list[tuple[str, str, str]]:
    """
    Retorna la lista plana de tuplas `(categoria_seed, categoria_db, termino_producto)`
    para los productos de alta demanda en Guatemala.
    """
    resultado: list[tuple[str, str, str]] = []
    for cat_seed, productos in seed_list_guatemala.items():
        cat_db = MAPEO_CATEGORIA_SEED_A_DB.get(cat_seed, "tecnologia")
        for prod in productos:
            resultado.append((cat_seed, cat_db, prod))
    return resultado


def cruzar_matriz_tiendas_y_prioridades() -> dict[str, Any]:
    """
    Cruza automáticamente `tiendas_ecommerce_guatemala` con las 24 tiendas operativas
    de tecHunter GT v5.2 (incluyendo los especialistas en cómputo Rech Guatemala,
    Click Guatemala y Tera Guatemala) e identifica las siguientes tiendas en el backlog.
    """
    nombres_operativos_norm = {
        t["alias_matriz"].strip().lower() for t in TIENDAS_OPERATIVAS_TECHUNTER
    } | {t["nombre"].strip().lower() for t in TIENDAS_OPERATIVAS_TECHUNTER}

    dominios_operativos = (
        "max.com.gt",
        "tecnofacil.com.gt",
        "kemik.gt",
        "pacifiko.com",
        "cemaco.com",
        "siman.com",
        "elektra.com.gt",
        "lacuracaonline.com",
        "almacenestropigas.com",
        "intelaf.com",
        "rech.com.gt",
        "click.gt",
        "tera.gt",
        "officedepot.com.gt",
        "ishop.gt",
        "claro.com.gt",
        "tienda.tigo.com.gt",
        "epa.biz",
        "epaenlinea.com",
        "novex.com.gt",
        "walmart.com.gt",
        "paiz.com.gt",
        "maxidespensa.com.gt",
        "latorre.com.gt",
        "pricesmart.com",
    )

    tiendas_activas_en_matriz: list[dict[str, Any]] = []
    tiendas_pendientes: list[dict[str, Any]] = []

    pesos_prioridad_estrategica: dict[str, tuple[int, str]] = {
        "El Gallo Más Gallo": (
            92,
            "Prioridad #1 en backlog: Fuerte competidor nacional en línea blanca, pantallas y smartphones.",
        ),
        "Arca de Noé": (
            88,
            "Prioridad #2 en backlog: Especialista líder en mascotas en Guatemala para cruzar alimento contra La Torre y Walmart.",
        ),
        "Samsung Store Guatemala": (
            85,
            "Prioridad #3 en backlog: Tienda oficial directa de Samsung para precios de referencia en Galaxy S/A y Bespoke.",
        ),
    }

    for segmento, lista_tiendas in tiendas_ecommerce_guatemala.items():
        for tienda in lista_tiendas:
            nombre = str(tienda.get("nombre") or "").strip()
            url = str(tienda.get("url") or "").strip()
            verticales = list(tienda.get("verticales") or [])

            es_operativa = (
                nombre.lower() in nombres_operativos_norm
                or any(dom in url.lower() for dom in dominios_operativos)
            )

            registro = {
                "nombre": nombre,
                "url": url,
                "segmento": segmento,
                "verticales": verticales,
                "estado": "operativa" if es_operativa else "pendiente",
            }

            if es_operativa:
                tiendas_activas_en_matriz.append(registro)
            else:
                puntaje_base = len(verticales) * 10
                extra_score, justificacion = pesos_prioridad_estrategica.get(
                    nombre,
                    (
                        puntaje_base,
                        f"Cobertura en {', '.join(verticales)} dentro del segmento {segmento}.",
                    ),
                )
                registro["puntaje_prioridad"] = extra_score
                registro["justificacion"] = justificacion
                tiendas_pendientes.append(registro)

    tiendas_pendientes.sort(key=lambda x: int(x.get("puntaje_prioridad", 0)), reverse=True)
    siguientes_3_alta_prioridad = tiendas_pendientes[:3]

    return {
        "total_operativas_sistema": 24,
        "tiendas_recien_activadas_v5_1": [
            "Tienda Tigo Guatemala",
            "Office Depot Guatemala",
            "Tropigas",
        ],
        "tiendas_recien_activadas_v5_2": [
            "Rech Guatemala",
            "Click Guatemala",
            "Tera Guatemala",
        ],
        "total_catalogo_matriz": len(tiendas_activas_en_matriz) + len(tiendas_pendientes),
        "operativas_cruzadas": tiendas_activas_en_matriz,
        "pendientes_ordenadas": tiendas_pendientes,
        "siguientes_3_alta_prioridad": siguientes_3_alta_prioridad,
    }
