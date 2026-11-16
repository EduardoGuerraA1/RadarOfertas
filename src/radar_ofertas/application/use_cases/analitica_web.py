"""
Servicio Ligero de Analítica Web y Telemetría de Conversión (tecHunter GT v5.0).

Mide en tiempo real sin afectar la latencia de respuesta:
  1. Visitas totales al comparador (`visitas_totales`).
  2. Términos de búsqueda más populares (`terminos_busqueda`) y filtros de categoría (`categorias_consultadas`).
  3. Clics salientes hacia tiendas (`clics_salientes_por_tienda` y `ultimos_clics_salientes`)
     al presionar 'Ir a la tienda ↗' o los anuncios nativos ('Z-Tech Imports GT', 'Nova Viventia Travel').
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import Counter, deque
from typing import Any

logger = logging.getLogger("tecHunter.analytics")


class GestorAnaliticaWeb:
    """
    Almacén en memoria thread-safe/async-safe de eventos de analítica de visitantes.
    Complementa a Google Analytics 4 (`gtag.js`) con métricas consultables vía `/api/analytics/summary`.
    """

    def __init__(self, max_eventos_recientes: int = 50) -> None:
        self.iniciado_en: str = dt.datetime.now(dt.timezone.utc).isoformat()
        self.visitas_totales: int = 0
        self.busquedas_totales: int = 0
        self.clics_salientes_totales: int = 0
        self.terminos_busqueda: Counter[str] = Counter()
        self.categorias_consultadas: Counter[str] = Counter()
        self.clics_por_tienda: Counter[str] = Counter()
        self.clics_anuncios_casa: Counter[str] = Counter()
        self.eventos_recientes: deque[dict[str, Any]] = deque(
            maxlen=max_eventos_recientes
        )

    def registrar_visita(
        self, query: str = "", categoria: str = "", tienda: str = ""
    ) -> None:
        self.visitas_totales += 1
        q_limpio = (query or "").strip().lower()
        cat_limpia = (categoria or "").strip().lower()
        if q_limpio:
            self.busquedas_totales += 1
            self.terminos_busqueda[q_limpio] += 1
        if cat_limpia:
            self.categorias_consultadas[cat_limpia] += 1

    def registrar_evento(
        self,
        tipo: str,
        query: str = "",
        tienda: str = "",
        titulo: str = "",
        url_destino: str = "",
        precio_gtq: float = 0.0,
    ) -> dict[str, Any]:
        ahora = dt.datetime.now(dt.timezone.utc).isoformat()
        tipo_norm = (tipo or "custom").strip().lower()

        if tipo_norm == "pageview":
            self.registrar_visita(query=query, tienda=tienda)
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
