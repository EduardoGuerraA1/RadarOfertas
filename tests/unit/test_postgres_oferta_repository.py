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
def test_guardar_ofertas_inserta_en_productos_e_historial_precios(mock_connect):
    cursor_mock = MagicMock()
    # Secuencia de respuestas de fetchone():
    # 1. _asegurar_categoria -> (categoria_id,)
    # 2. _asegurar_tienda -> (tienda_id, envio_gratis_default, tarifa_envio_local_gtq)
    # 3. _upsert_producto SELECT existente -> None
    # 4. _upsert_producto INSERT RETURNING id -> (producto_id,)
    cursor_mock.fetchone.side_effect = [
        ("cat-uuid-1",),
        ("tienda-uuid-kemik", False, Decimal("35.00")),
        None,
        ("prod-uuid-g29",),
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
    assert cursor_mock.execute.call_count == 5
    # Verificar la llamada final de INSERT INTO historial_precios
    ultima_query, ultimos_params = cursor_mock.execute.call_args_list[-1][0]
    assert "INSERT INTO historial_precios" in ultima_query
    assert ultimos_params[0] == "prod-uuid-g29"
    assert ultimos_params[1] == "tienda-uuid-kemik"
    assert ultimos_params[2] == Decimal("2699.0")
    assert ultimos_params[5] == Decimal("2734.00")  # 2699.00 + 35.00 envío local


@patch("radar_ofertas.infrastructure.db.postgres_oferta_repository.psycopg2.connect")
def test_buscar_ofertas_comparadas_retorna_diccionarios_tipados(mock_connect):
    cursor_mock = MagicMock()
    cursor_mock.fetchall.return_value = [
        (
            "prod-1",
            "Logitech G29 Driving Force",
            "Logitech",
            "https://images.kemik.gt/g29.jpg",
            "kemik",
            "Kemik",
            Decimal("2699.00"),
            Decimal("35.00"),
            Decimal("2734.00"),
            "https://www.kemik.gt/producto/g29",
            "2026-11-13 21:06:04+00",
        ),
        (
            "prod-2",
            "Logitech G29 Driving Force PS4/PC",
            "Logitech",
            "https://img.pacifiko.com/g29.jpg",
            "pacifiko",
            "Pacifiko",
            Decimal("3295.01"),
            Decimal("35.00"),
            Decimal("3330.01"),
            "https://www.pacifiko.com/compras-en-linea/g29",
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
    resultados = repo.buscar_ofertas_comparadas(query="volante logitech")

    assert len(resultados) == 2
    assert resultados[0]["tienda"] == "Kemik"
    assert resultados[0]["precio_gtq"] == 2699.00
    assert resultados[1]["tienda"] == "Pacifiko"
    assert resultados[1]["precio_gtq"] == 3295.01
