"""OrquestadorAirflow contra un Airflow simulado (httpx.MockTransport): sin Airflow real."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.dependencias import Dependencias
from app.main import create_app
from app.servicios.modelo import GestorModeloFijo
from app.servicios.orquestador import NoDisponible
from app.servicios.orquestador_airflow import OrquestadorAirflow
from app.servicios.repositorio import RepositorioMemoria


class AirflowFalso:
    """Imita los endpoints de la API v2 de Airflow que usa el orquestador."""

    def __init__(self):
        self.corridas: dict[str, dict] = {}
        self.tokens_emitidos = 0
        self.token_valido = "t1"
        self.caido = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.caido:
            raise httpx.ConnectError("sin conexión")
        p = req.url.path
        if p == "/auth/token":
            self.tokens_emitidos += 1
            self.token_valido = f"t{self.tokens_emitidos}"
            return httpx.Response(201, json={"access_token": self.token_valido})
        if p == "/api/v2/monitor/health":
            return httpx.Response(200, json={"metadatabase": {"status": "healthy"}, "scheduler": {"status": "healthy"}})
        if req.headers.get("Authorization") != f"Bearer {self.token_valido}":
            return httpx.Response(401, json={"detail": "token"})
        base = "/api/v2/dags/reentrenamiento/dagRuns"
        if p == base and req.method == "POST":
            run_id = json.loads(req.content)["dag_run_id"]
            self.corridas[run_id] = {"state": "queued", "xcom": None, "fallidas": []}
            return httpx.Response(200, json={"dag_run_id": run_id, "state": "queued"})
        partes = p.removeprefix(base + "/").split("/")
        run = self.corridas.get(partes[0])
        if run is None:
            return httpx.Response(404, json={"detail": "no existe"})
        if len(partes) == 1:
            return httpx.Response(200, json={"dag_run_id": partes[0], "state": run["state"]})
        if partes[-1] == "return_value":
            if run["xcom"] is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"key": "return_value", "value": run["xcom"]})
        if partes[-1] == "taskInstances":
            return httpx.Response(200, json={"task_instances": [
                {"task_id": t, "state": "failed"} for t in run["fallidas"]]})
        return httpx.Response(404)


@pytest.fixture
def airflow():
    return AirflowFalso()


@pytest.fixture
def orq(airflow):
    return OrquestadorAirflow("http://airflow:8080", "u", "c", version_vigente=lambda: "4",
                              transporte=httpx.MockTransport(airflow))


def test_ciclo_exitoso_con_promocion(orq, airflow):
    i = orq.disparar()
    assert i.startswith("rt_") and orq.estado(i) == {"estado": "en_curso"}
    airflow.corridas[i]["state"] = "running"
    assert orq.estado(i) == {"estado": "en_curso"}
    airflow.corridas[i].update(state="success", xcom=json.dumps(
        {"estado": "exitoso", "promovido": True, "version": "5", "motivo": "Costo 1 vs 2", "version_candidata": "5"}))
    e = orq.estado(i)
    assert e["estado"] == "exitoso" and e["promovido"] is True and e["version"] == "5" and e["motivo"] == "Costo 1 vs 2"


def test_exitoso_sin_promocion_reporta_la_vigente(orq, airflow):
    i = orq.disparar()
    airflow.corridas[i].update(state="success", xcom=json.dumps(
        {"estado": "exitoso", "promovido": False, "version": "4", "motivo": "empeora"}))
    e = orq.estado(i)
    assert e["promovido"] is False and e["version"] == "4"


def test_fallido_informa_la_tarea_y_la_version_vigente(orq, airflow):
    i = orq.disparar()
    airflow.corridas[i].update(state="failed", fallidas=["validar_insumos"])
    e = orq.estado(i)
    assert e == {"estado": "fallido", "promovido": False, "version": "4",
                 "motivo": "Falló la tarea validar_insumos; el modelo vigente no cambió"}


def test_id_desconocido_es_none(orq):
    assert orq.estado("rt_no_existe") is None


def test_token_vencido_se_renueva(orq, airflow):
    i = orq.disparar()
    airflow.token_valido = "otro"  # el token del orquestador deja de valer
    assert orq.estado(i) == {"estado": "en_curso"}
    assert airflow.tokens_emitidos == 2


def test_airflow_caido(orq, airflow):
    airflow.caido = True
    assert not orq.ping()
    with pytest.raises(NoDisponible):
        orq.disparar()


def test_contrato_completo_por_la_api(airflow, orq, cat, historico, modelo):
    deps = Dependencias(cat=cat, gestor=GestorModeloFijo(modelo), repo=RepositorioMemoria(historico), orquestador=orq)
    c = TestClient(create_app(deps))
    r = c.post("/admin/reentrenar")
    assert r.status_code == 202
    i = r.json()["id"]
    assert c.get(f"/admin/reentrenar/{i}").json() == {"estado": "en_curso"}
    airflow.corridas[i].update(state="success", xcom=json.dumps(
        {"estado": "exitoso", "promovido": True, "version": "5", "motivo": "ok"}))
    assert c.get(f"/admin/reentrenar/{i}").json() == {"estado": "exitoso", "promovido": True,
                                                       "version": "5", "motivo": "ok"}
    assert c.get("/admin/reentrenar/rt_otro").status_code == 404
    airflow.caido = True
    assert c.post("/admin/reentrenar").status_code == 503
    assert c.get(f"/admin/reentrenar/{i}").status_code == 503
    h = c.get("/health").json()
    assert h["estado"] == "degradado" and "Airflow" in h["motivo"]
