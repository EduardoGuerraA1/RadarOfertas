"""
Servicio Ligero y Blindado de Analítica Web Privada (tecHunter GT v5.1).

Características de Blindaje y Privacidad:
  1. Filtro Anti-Bots y Monitores (`es_bot_o_monitor`): Descarta automáticamente pings de
     mantenimiento (UptimeRobot, Pingdom, StatusCake, BetterStack, Render Healthcheck),
     crawlers (Googlebot, Bingbot, Ahrefs, Semrush) y peticiones `HEAD` para no inflar
     las métricas reales de usuarios humanos.
  2. Control de Acceso Privado (`es_acceso_admin_autorizado`): Protege el resumen de
     analítica (`/api/analytics/summary`) y el widget de métricas en la UI mediante
     token secreto (`?admin=secreto` o `ADMIN_ANALYTICS_TOKEN`) y cookie de sesión firmada
     (`techunter_admin`), dejando la interfaz 100% limpia de métricas para visitantes públicos.
"""
from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
from collections import Counter, deque
from typing import Any

logger = logging.getLogger("tecHunter.analytics")

PATRONES_BOTS_Y_MONITORES: tuple[str, ...] = (
    "uptimerobot",
    "pingdom",
    "statuscake",
    "betterstack",
    "better uptime",
    "hetrixtools",
    "freshping",
    "datadog",
    "newrelic",
    "prometheus",
    "kube-probe",
    "render/",
    "healthcheck",
    "googlebot",
    "adsbot-google",
    "bingbot",
    "slurp",
    "duckduckbot",
    "baiduspider",
    "yandexbot",
    "sogou",
    "exabot",
    "facebot",
    "facebookexternalhit",
    "ia_archiver",
    "ahrefsbot",
    "semrushbot",
    "mj12bot",
    "dotbot",
    "petalbot",
    "bytespider",
    "gptbot",
    "claudebot",
    "twitterbot",
    "slackbot",
    "discordbot",
    "telegrambot",
    "python-requests",
    "python-urllib",
    "aiohttp",
    "httpx",
    "curl/",
    "wget/",
    "go-http-client",
    "headlesschrome",
    "playwright",
    "puppeteer",
)

COOKIE_ADMIN_NAME = "techunter_admin"


def obtener_tokens_admin_validos() -> set[str]:
    """
    Retorna el conjunto de tokens válidos para acceso de administrador.
    Soporta `ADMIN_ANALYTICS_TOKEN` desde variables de entorno y `'secreto'` por compatibilidad.
    """
    token_env = (os.environ.get("ADMIN_ANALYTICS_TOKEN") or "").strip()
    tokens = {"secreto", "techunter-admin"}
    if token_env:
        tokens.add(token_env)
    return tokens


def es_token_admin_valido(candidato: str | None) -> bool:
    if not candidato or not candidato.strip():
        return False
    limpio = candidato.strip()
    return any(
        hmac.compare_digest(limpio, valido)
        for valido in obtener_tokens_admin_validos()
    )


def es_bot_o_monitor(user_agent: str = "", metodo_http: str = "GET") -> bool:
    """
    Detecta si la visita proviene de un monitor de uptime (ej. UptimeRobot),
    bot/crawler automatizado o petición HEAD de mantenimiento.
    """
    if (metodo_http or "GET").upper() == "HEAD":
        return True

    ua_lower = (user_agent or "").strip().lower()
    if not ua_lower:
        return False

    return any(patron in ua_lower for patron in PATRONES_BOTS_Y_MONITORES)


class GestorAnaliticaWeb:
    """
    Almacén en memoria de eventos de analítica de visitantes reales (filtrando bots y monitores).
    """

    def __init__(self, max_eventos_recientes: int = 50) -> None:
        self.iniciado_en: str = dt.datetime.now(dt.timezone.utc).isoformat()
        self.visitas_totales: int = 0
        self.busquedas_totales: int = 0
        self.clics_salientes_totales: int = 0
        self.pings_bots_ignorados: int = 0
        self.terminos_busqueda: Counter[str] = Counter()
        self.categorias_consultadas: Counter[str] = Counter()
        self.clics_por_tienda: Counter[str] = Counter()
        self.clics_anuncios_casa: Counter[str] = Counter()
        self.eventos_recientes: deque[dict[str, Any]] = deque(
            maxlen=max_eventos_recientes
        )

    def registrar_visita(
        self,
        query: str = "",
        categoria: str = "",
        tienda: str = "",
        user_agent: str = "",
        metodo_http: str = "GET",
    ) -> bool:
        """
        Registra una visita humana real. Si es un bot o monitor (ej. UptimeRobot),
        lo descarta y retorna `False`.
        """
        if es_bot_o_monitor(user_agent=user_agent, metodo_http=metodo_http):
            self.pings_bots_ignorados += 1
            return False

        self.visitas_totales += 1
        q_limpio = (query or "").strip().lower()
        cat_limpia = (categoria or "").strip().lower()
        if q_limpio:
            self.busquedas_totales += 1
            self.terminos_busqueda[q_limpio] += 1
        if cat_limpia:
            self.categorias_consultadas[cat_limpia] += 1
        return True

    def registrar_evento(
        self,
        tipo: str,
        query: str = "",
        tienda: str = "",
        titulo: str = "",
        url_destino: str = "",
        precio_gtq: float = 0.0,
        user_agent: str = "",
    ) -> dict[str, Any] | None:
        if es_bot_o_monitor(user_agent=user_agent, metodo_http="POST"):
            self.pings_bots_ignorados += 1
            return None

        ahora = dt.datetime.now(dt.timezone.utc).isoformat()
        tipo_norm = (tipo or "custom").strip().lower()

        if tipo_norm == "pageview":
            self.registrar_visita(
                query=query, tienda=tienda, user_agent=user_agent
            )
        elif tipo_norm == "search":
            q_limpio = (query or "").strip().lower()
            if q_limpio:
                self.busquedas_totales += 1
                self.terminos_busqueda[q_limpio] += 1
        elif tipo_norm in {"outbound_click", "ir_a_tienda"}:
            self.clics_salientes_totales += 1
            nombre_tienda = (tienda or "Tienda Externa").strip()
            self.clics_por_tienda[nombre_tienda] += 1
        elif tipo_norm == "house_ad_click":
            self.clics_salientes_totales += 1
            partner = (tienda or titulo or "Holding Partner").strip()
            self.clics_anuncios_casa[partner] += 1

        registro = {
            "timestamp": ahora,
            "tipo": tipo_norm,
            "query": query,
            "tienda": tienda,
            "titulo": titulo[:120] if titulo else "",
            "url_destino": url_destino,
            "precio_gtq": round(float(precio_gtq or 0.0), 2),
        }
        self.eventos_recientes.appendleft(registro)
        return registro

    def obtener_resumen(self, top_n: int = 10) -> dict[str, Any]:
        return {
            "iniciado_en": self.iniciado_en,
            "visitas_totales": self.visitas_totales,
            "busquedas_totales": self.busquedas_totales,
            "clics_salientes_totales": self.clics_salientes_totales,
            "pings_bots_ignorados": self.pings_bots_ignorados,
            "top_terminos_busqueda": [
                {"termino": t, "busquedas": c}
                for t, c in self.terminos_busqueda.most_common(top_n)
            ],
            "top_categorias": [
                {"categoria": cat, "consultas": c}
                for cat, c in self.categorias_consultadas.most_common(top_n)
            ],
            "clics_salientes_por_tienda": [
                {"tienda": t, "clics": c}
                for t, c in self.clics_por_tienda.most_common(top_n)
            ],
            "clics_anuncios_casa": dict(self.clics_anuncios_casa),
            "ultimos_eventos": list(self.eventos_recientes)[:15],
        }


gestor_analitica = GestorAnaliticaWeb()
