"""
Servicio de Dominio: Filtro Inteligente Anti-Ruido y Motor de Precisión de Modelos (v4.0).

1. Descarta automáticamente accesorios, repuestos o consumibles secundarios
   (correas, bands, protectores, micas, estuches, cables, carbones, mandriles, brocas sueltas, etc.)
   cuando el usuario busca un dispositivo o herramienta principal.
2. Motor de Precisión de Modelos y Especificaciones:
   - Cuando el usuario busca un modelo específico de laptop, smartphone o herramienta
     (ej. 'MacBook Air M2', 'Taladro DeWalt DCD776', 'iPhone 16 Pro'), exige coincidencia
     estricta de marca/modelo para evitar mezclar equipos de gama baja (ej. HP Stream Celeron)
     con equipos profesionales.
   - Clasifica cada producto en una de las 3 Gamas del diseño v4.0:
     * 'Profesional · Alta Gama' (slug: 'profesional')
     * 'Media · Productividad'   (slug: 'media')
     * 'Entrada · Básica'        (slug: 'entrada')
   - Extrae micro-chips de especificaciones técnicas (ej. ['M2', '8GB', '256GB SSD'],
     ['Ryzen 7', 'RTX 4050', '16GB'], ['20V Max', '1/2"', 'Brushless']).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)

# Palabras y frases negativas que identifican accesorios o repuestos secundarios
PALABRAS_NEGATIVAS_ACCESORIOS: tuple[str, ...] = (
    # Relojes / Smartwatches / Celulares / Consolas
    "correa",
    "correas",
    "band",
    "bands",
    "strap",
    "straps",
    "wristband",
    "wristbands",
    "watchband",
    "protector",
    "protectores",
    "screen protector",
    "mica",
    "micas",
    "vidrio templado",
    "tempered glass",
    "protective film",
    "face cover",
    "estuche",
    "estuches",
    "funda",
    "fundas",
    "case",
    "cases",
    "cover",
    "covers",
    "bumper",
    "cable",
    "cables",
    "adaptador",
    "adapter",
    "holder",
    "soporte para",
    "base de carga",
    "charging dock",
    "charging stand",
    "charger cable",
    "cargador para",
    "skin",
    "sticker",
    "calcomania",
    "llavero",
    "keychain",
    "replacement",
    "repuesto",
    "repuestos",
    "forro",
    # Laptops / Cómputo (mochilas, mesas plegables, bases enfriadoras, hubs, lectores, etc.)
    "mochila",
    "mochilas",
    "bolso",
    "maletin",
    "mesa plegable",
    "mesa mainstays",
    "ventilador de laptop",
    "base enfriadora",
    "base para laptop",
    "soporte para laptop",
    "cooling pad",
    "usb hub",
    "hub usb",
    "port expander",
    "usb splitter",
    "card reader",
    "lector de tarjeta",
    "external cd",
    "external dvd",
    "dvd drive",
    "convertidor",
    "docking station",
    "screwdriver",
    "repair tool kit",
    "for macbook",
    "for laptop",
    "para macbook",
    "mouse for",
    # Herramientas / Taladros (repuestos, brocas sueltas, discos y accesorios menores)
    "carbones",
    "carbon para",
    "cepillo para taladro",
    "cepillo circular",
    "porta taladro",
    "cinturon porta",
    "mandril",
    "llave para mandril",
    "llave de broquero",
    "broquero",
    "bomba autocebante",
    "dados magneticos",
    "broca",
    "brocas",
    "juego de brocas",
    "set de brocas",
    "disco corte",
    "disco de corte",
    "discos de corte",
    "carda",
    "cardas",
    "copa de alambre",
    "para taladro",
    "set de accesorios",
    "juego de accesorios",
    "rueda flap",
    "cargador 12",
    "cargador para 12v",
    "dispensador",
    "repisa",
    "toallero",
    "play doh",
    "dentista",
)

# Términos que activan el modo estricto de dispositivo principal
DISPOSITIVOS_PRINCIPALES_TRIGGERS: tuple[str, ...] = (
    "watch",
    "reloj",
    "smartwatch",
    "galaxy",
    "iphone",
    "telefono",
    "celular",
    "smartphone",
    "volante",
    "g29",
    "g920",
    "g923",
    "consola",
    "ps5",
    "playstation",
    "xbox",
    "nintendo",
    "switch",
    "laptop",
    "macbook",
    "tablet",
    "ipad",
    "monitor",
    "televisor",
    "taladro",
    "barreno",
    "rotomartillo",
    "esmeriladora",
)

# Tokens de marca/familia o modelo que, si aparecen en el query del usuario,
# DEBEN estar presentes en el título del producto para evitar comparaciones disparejas.
TOKENS_MARCA_Y_FAMILIA_ESTRICTOS: frozenset[str] = frozenset(
    {
        # Marcas de Cómputo, Periféricos Gamer y Cámaras Smart Home
        "apple",
        "macbook",
        "imac",
        "iphone",
        "ipad",
        "airpods",
        "razer",
        "hyperx",
        "redragon",
        "corsair",
        "keychron",
        "logitech",
        "tapo",
        "ezviz",
        "nexxt",
        "kingston",
        "asus",
        "lenovo",
        "hp",
        "dell",
        "acer",
        "msi",
        "epson",
        "canon",
        "samsung",
        "lg",
        "sony",
        "xiaomi",
        "redmi",
        "poco",
        "honor",
        "motorola",
        "hisense",
        "tcl",
        "jbl",
        "bose",
        "garmin",
        # Líneas y familias de modelos de Cómputo y Periféricos
        "gigantus",
        "fury",
        "flick",
        "kumara",
        "blackwidow",
        "origins",
        "blackshark",
        "zeus",
        "kiyo",
        "brio",
        "lightspeed",
        "odyssey",
        "ultragear",
        "ecotank",
        "pixma",
        "loq",
        "thinkpad",
        "ideapad",
        "legion",
        "vivobook",
        "zenbook",
        "tuf",
        "rog",
        "pavilion",
        "victus",
        "omen",
        "inspiron",
        "latitude",
        "xps",
        "alienware",
        "nitro",
        "aspire",
        "predator",
        # Marcas de Herramientas, Línea Blanca y Supermercado
        "dewalt",
        "bosch",
        "makita",
        "milwaukee",
        "truper",
        "pretul",
        "stanley",
        "karcher",
        "emtop",
        "mabe",
        "whirlpool",
        "frigidaire",
        "oster",
        "ninja",
        "ps5",
        "xbox",
        "nintendo",
        "pedigree",
        "purina",
        "whiskas",
        "incaparina",
    }
)

# Variantes de tamaño, gama o submodelo que no deben mezclarse cuando se especifican
TOKENS_VARIANTE_ESTRICTOS: frozenset[str] = frozenset(
    {
        "mini",
        "small",
        "medium",
        "large",
        "xl",
        "xxl",
        "extended",
        "extendido",
        "tkl",
        "tenkeyless",
        "wireless",
        "inalambrico",
        "pro",
        "max",
        "ultra",
        "plus",
        "lite",
        "fe",
    }
)

# Grupos de tipo de producto principal para impedir que se mezclen categorías distintas
GRUPOS_TIPO_PRODUCTO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mousepad", ("mousepad", "mouse pad", "alfombrilla")),
    ("teclado", ("teclado", "keyboard")),
    ("diadema", ("diadema", "headset", "audifono", "audifonos")),
    ("webcam", ("webcam", "camara web")),
    ("camara-seguridad", ("camara de seguridad", "tapo c", "ezviz", "nexxt")),
    ("monitor", ("monitor",)),
    ("impresora", ("impresora", "multifuncional", "ecotank", "smart tank", "pixma")),
    ("volante", ("volante", "driving force")),
    ("laptop", ("laptop", "notebook", "macbook", "portatil")),
    ("tablet", ("ipad", "tablet")),
    ("smartwatch", ("galaxy watch", "apple watch", "smartwatch", "reloj inteligente")),
    ("smartphone", ("iphone", "galaxy s", "galaxy a", "galaxy z", "redmi", "poco", "smartphone", "celular")),
    ("ssd", ("ssd", "disco solido", "estado solido", "nvme")),
    ("ram", ("memoria ram", "ddr4", "ddr5")),
    ("refrigeradora", ("refrigeradora", "frigobar", "congelador")),
    ("lavadora", ("lavadora", "secadora", "torre de lavado", "washtower")),
    ("estufa", ("estufa",)),
    ("microondas", ("microondas",)),
    ("freidora", ("freidora",)),
    ("licuadora", ("licuadora",)),
    ("cafetera", ("cafetera",)),
    ("televisor", ("televisor", "smart tv")),
    ("taladro", ("taladro", "rotomartillo", "barreno", "atornillador")),
    ("esmeriladora", ("esmeriladora", "pulidora")),
    ("hidrolavadora", ("hidrolavadora",)),
    ("alimento-mascota", ("pedigree", "purina", "dog chow", "pro plan", "beneful", "whiskas", "alimento para perro", "alimento para gato")),
)

# Plantillas oficiales de búsqueda por tienda para garantizar cero errores 404/500 en enlaces salientes
PLANTILLAS_BUSQUEDA_OFICIAL_TIENDA: dict[str, str] = {
    "rech": "https://www.rech.com.gt/?s={query}&post_type=product",
    "click": "https://www.click.gt/buscar?q={query}",
    "tera": "https://www.tera.com.gt/?s={query}&post_type=product",
    "intelaf": "https://www.intelaf.com/buscar/?q={query}",
    "kemik": "https://www.kemik.gt/busqueda?q={query}",
    "pacifiko": "https://www.pacifiko.com/compras-en-linea/{query}",
    "tiendas-max": "https://www.max.com.gt/catalogsearch/result/?q={query}",
    "tecno-facil": "https://www.tecnofacil.com.gt/catalogsearch/result/?q={query}",
    "tecnofacil": "https://www.tecnofacil.com.gt/catalogsearch/result/?q={query}",
    "istore": "https://ishop.gt/search?q={query}",
    "ishop": "https://ishop.gt/search?q={query}",
    "epa": "https://gt.epaenlinea.com/catalogsearch/result/?q={query}",
    "novex": "https://www.novex.com.gt/busqueda?controller=search&s={query}",
    "cemaco": "https://www.cemaco.com/s?q={query}",
    "office-depot": "https://www.officedepot.com.gt/officedepotGuatemala/es/search/?text={query}",
    "tienda-tigo": "https://tienda.tigo.com.gt/catalogsearch/result/?q={query}",
    "tropigas": "https://www.almacenestropigas.com/guatemala/catalogsearch/result/?q={query}",
    "la-curacao": "https://www.lacuracaonline.com/guatemala/catalogsearch/result/?q={query}",
    "tienda-claro": "https://www.claro.com.gt/personas/servicios/servicios-moviles/prepago/",
    "pricesmart": "https://www.pricesmart.com/en-GT/search?q={query}",
    "siman": "https://gt.siman.com/{query}?_q={query}&map=ft",
    "elektra": "https://www.elektra.com.gt/{query}?_q={query}&map=ft",
    "walmart": "https://www.walmart.com.gt/{query}?_q={query}&map=ft",
    "paiz": "https://www.paiz.com.gt/{query}?_q={query}&map=ft",
    "maxi-despensa": "https://www.maxidespensa.com.gt/{query}?_q={query}&map=ft",
    "la-torre": "https://www.latorre.com.gt/{query}?_q={query}&map=ft",
}


def _normalizar_texto(texto: str) -> str:
    """Convierte a minúsculas y elimina tildes/diacríticos para comparación uniforme."""
    texto_lower = (texto or "").lower().strip()
    descompuesto = unicodedata.normalize("NFD", texto_lower)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _contiene_termino_exacto(texto_normalizado: str, termino_normalizado: str) -> bool:
    """Verifica si `termino_normalizado` aparece como palabra o frase completa en `texto_normalizado`."""
    patron = rf"(?<![a-z0-9]){re.escape(termino_normalizado)}(?![a-z0-9])"
    return re.search(patron, texto_normalizado) is not None


def extraer_termino_busqueda_limpio(titulo: str) -> str:
    """
    Extrae un término de búsqueda conciso y exacto (marca + modelo + especificación clave)
    a partir del título del producto para construir URLs de búsqueda limpias en las tiendas.
    """
    limpio = re.sub(r"\([^)]*\)", " ", titulo or "")
    limpio = re.sub(
        r"\b(con|para|de|el|la|los|las|un|una|color|en|y|o|incluye|tapa|privacidad|costura|reforzada|micro-weave|cloth|spill-proof|premium|multiplataforma|seguimiento|inteligente|vision|nocturna|rotacion|pan/tilt|pan|tilt)\b",
        " ",
        limpio,
        flags=re.IGNORECASE,
    )
    palabras = [p for p in re.findall(r"[A-Za-z0-9ÁÉÍÓÚáéíóúñÑ+./-]+", limpio) if len(p) >= 2]
    seleccion = palabras[:7] if palabras else [titulo.strip()]
    return " ".join(seleccion).strip()


def construir_url_busqueda_tienda(tienda_slug_o_nombre: str, termino: str) -> str:
    """
    Construye la URL oficial de búsqueda de la tienda con el término exacto codificado,
    garantizando que el botón 'Ir a la tienda' nunca caiga en un error 404 o 500.
    """
    from urllib.parse import quote_plus

    slug = _normalizar_texto(tienda_slug_o_nombre).replace(" ", "-")
    if slug in {"click-guatemala", "click-gt"}:
        slug = "click"
    elif slug in {"rech-guatemala", "rech-gt"}:
        slug = "rech"
    elif slug in {"tera-guatemala", "tera-gt"}:
        slug = "tera"
    elif slug == "tecnofacil":
        slug = "tecno-facil"

    termino_limpio = extraer_termino_busqueda_limpio(termino) or (termino or "").strip()
    q_encoded = quote_plus(termino_limpio)
    plantilla = PLANTILLAS_BUSQUEDA_OFICIAL_TIENDA.get(
        slug, f"https://www.{slug}.com.gt/?s={{query}}"
    )
    return plantilla.format(query=q_encoded)


def resolver_url_saliente_segura(url: str, tienda_slug_o_nombre: str, titulo: str) -> str:
    """
    Verifica la URL saliente de un producto. Si la URL directa no puede verificarse con certeza
    (ej. rutas sintéticas `/producto/...` en Rech, Click Guatemala o Tera, dominios antiguos
    `tera.gt`, o URLs vacías/rotas), devuelve la URL oficial de búsqueda de la tienda con el
    término exacto del producto codificado.
    """
    url_limpia = (url or "").strip()
    slug = _normalizar_texto(tienda_slug_o_nombre).replace(" ", "-")
    if slug in {"click-guatemala", "click-gt"}:
        slug = "click"
    elif slug in {"rech-guatemala", "rech-gt"}:
        slug = "rech"
    elif slug in {"tera-guatemala", "tera-gt"}:
        slug = "tera"

    if not url_limpia or not url_limpia.startswith(("http://", "https://")):
        return construir_url_busqueda_tienda(slug, titulo)

    # En Rech, Click Guatemala y Tera, si la URL es un slug sintético (/producto/...) o dominio tera.gt,
    # redirigir siempre a la búsqueda oficial de la tienda con el modelo exacto codificado.
    if slug in {"rech", "click", "tera"}:
        if (
            "/producto/" in url_limpia
            or "tera.gt" in url_limpia
            or url_limpia.rstrip("/") in {
                "https://www.rech.com.gt",
                "https://www.click.gt",
                "https://www.tera.gt",
                "https://www.tera.com.gt",
            }
        ):
            return construir_url_busqueda_tienda(slug, titulo)

    return url_limpia


def _detectar_tipo_producto(texto_norm: str) -> str:
    """Identifica el tipo de producto principal normalizado a partir de un título o query."""
    # Prioridad a accesorios de cómputo si el texto menciona mousepad antes que mouse
    if any(k in texto_norm for k in ("mousepad", "mouse pad", "alfombrilla")):
        return "mousepad"
    for tipo, keywords in GRUPOS_TIPO_PRODUCTO:
        for kw in keywords:
            if _contiene_termino_exacto(texto_norm, kw) or kw in texto_norm:
                return tipo
    return ""


def _extraer_codigos_modelo_query(query_norm: str) -> list[str]:
    """
    Detecta tokens de marca, familia, modelo y variante específicos en la búsqueda del usuario:
    ej. 'razer', 'gigantus', 'v2', 'large', 'g840', 'xl', 'k552', 'm2', 'dcd776', 'tapo', 'c200'.
    """
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", query_norm)
    codigos: list[str] = []
    for tok in tokens:
        if tok in {"de", "la", "el", "en", "con", "para", "por", "del", "los", "las", "un", "una"}:
            continue
        tiene_letra = any(c.isalpha() for c in tok)
        tiene_digito = any(c.isdigit() for c in tok)
        if tiene_letra and tiene_digito and len(tok) >= 2:
            codigos.append(tok)
        elif tok in TOKENS_MARCA_Y_FAMILIA_ESTRICTOS:
            codigos.append(tok)
        elif tok in TOKENS_VARIANTE_ESTRICTOS and len(tokens) >= 2:
            codigos.append(tok)
    return codigos


def coincide_modelo_especifico(titulo: str, query: str = "") -> bool:
    """
    Verifica que si el usuario buscó un modelo, marca o tipo específico (ej. 'Razer Gigantus V2 Large',
    'MacBook Air M2' o 'Taladro DeWalt DCD776'), el producto coincida estrictamente con el tipo de
    producto, marca, modelo y variante del query, evitando que productos de distintas gamas o variantes se mezclen.
    """
    if not query or not query.strip():
        return True

    titulo_norm = _normalizar_texto(titulo)
    query_norm = _normalizar_texto(query)
    titulo_compacto = titulo_norm.replace("-", "").replace(" ", "")

    # Si el query especifica un tipo de producto concreto (ej. mousepad, teclado, diadema, webcam, camara),
    # el título debe pertenecer al mismo tipo de producto.
    tipo_query = _detectar_tipo_producto(query_norm)
    tipo_titulo = _detectar_tipo_producto(titulo_norm)
    if tipo_query and tipo_titulo and tipo_query != tipo_titulo:
        return False

    codigos_requeridos = _extraer_codigos_modelo_query(query_norm)
    if not codigos_requeridos:
        return True

    for codigo in codigos_requeridos:
        codigo_compacto = codigo.replace("-", "")
        if not (
            _contiene_termino_exacto(titulo_norm, codigo)
            or (len(codigo_compacto) >= 3 and codigo_compacto in titulo_compacto)
        ):
            return False

    # Si el usuario buscó explícitamente "macbook air" o "macbook pro", exigir el submodelo
    if "macbook air" in query_norm and "macbook pro" in titulo_norm:
        return False
    if "macbook pro" in query_norm and "macbook air" in titulo_norm:
        return False

    return True


def es_oferta_relevante(titulo: str, query: str = "") -> bool:
    """
    Determina si un título de producto es relevante para la búsqueda `query`,
    descartando accesorios/repuestos no solicitados y aplicando el Motor de Precisión
    de Modelos cuando el query especifica marca/modelo/variante exacta.
    """
    if not titulo or not titulo.strip():
        return False

    titulo_norm = _normalizar_texto(titulo)
    query_norm = _normalizar_texto(query)

    for negativo in PALABRAS_NEGATIVAS_ACCESORIOS:
        neg_norm = _normalizar_texto(negativo)
        if query_norm and _contiene_termino_exacto(query_norm, neg_norm):
            continue

        if _contiene_termino_exacto(titulo_norm, neg_norm):
            return False

    # Si el query especifica un tipo de producto (ej. mousepad), descartar otros tipos (ej. teclado, diadema)
    if query_norm and not coincide_modelo_especifico(titulo, query):
        return False

    return True


def extraer_especificaciones_y_gama(
    titulo: str, precio_gtq: float = 0.0, categoria_ui: str = ""
) -> dict[str, Any]:
    """
    Analiza el título y precio de un producto para determinar:
      - `gama`: 'Profesional · Alta Gama' | 'Media · Productividad' | 'Entrada · Básica'
      - `gama_slug`: 'profesional' | 'media' | 'entrada'
      - `chips_especificaciones`: lista de 2 a 4 etiquetas técnicas concisas
      - `clave_modelo`: identificador normalizado del modelo para comparar ahorros reales
    """
    t_norm = _normalizar_texto(titulo)
    chips: list[str] = []

    # 1. Procesadores / Chips
    if re.search(r"\bm4\s*(?:pro|max)?\b", t_norm):
        m = re.search(r"\b(m4(?:\s*pro|\s*max)?)\b", t_norm)
        chips.append(m.group(1).upper() if m else "M4")
    elif re.search(r"\bm3\s*(?:pro|max)?\b", t_norm):
        m = re.search(r"\b(m3(?:\s*pro|\s*max)?)\b", t_norm)
        chips.append(m.group(1).upper() if m else "M3")
    elif re.search(r"\bm2\s*(?:pro|max)?\b", t_norm):
        m = re.search(r"\b(m2(?:\s*pro|\s*max)?)\b", t_norm)
        chips.append(m.group(1).upper() if m else "M2")
    elif re.search(r"\bm1\b", t_norm):
        chips.append("M1")
    elif re.search(r"\bcore\s*ultra\s*[579]\b", t_norm):
        m = re.search(r"\bcore\s*(ultra\s*[579])\b", t_norm)
        chips.append(f"Core {m.group(1).title()}" if m else "Core Ultra")
    elif re.search(r"\b(?:core\s*)?i[3579](?:-[0-9]{4,5}[a-z]{0,2})?\b", t_norm):
        m = re.search(r"\b(i[3579])(?:-([0-9]{4,5}[a-z]{0,2}))?\b", t_norm)
        if m:
            chips.append(f"Core {m.group(1).upper()}")
    elif re.search(r"\bryzen\s*[3579]\b", t_norm):
        m = re.search(r"\b(ryzen\s*[3579](?:\s*[0-9]{4}[a-z]{0,2})?)\b", t_norm)
        if m:
            partes = m.group(1).upper().split()
            chips.append(" ".join(partes[:2]))
    elif "celeron" in t_norm:
        chips.append("Celeron")
    elif re.search(r"\bn100\b|\bn150\b|\bn4020\b|\bn4500\b", t_norm):
        m = re.search(r"\b(n100|n150|n4020|n4500)\b", t_norm)
        if m:
            chips.append(f"Intel {m.group(1).upper()}")

    # 2. GPU dedicada
    m_gpu = re.search(r"\b(rtx\s*[0-9]{4}(?:\s*ti)?|gtx\s*[0-9]{4})\b", t_norm)
    if m_gpu:
        chips.append(m_gpu.group(1).upper())

    # 3. Memoria RAM y Almacenamiento
    matches_mem = re.findall(r"\b([0-9]{1,4})\s*(gb|tb)\b", t_norm)
    ram_detectada_gb = 0
    for cant_str, unidad in matches_mem:
        cant = int(cant_str)
        if unidad == "gb" and cant in {4, 8, 12, 16, 18, 24, 32, 64}:
            if ram_detectada_gb == 0:
                ram_detectada_gb = cant
            etiqueta_ram = f"{cant}GB RAM" if cant <= 64 else f"{cant}GB"
            if etiqueta_ram not in chips and f"{cant}GB" not in chips:
                chips.append(f"{cant}GB")
        elif (unidad == "gb" and cant in {128, 256, 512}) or (unidad == "tb" and cant in {1, 2, 4}):
            sufijo_ssd = " SSD" if "ssd" in t_norm or "nvme" in t_norm or "macbook" in t_norm else ""
            etiqueta_storage = f"{cant}{unidad.upper()}{sufijo_ssd}"
            if etiqueta_storage not in chips:
                chips.append(etiqueta_storage)

    # 4. Especificaciones de Herramientas / Ferretería (Voltaje, Potencia, Mandril, Brushless)
    m_volt = re.search(r"\b(12v|18v|20v(?:\s*max)?|60v)\b", t_norm)
    if m_volt:
        chips.append(m_volt.group(1).upper())
    m_watts = re.search(r"\b([0-9]{3,4})\s*w\b", t_norm)
    if m_watts:
        chips.append(f"{m_watts.group(1)}W")
    if "1/2" in t_norm:
        chips.append('1/2"')
    elif "3/8" in t_norm:
        chips.append('3/8"')
    if "brushless" in t_norm or "sin escobillas" in t_norm:
        chips.append("Brushless")
    elif "percutor" in t_norm or "rotomartillo" in t_norm:
        chips.append("Percutor")
    elif "inalambrico" in t_norm:
        chips.append("Inalámbrico")

    # 5. Especificaciones de Pantallas / Línea Blanca / Mascotas
    m_pulg = re.search(r"\b([0-9]{2}(?:\.[0-9])?)\s*(?:pulgadas|\"|'')", t_norm)
    if m_pulg and len(chips) < 3:
        chips.append(f'{m_pulg.group(1)}"')
    if "4k" in t_norm or "uhd" in t_norm:
        chips.append("4K UHD")
    if "qled" in t_norm:
        chips.append("QLED")
    elif "oled" in t_norm:
        chips.append("OLED")
    elif "amoled" in t_norm:
        chips.append("AMOLED")
    if re.search(r"\b5g\b", t_norm):
        chips.append("5G")
    if "inverter" in t_norm:
        chips.append("Inverter")

    m_peso = re.search(r"\b([0-9]{1,2}(?:\.[0-9])?)\s*(kg|lb|lbs)\b", t_norm)
    if m_peso and len(chips) < 3:
        chips.append(f"{m_peso.group(1)}{m_peso.group(2).upper()}")

    # Garantizar entre 2 y 4 chips limpios
    if not chips:
        if categoria_ui == "herramientas":
            chips = ["Uso Técnico", "Garantía GT"]
        elif categoria_ui == "super-mascotas":
            chips = ["Consumo Diario", "Stock GT"]
        elif categoria_ui == "hogar":
            chips = ["Hogar GT", "Garantía Oficial"]
        elif categoria_ui == "smartphones":
            chips = ["Libre", "Garantía GT"]
        else:
            chips = ["Edición GT", "Envío Local"]

    chips_limpios = chips[:4]

    # Clasificación de Gama (Profesional · Alta Gama | Media · Productividad | Entrada · Básica)
    es_entrada = any(
        k in t_norm
        for k in (
            "celeron",
            "n100",
            "n150",
            "n4020",
            "n4500",
            "hp stream",
            "pentium",
            "athlon",
            "4gb",
            "64gb",
            "pretul",
            "black+decker",
            "black and decker",
            "black & decker",
            "galaxy a0",
            "galaxy a1",
            "redmi a",
            "32 pulgadas",
            "hd ready",
        )
    )
    es_profesional = any(
        k in t_norm
        for k in (
            "macbook",
            "imac",
            "mac mini",
            "m1",
            "m2",
            "m3",
            "m4",
            "core i7",
            "core i9",
            "i7-",
            "i9-",
            "core ultra",
            "ryzen 7",
            "ryzen 9",
            "rtx",
            "thinkpad",
            "zenbook",
            "legion",
            "rog",
            "tuf gaming",
            "omen",
            "alienware",
            "iphone 15",
            "iphone 16",
            "galaxy s2",
            "galaxy z",
            "watch ultra",
            "apple watch",
            "ps5",
            "playstation 5",
            "dewalt",
            "gsb 20",
            "gsb20",
            "brushless",
            "industrial",
            "makita",
            "pro plan",
            "qled",
            "oled",
            "side by side",
        )
    ) or ram_detectada_gb >= 16

    if es_entrada and not es_profesional:
        gama = "Entrada · Básica"
        gama_slug = "entrada"
    elif es_profesional or (
        categoria_ui == "computo" and precio_gtq >= 5800 and not es_entrada
    ) or (
        categoria_ui == "herramientas" and precio_gtq >= 1200 and not es_entrada
    ) or (
        categoria_ui == "smartphones" and precio_gtq >= 5000
    ):
        gama = "Profesional · Alta Gama"
        gama_slug = "profesional"
    else:
        gama = "Media · Productividad"
        gama_slug = "media"

    identidad = extraer_identidad_producto(
        titulo, categoria_ui=categoria_ui, gama_slug=gama_slug
    )
    clave_modelo = identidad["clave_modelo"]

    return {
        "gama": gama,
        "gama_slug": gama_slug,
        "chips_especificaciones": chips_limpios,
        "clave_modelo": clave_modelo,
    }


def extraer_identidad_producto(
    titulo: str, categoria_ui: str = "", gama_slug: str = ""
) -> dict[str, Any]:
    """
    Extrae la firma de identidad estricta de un producto:
      - `tipo_producto`: ej. 'mousepad', 'teclado', 'diadema', 'webcam', 'camara-seguridad', 'laptop'
      - `marca`: ej. 'razer', 'logitech', 'hyperx', 'redragon', 'tp-link', 'ezviz', 'apple'
      - `codigos_modelo`: tupla ordenada de tokens de modelo/línea (ej. ('gigantus', 'v2'), ('g840',))
      - `variante_clave`: tupla ordenada de variantes de tamaño/capacidad/subgama (ej. ('large',), ('8gb', '256gb'))
      - `clave_modelo`: clave canónica determinista para agrupar únicamente productos idénticos
    """
    t_norm = _normalizar_texto(titulo)
    tipo_producto = _detectar_tipo_producto(t_norm)

    # 1. Detectar marca canónica
    marca_detectada = ""
    if "tp-link" in t_norm or "tapo" in t_norm:
        marca_detectada = "tp-link"
    elif "black+decker" in t_norm or "black and decker" in t_norm or "black & decker" in t_norm:
        marca_detectada = "black+decker"
    elif "macbook" in t_norm or "iphone" in t_norm or "ipad" in t_norm or "airpods" in t_norm:
        marca_detectada = "apple"
    elif "redmi" in t_norm or "poco" in t_norm:
        marca_detectada = "xiaomi"
    elif "playstation" in t_norm or "ps5" in t_norm:
        marca_detectada = "sony"
    else:
        for marca_cand in (
            "razer",
            "logitech",
            "hyperx",
            "redragon",
            "corsair",
            "keychron",
            "ezviz",
            "nexxt",
            "kingston",
            "apple",
            "samsung",
            "xiaomi",
            "honor",
            "motorola",
            "asus",
            "lenovo",
            "hp",
            "dell",
            "acer",
            "msi",
            "epson",
            "canon",
            "lg",
            "sony",
            "whirlpool",
            "mabe",
            "frigidaire",
            "oster",
            "ninja",
            "dewalt",
            "bosch",
            "makita",
            "milwaukee",
            "truper",
            "pretul",
            "stanley",
            "karcher",
            "emtop",
            "pedigree",
            "purina",
            "whiskas",
            "incaparina",
        ):
            if _contiene_termino_exacto(t_norm, marca_cand):
                marca_detectada = marca_cand
                break

    # 2. Patrones prioritarios de modelo exacto
    for patron_modelo in (
        r"\b(macbook\s*air\s*m[1234])\b",
        r"\b(macbook\s*pro\s*m[1234])\b",
        r"\b(iphone\s*1[3456](?:\s*pro)?(?:\s*max)?)\b",
        r"\b(galaxy\s*[asz][0-9]{2}(?:\s*fe|\s*ultra|\s*plus)?)\b",
        r"\b(gigantus\s*v2(?:\s*large|\s*xl|\s*xxl|\s*medium)?)\b",
        r"\b(fury\s*s(?:\s*pro)?(?:\s*xl|\s*large)?)\b",
        r"\b(g840(?:\s*xl)?)\b",
        r"\b(mm300(?:\s*pro)?(?:\s*xl)?)\b",
        r"\b(flick(?:\s*xl)?)\b",
        r"\b(kumara\s*k552)\b",
        r"\b(g\s*pro\s*x(?:\s*tkl)?)\b",
        r"\b(alloy\s*origins(?:\s*core)?)\b",
        r"\b(blackwidow\s*v4(?:\s*pro|\s*x)?)\b",
        r"\b(keychron\s*k[0-9]+)\b",
        r"\b(cloud\s*(?:iii|ii|alpha|stinger|3|2))\b",
        r"\b(g733|g435|g29|g920|g923|c920s|c920|c270|brio\s*4k|kiyo\s*x)\b",
        r"\b(blackshark\s*v2(?:\s*x|\s*pro)?)\b",
        r"\b(zeus\s*x(?:\s*h510)?)\b",
        r"\b(tapo\s*c[0-9]{3}[a-z]*)\b",
        r"\b(ezviz\s*(?:c6n|h8c|c3tn|h6c|c8c))\b",
        r"\b(dcd[0-9]{3})\b",
        r"\b(gsb\s*[0-9]{2})\b",
        r"\b(ps5|playstation\s*5)\b",
    ):
        m_mod = re.search(patron_modelo, t_norm)
        if m_mod:
            modelo_can = re.sub(r"\s+", "-", m_mod.group(1).strip())
            # Extraer capacidades de RAM/Almacenamiento o tamaño para distinguir variantes
            caps = re.findall(r"\b([0-9]{1,4}\s*(?:gb|tb|pies|kg|lb))\b", t_norm)
            caps_norm = tuple(re.sub(r"\s+", "", c) for c in caps[:2])
            variantes = [
                v
                for v in ("mini", "small", "medium", "large", "xl", "xxl", "tkl", "pro", "max", "ultra")
                if _contiene_termino_exacto(t_norm, v) and v not in modelo_can.split("-")
            ]
            sufijo_var = "-".join([*variantes, *caps_norm])
            clave_final = f"{modelo_can}-{sufijo_var}" if sufijo_var else modelo_can
            return {
                "tipo_producto": tipo_producto,
                "marca": marca_detectada,
                "codigos_modelo": (modelo_can,),
                "variante_clave": (*variantes, *caps_norm),
                "clave_modelo": clave_final,
            }

    # 3. Extracción general de códigos alfanuméricos de modelo y variantes
    tokens = re.findall(r"[a-z0-9]+", t_norm)
    codigos_alfanum: list[str] = []
    variantes_detectadas: list[str] = []
    unidades_medida = {"gb", "tb", "mhz", "hz", "mm", "cm", "kg", "lb", "lbs", "pies", "plg", "fps", "mp", "w", "v"}

    for tok in tokens:
        if tok == marca_detectada or tok in {"de", "la", "el", "en", "con", "para", "por", "gt", "wifi"}:
            continue
        if tok in TOKENS_VARIANTE_ESTRICTOS:
            if tok not in variantes_detectadas:
                variantes_detectadas.append(tok)
            continue
        tiene_letra = any(c.isalpha() for c in tok)
        tiene_digito = any(c.isdigit() for c in tok)
        if tiene_letra and tiene_digito and len(tok) >= 2:
            # Ignorar unidades puras como 1080p, 720p, 4k, 5g, 144hz, 900x400mm, 16gb
            if re.fullmatch(r"[0-9]+(?:gb|tb|mhz|hz|mm|cm|kg|lb|lbs|fps|mp|w|v|p|k|g)", tok):
                variantes_detectadas.append(tok)
            elif re.fullmatch(r"[0-9]+x[0-9]+(?:mm|cm)?", tok):
                continue
            else:
                codigos_alfanum.append(tok)
        elif tok in TOKENS_MARCA_Y_FAMILIA_ESTRICTOS and tok != marca_detectada:
            codigos_alfanum.append(tok)

    if marca_detectada and codigos_alfanum:
        modelo_str = "-".join(codigos_alfanum[:3])
        var_str = "-".join(variantes_detectadas[:2])
        partes_clave = [p for p in (tipo_producto, marca_detectada, modelo_str, var_str) if p]
        clave_modelo = ":".join(partes_clave)
    else:
        clave_modelo = f"{categoria_ui or 'general'}:{gama_slug or 'media'}"

    return {
        "tipo_producto": tipo_producto,
        "marca": marca_detectada,
        "codigos_modelo": tuple(codigos_alfanum[:3]),
        "variante_clave": tuple(variantes_detectadas[:3]),
        "clave_modelo": clave_modelo,
    }


def son_productos_estrictamente_identicos(
    oferta_base: dict[str, Any], oferta_candidata: dict[str, Any]
) -> bool:
    """
    Determina con precisión quirúrgica si dos ofertas corresponden al MISMO artículo
    comercial (mismo tipo de producto, misma marca, mismo modelo y misma variante/especificación clave).
    Evita que productos de distintas gamas, marcas o variantes (ej. Razer Gigantus V2 Large vs
    Logitech G840 XL o Razer Gigantus V2 XXL) se mezclen o generen ahorros falsos.
    """
    p_base = float(oferta_base.get("precio_gtq") or 0.0)
    p_cand = float(oferta_candidata.get("precio_gtq") or 0.0)
    if p_base <= 0 or p_cand <= 0:
        return False

    p_min = min(p_base, p_cand)
    p_max = max(p_base, p_cand)
    if p_max > p_min * 1.65:
        return False

    if oferta_base.get("categoria_ui") != oferta_candidata.get("categoria_ui"):
        return False
    if oferta_base.get("gama_slug") != oferta_candidata.get("gama_slug"):
        return False

    if (
        oferta_base.get("producto_id")
        and oferta_base.get("producto_id") == oferta_candidata.get("producto_id")
    ):
        return True

    titulo_b = str(oferta_base.get("titulo") or "")
    titulo_c = str(oferta_candidata.get("titulo") or "")
    id_b = extraer_identidad_producto(
        titulo_b,
        categoria_ui=str(oferta_base.get("categoria_ui") or ""),
        gama_slug=str(oferta_base.get("gama_slug") or ""),
    )
    id_c = extraer_identidad_producto(
        titulo_c,
        categoria_ui=str(oferta_candidata.get("categoria_ui") or ""),
        gama_slug=str(oferta_candidata.get("gama_slug") or ""),
    )

    # 1. El tipo de producto debe coincidir si alguno fue detectado
    if id_b["tipo_producto"] != id_c["tipo_producto"]:
        return False

    # 2. La marca debe existir y ser idéntica
    if not id_b["marca"] or not id_c["marca"] or id_b["marca"] != id_c["marca"]:
        return False

    # 3. Si ambos tienen clave_modelo específica (no genérica categoria:gama), deben coincidir
    clave_b = str(oferta_base.get("clave_modelo") or id_b["clave_modelo"])
    clave_c = str(oferta_candidata.get("clave_modelo") or id_c["clave_modelo"])
    es_generica_b = clave_b.endswith((":profesional", ":media", ":entrada"))
    es_generica_c = clave_c.endswith((":profesional", ":media", ":entrada"))

    if not es_generica_b and not es_generica_c:
        return clave_b == clave_c

    # 4. Ambos deben compartir al menos un código de modelo específico y la misma variante
    if not id_b["codigos_modelo"] or not id_c["codigos_modelo"]:
        return False
    if set(id_b["codigos_modelo"]) != set(id_c["codigos_modelo"]):
        return False
    if id_b["variante_clave"] != id_c["variante_clave"]:
        return False

    return True


def filtrar_ofertas_relevantes(
    ofertas: list[OfertaLocal], query: str = ""
) -> list[OfertaLocal]:
    """
    Filtra una lista de entidades `OfertaLocal`, removiendo accesorios irrelevantes
    y equipos que no coincidan con el modelo específico buscado.
    """
    if not ofertas:
        return []

    filtradas = [o for o in ofertas if es_oferta_relevante(o.titulo, query)]
    descartadas = len(ofertas) - len(filtradas)
    if descartadas > 0:
        logger.info(
            "Motor de Precisión y Anti-Ruido ('%s'): %d ofertas descartadas (%d ofertas principales conservadas).",
            query,
            descartadas,
            len(filtradas),
        )
    return filtradas


def filtrar_dicts_relevantes(
    ofertas: list[dict[str, Any]], query: str = ""
) -> list[dict[str, Any]]:
    """Filtra diccionarios de ofertas provenientes de consultas a Neon DB."""
    if not ofertas:
        return []
    return [
        o for o in ofertas if es_oferta_relevante(str(o.get("titulo") or ""), query)
    ]
