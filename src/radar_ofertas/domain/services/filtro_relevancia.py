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
        "apple",
        "macbook",
        "imac",
        "iphone",
        "ipad",
        "airpods",
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
        "dewalt",
        "bosch",
        "makita",
        "milwaukee",
        "truper",
        "pretul",
        "stanley",
        "karcher",
        "logitech",
        "ps5",
        "xbox",
        "nintendo",
        "pedigree",
        "purina",
        "whiskas",
    }
)


def _normalizar_texto(texto: str) -> str:
    """Convierte a minúsculas y elimina tildes/diacríticos para comparación uniforme."""
    texto_lower = (texto or "").lower().strip()
    descompuesto = unicodedata.normalize("NFD", texto_lower)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _contiene_termino_exacto(texto_normalizado: str, termino_normalizado: str) -> bool:
    """Verifica si `termino_normalizado` aparece como palabra o frase completa en `texto_normalizado`."""
    patron = rf"(?<![a-z0-9]){re.escape(termino_normalizado)}(?![a-z0-9])"
    return re.search(patron, texto_normalizado) is not None


def _extraer_codigos_modelo_query(query_norm: str) -> list[str]:
    """
    Detecta tokens de modelo específicos en la búsqueda del usuario:
    ej. 'm1', 'm2', 'm3', 'm4', 'dcd776', 'dcd796', 'gsb20', 'g29', 'g920', 's24', 's25', 'a56', 'rtx', 'i7', 'i5'.
    """
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", query_norm)
    codigos: list[str] = []
    for tok in tokens:
        if tok in {"de", "la", "el", "en", "con", "para", "por", "pro", "air", "max", "plus", "ultra"}:
            continue
        # Token alfanumérico con letras y dígitos (ej. m2, dcd776, g29, i7, s24, a56, gsb20-2)
        tiene_letra = any(c.isalpha() for c in tok)
        tiene_digito = any(c.isdigit() for c in tok)
        if tiene_letra and tiene_digito and len(tok) >= 2:
            codigos.append(tok)
        elif tok in TOKENS_MARCA_Y_FAMILIA_ESTRICTOS:
            codigos.append(tok)
    return codigos


def coincide_modelo_especifico(titulo: str, query: str = "") -> bool:
    """
    Verifica que si el usuario buscó un modelo o marca específica (ej. 'MacBook Air M2'
    o 'Taladro DeWalt DCD776'), el producto coincida con todos los tokens de marca/modelo
    del query y no mezcle equipos de gama baja no relacionados (como HP Stream Celeron).
    """
    if not query or not query.strip():
        return True

    titulo_norm = _normalizar_texto(titulo)
    query_norm = _normalizar_texto(query)
    titulo_compacto = titulo_norm.replace("-", "").replace(" ", "")

    codigos_requeridos = _extraer_codigos_modelo_query(query_norm)
    if not codigos_requeridos:
        return True

    for codigo in codigos_requeridos:
        codigo_compacto = codigo.replace("-", "")
        if not (
            _contiene_termino_exacto(titulo_norm, codigo)
            or codigo_compacto in titulo_compacto
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
    de Modelos cuando el query especifica marca/modelo exacto.
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

    # Si el usuario especificó marca/familia o código de modelo (ej. "macbook", "MacBook Air M2",
    # "Taladro DeWalt DCD776"), exigir coincidencia estricta para evitar mezclar gamas o productos ajenos.
    codigos_query = _extraer_codigos_modelo_query(query_norm)
    if codigos_query:
        if not coincide_modelo_especifico(titulo, query):
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

    # Clave de modelo para agrupar comparaciones justas (misma familia/gama)
    clave_modelo = f"{categoria_ui or 'general'}:{gama_slug}"
    for patron_modelo in (
        r"\b(macbook\s*air\s*m[1234])\b",
        r"\b(macbook\s*pro\s*m[1234])\b",
        r"\b(iphone\s*1[3456](?:\s*pro)?(?:\s*max)?)\b",
        r"\b(galaxy\s*[asz][0-9]{2}(?:\s*ultra)?)\b",
        r"\b(dcd[0-9]{3})\b",
        r"\b(gsb\s*[0-9]{2})\b",
        r"\b(g29|g920|g923)\b",
        r"\b(ps5|playstation\s*5)\b",
    ):
        m_mod = re.search(patron_modelo, t_norm)
        if m_mod:
            clave_modelo = re.sub(r"\s+", "-", m_mod.group(1))
            break

    return {
        "gama": gama,
        "gama_slug": gama_slug,
        "chips_especificaciones": chips_limpios,
        "clave_modelo": clave_modelo,
    }


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
