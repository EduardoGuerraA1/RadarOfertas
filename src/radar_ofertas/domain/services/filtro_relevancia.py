"""
Servicio de Dominio: Filtro Inteligente Anti-Ruido para Búsquedas de Productos.

Descarta automáticamente accesorios, repuestos o consumibles secundarios
(correas, bands, protectores, micas, estuches, cables, carbones, mandriles, etc.)
cuando el usuario busca un dispositivo o herramienta principal (ej. 'galaxy watch',
'volante', 'telefono', 'taladro'), a menos que el usuario haya incluido
explícitamente la palabra del accesorio en su búsqueda.
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
    # Herramientas / Taladros (repuestos y accesorios menores)
    "carbones",
    "carbon para",
    "cepillo para taladro",
    "cepillo circular",
    "porta taladro",
    "cinturon porta",
    "mandril",
    "llave para mandril",
    "bomba autocebante",
    "dados magneticos",
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
    "tablet",
    "ipad",
    "monitor",
    "televisor",
    "taladro",
    "barreno",
    "rotomartillo",
    "esmeriladora",
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


def es_oferta_relevante(titulo: str, query: str = "") -> bool:
    """
    Determina si un título de producto es relevante para la búsqueda `query`,
    descartando accesorios/repuestos cuando el usuario no los pidió explícitamente.
    """
    if not titulo or not titulo.strip():
        return False

    titulo_norm = _normalizar_texto(titulo)
    query_norm = _normalizar_texto(query)

    # Si no hay query (ej. vista general) o si el query menciona un dispositivo principal,
    # aplicamos el filtro de palabras negativas salvo que el usuario haya buscado el accesorio.
    for negativo in PALABRAS_NEGATIVAS_ACCESORIOS:
        neg_norm = _normalizar_texto(negativo)
        # Si el usuario buscó explícitamente el accesorio (ej. "correa galaxy watch"), no lo bloqueamos
        if query_norm and _contiene_termino_exacto(query_norm, neg_norm):
            continue

        if _contiene_termino_exacto(titulo_norm, neg_norm):
            return False

    return True


def filtrar_ofertas_relevantes(
    ofertas: list[OfertaLocal], query: str = ""
) -> list[OfertaLocal]:
    """
    Filtra una lista de entidades `OfertaLocal`, removiendo accesorios irrelevantes
    y registrando cuántos elementos de ruido fueron descartados.
    """
    if not ofertas:
        return []

    filtradas = [o for o in ofertas if es_oferta_relevante(o.titulo, query)]
    descartadas = len(ofertas) - len(filtradas)
    if descartadas > 0:
        logger.info(
            "Filtro Anti-Ruido ('%s'): %d accesorios irrelevantes descartados (%d ofertas principales conservadas).",
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
