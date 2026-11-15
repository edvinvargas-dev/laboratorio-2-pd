"""Pruebas del repositorio PostgreSQL contra una base real.

Se ejecutan solo si existe TEST_DATABASE_URL (una base desechable: se borra su esquema).
Ejemplo:  TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5433/novamercado_test
"""

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from app.dependencias import Dependencias
from app.main import create_app
from app.schemas import Calidad, ObservacionCalidad, SolicitudObservacion
from app.servicios.modelo import GestorModeloFijo
from app.servicios.orquestador import OrquestadorFalso
from tests.conftest import FAMILIAS, FECHA

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin TEST_DATABASE_URL")


@pytest.fixture
def data_dir(tmp_path, historico):
    historico.to_csv(tmp_path / "historico_ventas.csv", index=False, date_format="%Y-%m-%d")
    return tmp_path


@pytest.fixture
def repo(data_dir):
    import psycopg

    from app.servicios.repositorio_pg import RepositorioPostgres

    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    r = RepositorioPostgres(URL)
    assert r.inicializar(data_dir) is True
    yield r
    r.cerrar()


def obs(ventas: dict[str, int], fecha=FECHA, tienda=5) -> SolicitudObservacion:
    return SolicitudObservacion(tienda_id=tienda, fecha=fecha,
                                ventas=[{"familia_id": f, "ventas": v} for f, v in ventas.items()])


OK = Calidad(estado="ok")


def test_historico_se_carga_una_sola_vez(repo, data_dir, historico):
    assert repo.inicializar(data_dir) is False  # segundo arranque: no repite el trabajo
    with repo.pool.connection() as c:
        assert c.execute("SELECT count(*) FROM historico_ventas").fetchone()[0] == len(historico)


def test_observacion_idempotente_y_modificada(repo):
    datos = {f: 10 + i for i, f in enumerate(FAMILIAS)}
    assert repo.guardar_observacion({"x": 1}, obs(datos), OK) == 12
    assert repo.guardar_observacion({"x": 1}, obs(datos), OK) == 0
    datos["abarrotes"] = 999
    assert repo.guardar_observacion({"x": 1}, obs(datos), OK) == 1
    with repo.pool.connection() as c:
        assert c.execute("SELECT count(*) FROM observaciones").fetchone()[0] == 12
        assert c.execute("SELECT count(*) FROM solicitudes WHERE endpoint = '/v1/observaciones'").fetchone()[0] == 3


def test_historia_observacion_prevalece_sobre_historico(repo):
    d = dt.date(2025, 11, 10)
    antes = repo.historia(5, d, d + dt.timedelta(days=1))
    assert len(antes) == 12
    repo.guardar_observacion(None, obs({"abarrotes": 4321}, fecha=d), OK)
    despues = repo.historia(5, d, d + dt.timedelta(days=1)).set_index("familia_id")
    assert len(despues) == 12 and despues.loc["abarrotes", "ventas"] == 4321


def test_historia_respeta_el_rango(repo):
    h = repo.historia(5, dt.date(2025, 11, 10), dt.date(2025, 11, 17))
    assert h.fecha.min() == dt.datetime(2025, 11, 10) and h.fecha.max() == dt.datetime(2025, 11, 16)
    assert set(h.tienda_id) == {5}


def test_correcciones_y_rechazos_se_registran(repo):
    cal = Calidad.desde([ObservacionCalidad(campo="ventas[0].ventas", accion="advertir", detalle="negativo")])
    repo.guardar_observacion({"a": 1}, obs({"bebe": 3}), cal)
    repo.registrar_rechazo("/v1/prediccion", {"tienda_id": 99}, "tienda_id 99 no existe")
    repo.registrar_rechazo("/v1/prediccion", None, "El cuerpo no es JSON válido")
    with repo.pool.connection() as c:
        assert c.execute("SELECT accion, detalle FROM correcciones").fetchall() == [("advertir", "negativo")]
        filas = c.execute("SELECT estado, detalle_rechazo, cuerpo FROM solicitudes WHERE estado = 'rechazado' "
                          "ORDER BY id").fetchall()
        assert filas[0] == ("rechazado", "tienda_id 99 no existe", {"tienda_id": 99})
        assert filas[1][2] is None


def test_api_completa_sobre_postgres(repo, cat, modelo):
    """El contrato funciona igual sobre Postgres, y la predicción queda registrada con su versión."""
    deps = Dependencias(cat=cat, gestor=GestorModeloFijo(modelo), repo=repo, orquestador=OrquestadorFalso())
    cliente = TestClient(create_app(deps))
    pred = {"tienda": "T05", "fecha": FECHA, "familias": [{"familia_id": f, "en_promocion": 2} for f in FAMILIAS]}
    r = cliente.post("/v1/prediccion", json=pred)
    assert r.status_code == 200 and r.json()["calidad"]["estado"] == "corregido"
    o = {"tienda_id": 5, "fecha": FECHA, "ventas": [{"familia_id": f, "ventas": 50} for f in FAMILIAS]}
    assert cliente.post("/v1/observaciones", json=o).json()["registros_guardados"] == 12
    assert cliente.post("/v1/observaciones", json=o).json()["registros_guardados"] == 0
    assert cliente.get("/health").json()["estado"] == "ok"

    with repo.pool.connection() as c:
        assert c.execute("SELECT count(*), min(version_modelo) FROM predicciones").fetchone() == (12, "3")
        # 'tienda' → 'tienda_id' (nombre del campo) y 'T05' → 5 (valor)
        assert c.execute("SELECT campo, accion FROM correcciones ORDER BY id").fetchall() == [
            ("tienda", "reparar"), ("tienda_id", "reparar")]
    # Para reentrenar: la observación del día hereda la promoción de la predicción
    ent = repo.ventas_entrenamiento()
    dia = ent[(ent.fecha == FECHA) & (ent.tienda_id == 5)]
    assert len(dia) == 12 and set(dia.en_promocion) == {2} and set(dia.origen) == {"observacion"}


def test_persistencia_entre_instancias(repo, data_dir):
    """Simula detener y volver a levantar: una conexión nueva ve lo guardado."""
    from app.servicios.repositorio_pg import RepositorioPostgres

    repo.guardar_observacion(None, obs({"bebe": 7}), OK)
    otro = RepositorioPostgres(URL)
    try:
        assert otro.inicializar(data_dir) is False
        assert otro.guardar_observacion(None, obs({"bebe": 7}), OK) == 0
    finally:
        otro.cerrar()


def test_base_caida_responde_503(cat, modelo):
    from app.servicios.repositorio_pg import RepositorioPostgres

    caida = RepositorioPostgres("postgresql://x:y@localhost:1/nada", timeout=1)
    try:
        deps = Dependencias(cat=cat, gestor=GestorModeloFijo(modelo), repo=caida, orquestador=OrquestadorFalso())
        cliente = TestClient(create_app(deps))
        o = {"tienda_id": 5, "fecha": FECHA, "ventas": [{"familia_id": "bebe", "ventas": 1}]}
        assert cliente.post("/v1/observaciones", json=o).status_code == 503
        h = cliente.get("/health").json()
        assert h["estado"] == "degradado" and "base de datos" in h["motivo"]
    finally:
        caida.cerrar()
