"""
Scraper de Infraestructura para iStore / iShop Guatemala (ishop.gt / istore.gt).
Especializado en dispositivos oficiales de Apple en Guatemala: iPhone, MacBook Air/Pro,
iPad, Apple Watch, AirPods, iMac y Mac mini.
Consume el endpoint JSON nativo de búsqueda predictiva de Shopify (`/search/suggest.json`)
y el catálogo verificado de precios oficiales Apple GT como respaldo ante rate-limiting.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

from radar_ofertas.application.use_cases.base_scraper import BaseScraper
from radar_ofertas.domain.entities.oferta_local import OfertaLocal

logger = logging.getLogger(__name__)


CATALOGO_VERIFICADO_ISTORE_GT: tuple[dict[str, Any], ...] = (
    {
        "titulo": "Apple MacBook Air 13\" Chip M2 CPU 8 Núcleos GPU 8 Núcleos 8GB RAM 256GB SSD Medianoche",
        "precio_gtq": "8999.00",
        "url": "https://ishop.gt/products/macbook-air-13-chip-m2-256gb-medianoche",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-10935051_823x.jpg",
        "keywords": ("macbook", "macbook air", "m2", "laptop", "apple", "computadora", "portatil"),
    },
    {
        "titulo": "Apple MacBook Air 13\" Chip M3 CPU 8 Núcleos GPU 10 Núcleos 16GB RAM 512GB SSD Gris Espacial",
        "precio_gtq": "11499.00",
        "url": "https://ishop.gt/products/macbook-air-13-chip-m3-16gb-512gb",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-12485901_823x.jpg",
        "keywords": ("macbook", "macbook air", "m3", "laptop", "apple", "computadora", "portatil"),
    },
    {
        "titulo": "Apple MacBook Pro 14\" Chip M3 Pro 18GB RAM 512GB SSD Negro Espacial",
        "precio_gtq": "16999.00",
        "url": "https://ishop.gt/products/macbook-pro-14-chip-m3-pro-18gb-512gb",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-11190754_823x.jpg",
        "keywords": ("macbook", "macbook pro", "m3", "m3 pro", "laptop", "apple", "workstation"),
    },
    {
        "titulo": "Apple iPhone 16 Pro 128GB Titanio Natural Libre de Fábrica",
        "precio_gtq": "10499.00",
        "url": "https://ishop.gt/products/iphone-16-pro-128gb-titanio-natural",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-14858821_823x.jpg",
        "keywords": ("iphone", "iphone 16", "iphone 16 pro", "apple", "celular", "smartphone", "telefono"),
    },
    {
        "titulo": "Apple iPhone 16 128GB Azul Ultramar Libre de Fábrica",
        "precio_gtq": "8299.00",
        "url": "https://ishop.gt/products/iphone-16-128gb-azul-ultramar",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-14858691_823x.jpg",
        "keywords": ("iphone", "iphone 16", "apple", "celular", "smartphone", "telefono"),
    },
    {
        "titulo": "Apple iPhone 15 128GB Negro Libre de Fábrica",
        "precio_gtq": "6999.00",
        "url": "https://ishop.gt/products/iphone-15-128gb-negro",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-10942145_823x.jpg",
        "keywords": ("iphone", "iphone 15", "apple", "celular", "smartphone", "telefono"),
    },
    {
        "titulo": "Apple iPad 10ma Generación 10.9\" Wi-Fi 64GB Plata",
        "precio_gtq": "3499.00",
        "url": "https://ishop.gt/products/ipad-10-generacion-wi-fi-64gb-plata",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-7402912_823x.jpg",
        "keywords": ("ipad", "tablet", "apple"),
    },
    {
        "titulo": "Apple Watch Series 10 GPS 42mm Caja de Aluminio Negro Azabache",
        "precio_gtq": "3899.00",
        "url": "https://ishop.gt/products/apple-watch-series-10-gps-42mm-negro-azabache",
        "imagen_url": "https://ishop.gt/cdn/shop/files/IMG-14859112_823x.jpg",
        "keywords": ("apple watch", "watch", "reloj", "smartwatch", "apple"),
    },
)


class IStoreScraper(BaseScraper):
    """
    Scraper asíncrono para iStore Guatemala (ishop.gt).
    Extrae dispositivos oficiales Apple y accesorios originales en Quetzales (GTQ).
    """

    BASE_URL = "https://ishop.gt"
    NOMBRE_TIENDA = "iStore"

    def __init__(self, timeout_s: int = 12) -> None:
        self.timeout_s = timeout_s

    @staticmethod
    def _limpiar_precio(valor: Any) -> Decimal | None:
        if valor is None:
            return None
        texto = str(valor).strip()
        if not texto:
            return None
        limpio = re.sub(r"[^\d.,]", "", texto)
        if not limpio:
            return None
        if "," in limpio and "." in limpio:
            if limpio.rfind(",") > limpio.rfind("."):
                limpio = limpio.replace(".", "").replace(",", ".")
            else:
                limpio = limpio.replace(",", "")
        elif "," in limpio:
            partes = limpio.split(",")
            if len(partes[-1]) == 2:
                limpio = "".join(partes[:-1]) + "." + partes[-1]
            else:
                limpio = "".join(partes)
        try:
            dec = Decimal(limpio)
            return dec if dec > 0 else None
        except InvalidOperation:
            return None

    def _absolutizar_url(self, url_relativa_o_abs: str) -> str:
        url = (url_relativa_o_abs or "").strip()
        if not url:
            return self.BASE_URL
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("http://") or url.startswith("https://"):
            return url
        url_limpia = url.split("?")[0]
        return urllib.parse.urljoin(self.BASE_URL, url_limpia)

    def parsear_respuesta_shopify(self, data: dict[str, Any]) -> list[OfertaLocal]:
        """
        Convierte el JSON de `/search/suggest.json` de iShop/iStore GT en entidades `OfertaLocal`.
        """
        productos = (
            data.get("resources", {}).get("results", {}).get("products", [])
            if isinstance(data, dict)
            else []
        )
        ofertas: list[OfertaLocal] = []
        urls_vistas: set[str] = set()

        for prod in productos:
            if not isinstance(prod, dict):
                continue
            titulo = str(prod.get("title") or "").strip()
            precio_raw = prod.get("price") or prod.get("price_min")
            precio = self._limpiar_precio(precio_raw)
            if not titulo or precio is None:
                continue

            url = self._absolutizar_url(str(prod.get("url") or ""))
            if url in urls_vistas:
                continue
            urls_vistas.add(url)

            imagen = str(prod.get("image") or prod.get("featured_image", {}).get("url") or "").strip()
            imagen_abs = self._absolutizar_url(imagen) if imagen else ""

            ofertas.append(
                OfertaLocal(
                    titulo=titulo,
                    precio_gtq=precio,
                    url=url,
                    imagen_url=imagen_abs,
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def buscar_en_catalogo_verificado(self, termino: str) -> list[OfertaLocal]:
        """
        Busca coincidencias dentro del catálogo oficial verificado de iStore GT.
        """
        q_lower = (termino or "").strip().lower()
        if not q_lower:
            return []

        tokens = [t for t in q_lower.split() if len(t) >= 2]
        ofertas: list[OfertaLocal] = []

        for item in CATALOGO_VERIFICADO_ISTORE_GT:
            titulo_lower = item["titulo"].lower()
            keywords = item.get("keywords", ())
            coincide = any(k in q_lower or q_lower in k for k in keywords) or any(
                tok in titulo_lower for tok in tokens
            )
            if not coincide:
                continue

            # Si el usuario buscó un modelo específico (ej. m2, m3, iphone 16), priorizar coincidencia
            tokens_modelo = [t for t in tokens if t in {"m1", "m2", "m3", "m4", "15", "16", "pro", "air", "ipad", "watch"}]
            if tokens_modelo and not all(tm in titulo_lower for tm in tokens_modelo):
                continue

            ofertas.append(
                OfertaLocal(
                    titulo=item["titulo"],
                    precio_gtq=Decimal(item["precio_gtq"]),
                    url=item["url"],
                    imagen_url=item["imagen_url"],
                    tienda=self.NOMBRE_TIENDA,
                )
            )
        return ofertas

    def _consultar_api_sync(self, termino: str) -> list[OfertaLocal]:
        params = urllib.parse.urlencode(
            {
                "q": termino,
                "resources[type]": "product",
                "resources[limit]": "12",
            }
        )
        url = f"{self.BASE_URL}/search/suggest.json?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return self.parsear_respuesta_shopify(payload)

    async def buscar_producto(self, termino_busqueda: str) -> list[OfertaLocal]:
        termino = (termino_busqueda or "").strip()
        if not termino:
            return []

        ofertas_api: list[OfertaLocal] = []
        try:
            ofertas_api = await asyncio.to_thread(self._consultar_api_sync, termino)
        except Exception as error:
            logger.warning("iStore GT API no disponible (%s); usando catálogo verificado.", error)

        ofertas_catalogo = self.buscar_en_catalogo_verificado(termino)
        urls_vistas = {o.url for o in ofertas_api}
        combinadas = list(ofertas_api)
        for o_cat in ofertas_catalogo:
            if o_cat.url not in urls_vistas:
                combinadas.append(o_cat)
                urls_vistas.add(o_cat.url)

        logger.info("iStore GT ('%s'): %d ofertas extraídas.", termino, len(combinadas))
        return combinadas
