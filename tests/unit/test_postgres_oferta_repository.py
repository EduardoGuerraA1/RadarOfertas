from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from radar_ofertas.domain.entities.oferta_local import OfertaLocal
from radar_ofertas.infrastructure.db.postgres_oferta_repository import (
    PostgresOfertaRepository,
)


def test_sin_database_url_lanza_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        PostgresOfertaRepository(database_url="")


@patch("radar_ofertas.infrastructure.db.postgres_oferta_repository.psycopg2.connect")
def test_guardar_ofertas_inserta_en_productos_e_historial_precios_cuando_es_nuevo(
    mock_connect,
):
    cursor_mock = MagicMock()
    # Secuencia de respuestas de fetchone():
    # 1. _asegurar_categoria -> (categoria_id,)
    # 2. _asegurar_tienda -> (tienda_id, envio_gratis_default, tarifa_envio_local_gtq)
    # 3. _upsert_producto SELECT existente -> None
    # 4. _upsert_producto INSERT RETURNING id -> (producto_id,)
    # 5. _obtener_ultimo_precio_registrado SELECT precio_nativo -> None (sin historial previo)
    cursor_mock.fetchone.side_effect = [
        ("cat-uuid-1",),
        ("tienda-uuid-kemik", False, Decimal("35.00")),
        None,
        ("prod-uuid-g29",),
        None,
    ]

    conn_mock = MagicMock()
    conn_mock.__enter__.return_value = conn_mock
    conn_mock.cursor.return_value.__enter__.return_value = cursor_mock
    mock_connect.return_value = conn_mock

    repo = PostgresOfertaRepository(
        database_url="postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require"
    )
    oferta = OfertaLocal(
        tienda="Kemik",
        titulo="Logitech G29 Driving Force Volante de Carreras",
        precio_gtq=2699.00,
        url="https://www.kemik.gt/producto/logitech-g29",
        imagen_url="https://images.kemik.gt/g29.jpg",
    )

    insertados = repo.guardar_ofertas([oferta])

    assert insertados == 1
    assert cursor_mock.execute.call_count == 6
    ultima_query, ultimos_params = cursor_mock.execute.call_args_list[-1][0]
    assert "INSERT INTO historial_precios" in ultima_query
    assert ultimos_params[0] == "prod-uuid-g29"
    assert ultimos_params[1] == "tienda-uuid-kemik"
    assert ultimos_params[2] == Decimal("2699.00")
    assert ultimos_params[5] == Decimal("2734.00")


@patch("radar_ofertas.infrastructure.db.postgres_oferta_repository.psycopg2.connect")
def test_guardar_ofertas_omite_insercion_si_el_precio_no_cambio(mock_connect):
    cursor_mock = MagicMock()
    # Secuencia de respuestas de fetchone():
    # 1. _asegurar_categoria -> (categoria_id,)
    # 2. _asegurar_tienda -> (tienda_id, envio_gratis_default, tarifa_envio_local_gtq)
    # 3. _upsert_producto SELECT existente -> ("prod-uuid-g29",)
    # 4. _obtener_ultimo_precio_registrado -> (Decimal("2699.00"),) -> igual al actual
    cursor_mock.fetchone.side_effect = [
        ("cat-uuid-1",),
        ("tienda-uuid-kemik", False, Decimal("35.00")),
        ("prod-uuid-g29",),
        (Decimal("2699.00"),),
    ]

    conn_mock = MagicMock()
    conn_mock.__enter__.return_value = conn_mock
    conn_mock.cursor.return_value.__enter__.return_value = cursor_mock
    mock_connect.return_value = conn_mock

    repo = PostgresOfertaRepository(
        database_url="postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require"
    )
    oferta = OfertaLocal(
        tienda="Kemik",
        titulo="Logitech G29 Driving Force Volante de Carreras",
        precio_gtq=2699.00,
        url="https://www.kemik.gt/producto/logitech-g29",
        imagen_url="https://images.kemik.gt/g29.jpg",
    )

    insertados = repo.guardar_ofertas([oferta])

    assert insertados == 0
    # Asegurar que NO se ejecutó INSERT INTO historial_precios
    queries_ejecutadas = [call[0][0] for call in cursor_mock.execute.call_args_list]
    assert not any("INSERT INTO historial_precios" in q for q in queries_ejecutadas)


@patch("radar_ofertas.infrastructure.db.postgres_oferta_repository.psycopg2.connect")
def test_buscar_ofertas_comparadas_filtra_ruido_y_retorna_diccionarios_tipados(
    mock_connect,
):
    cursor_mock = MagicMock()
    cursor_mock.fetchall.return_value = [
        (
            "prod-ruido",
            "Silicone Sport Band for Samsung Galaxy Watch Ultra Correa",
            "Samsung",
            "https://img.pacifiko.com/band.jpg",
            "pacifiko",
            "Pacifiko",
            Decimal("95.00"),
            Decimal("35.00"),
            Decimal("130.00"),
            "https://www.pacifiko.com/compras-en-linea/band",
            "2026-11-13 21:06:04+00",
        ),
        (
            "prod-1",
            "Samsung Galaxy Watch 7 40mm Bluetooth Smartwatch",
            "Samsung",
            "https://www.max.com.gt/watch7.jpg",
            "tiendas-max",
            "Tiendas Max",
            Decimal("2199.00"),
            Decimal("35.00"),
            Decimal("2234.00"),
            "https://www.max.com.gt/galaxy-watch-7.html",
            "2026-11-13 21:48:33+00",
        ),
    ]

    conn_mock = MagicMock()
    conn_mock.__enter__.return_value = conn_mock
    conn_mock.cursor.return_value.__enter__.return_value = cursor_mock
    mock_connect.return_value = conn_mock

    repo = PostgresOfertaRepository(
        database_url="postgresql://user:pass@ep-test.neon.tech/neondb?sslmode=require"
    )
    resultados = repo.buscar_ofertas_comparadas(query="galaxy watch")

    # El accesorio (Band / Correa) debe ser descartado por el Filtro Anti-Ruido
    assert len(resultados) == 1
    assert resultados[0]["tienda"] == "Tiendas Max"
    assert resultados[0]["precio_gtq"] == 2199.00
