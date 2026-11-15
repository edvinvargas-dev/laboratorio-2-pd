"""Pruebas del contrato del Anexo: campos, tipos, códigos de estado y comportamiento."""

import datetime as dt

import pytest
from pydantic import ValidationError

from app.schemas import Calidad, ObservacionCalidad
from app.servicios.modelo import GestorModeloFijo
from app.servicios.orquestador import OrquestadorFalso
from tests.conftest import FAMILIAS, FECHA


# ------------------------------------------------------------------- predicción

def test_prediccion_valida_cumple_contrato(client, pred_valida):
    r = client.post("/v1/prediccion", json=pred_valida)
    assert r.status_code == 200
    b = r.json()
    assert {"tienda_id", "fecha", "version_modelo", "predicciones", "calidad"} <= b.keys()
    assert b["tienda_id"] == 5 and b["fecha"] == FECHA
    assert isinstance(b["version_modelo"], str) and b["version_modelo"] == "3"
    assert [p["familia_id"] for p in b["predicciones"]] == FAMILIAS  # mismo orden que la solicitud
    for p in b["predicciones"]:
        assert {"familia_id", "venta_esperada", "cantidad_sugerida"} <= p.keys()
        assert isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0
        assert isinstance(p["venta_esperada"], (int, float))
    assert b["calidad"] == {"estado": "ok", "observaciones": []}


def test_prediccion_se_registra(client, deps, pred_valida):
    client.post("/v1/prediccion", json=pred_valida)
    assert len(deps.repo.predicciones) == 1
    assert deps.repo.predicciones[0]["respuesta"].version_modelo == "3"


def test_misma_fecha_se_puede_pedir_dos_veces(client, pred_valida):
    a = client.post("/v1/prediccion", json=pred_valida).json()
    b = client.post("/v1/prediccion", json=pred_valida).json()
    assert a["predicciones"] == b["predicciones"]


def test_prediccion_no_usa_ventas_del_mismo_dia(client, deps, pred_valida):
    antes = client.post("/v1/prediccion", json=pred_valida).json()["predicciones"]
    for f in FAMILIAS:  # aunque ya existiera la venta real del día, no debe usarse
        deps.repo.ventas[(5, dt.date.fromisoformat(FECHA), f)] = 10**6
    despues = client.post("/v1/prediccion", json=pred_valida).json()["predicciones"]
    assert antes == despues


def test_observacion_de_ayer_cambia_la_prediccion(client, pred_valida, obs_valida):
    """Las observaciones registradas alimentan los pronósticos siguientes.

    El baseline usa la mediana de d−7, d−14, d−21 y d−28: se cambian tres para que la mediana se mueva.
    """
    antes = client.post("/v1/prediccion", json=pred_valida).json()["predicciones"]
    for fecha in ["2025-11-10", "2025-11-03", "2025-10-27"]:
        obs = {**obs_valida, "fecha": fecha, "ventas": [{"familia_id": f, "ventas": 5000} for f in FAMILIAS]}
        assert client.post("/v1/observaciones", json=obs).status_code == 200
    despues = client.post("/v1/prediccion", json=pred_valida).json()["predicciones"]
    assert despues[0]["venta_esperada"] > antes[0]["venta_esperada"]


@pytest.mark.parametrize("cuerpo, fragmento", [
    ({"tienda_id": 99, "fecha": FECHA, "familias": [{"familia_id": "bebe", "en_promocion": 0}]}, "tienda_id"),
    ({"fecha": FECHA, "familias": [{"familia_id": "bebe", "en_promocion": 0}]}, "tienda_id"),
    ({"tienda_id": 5, "fecha": "ayer", "familias": [{"familia_id": "bebe", "en_promocion": 0}]}, "fecha"),
    ({"tienda_id": 5, "fecha": FECHA, "familias": []}, "familias"),
    ({"tienda_id": 5, "fecha": FECHA, "familias": [{"familia_id": "ropa", "en_promocion": 0}]}, "Ninguna familia"),
    ({"tienda_id": 5, "fecha": "1900-01-01", "familias": [{"familia_id": "bebe", "en_promocion": 0}]}, "rango"),
    ({"tienda_id": 10, "fecha": "2025-01-10", "familias": [{"familia_id": "bebe", "en_promocion": 0}]}, "abrió"),
    ([1, 2, 3], "objeto"),
])
def test_rechazo_422_con_detail_textual(client, deps, cuerpo, fragmento):
    r = client.post("/v1/prediccion", json=cuerpo)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str) and fragmento in r.json()["detail"]
    assert len(deps.repo.rechazos) == 1


def test_json_invalido_422(client):
    r = client.post("/v1/prediccion", content=b"{no es json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "JSON" in r.json()["detail"]


def test_sin_modelo_503(client, deps, pred_valida):
    deps.gestor = GestorModeloFijo(None)
    assert client.post("/v1/prediccion", json=pred_valida).status_code == 503
    assert client.get("/modelo").status_code == 503
    assert client.get("/health").status_code == 503


# ---------------------------------------------------------------- observaciones

def test_observacion_idempotente(client, obs_valida):
    r1 = client.post("/v1/observaciones", json=obs_valida)
    assert r1.status_code == 200
    assert r1.json() == {"registros_guardados": 12, "calidad": {"estado": "ok", "observaciones": []}}
    r2 = client.post("/v1/observaciones", json=obs_valida)
    assert r2.status_code == 200 and r2.json()["registros_guardados"] == 0


def test_observacion_modificada_cuenta_solo_lo_que_cambia(client, obs_valida):
    client.post("/v1/observaciones", json=obs_valida)
    obs_valida["ventas"][0]["ventas"] += 1
    assert client.post("/v1/observaciones", json=obs_valida).json()["registros_guardados"] == 1


# ------------------------------------------------------------- administración

def test_reentrenar_202_y_estado(client):
    r = client.post("/admin/reentrenar")
    assert r.status_code == 202 and isinstance(r.json()["id"], str)
    e = client.get(f"/admin/reentrenar/{r.json()['id']}")
    assert e.status_code == 200
    b = e.json()
    assert b["estado"] in {"en_curso", "exitoso", "fallido"}
    if b["estado"] != "en_curso":
        assert {"promovido", "version", "motivo"} <= b.keys() and isinstance(b["version"], str)


def test_reentrenar_id_desconocido_404(client):
    assert client.get("/admin/reentrenar/no-existe").status_code == 404


def test_reentrenar_no_disponible_503(client, deps):
    deps.orquestador = OrquestadorFalso(disponible=False)
    assert client.post("/admin/reentrenar").status_code == 503


def test_modelo_vigente(client):
    assert client.get("/modelo").json() == {"nombre": "novamercado-pronostico", "alias": "vigente", "version": "3"}


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["estado"] == "ok"


def test_health_degradado_sin_mlflow_pero_sigue_prediciendo(client, deps, modelo, pred_valida):
    deps.gestor = GestorModeloFijo(modelo, mlflow_ok=False)
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["estado"] == "degradado" and "MLflow" in r.json()["motivo"]
    assert client.post("/v1/prediccion", json=pred_valida).status_code == 200


# ---------------------------------------------------------------------- calidad

def test_estado_calidad_se_deriva_de_las_acciones():
    rep = ObservacionCalidad(campo="x", accion="reparar", detalle="d")
    adv = ObservacionCalidad(campo="y", accion="advertir", detalle="d")
    assert Calidad.desde([]).estado == "ok"
    assert Calidad.desde([rep]).estado == "corregido"
    assert Calidad.desde([rep, adv]).estado == "advertencia"
    with pytest.raises(ValidationError):
        Calidad(estado="ok", observaciones=[rep])
