"""Gestor del modelo vigente con una fuente falsa: recarga en caliente, caída de MLflow y caché."""

from fastapi.testclient import TestClient

from app.dependencias import Dependencias
from app.main import create_app
from app.servicios.modelo_mlflow import GestorModeloMLflow
from app.servicios.orquestador import OrquestadorFalso
from app.servicios.repositorio import RepositorioMemoria
from ml.modelos import ModeloBaseline, Pronosticador
from tests.conftest import FAMILIAS


class FuenteFalsa:
    def __init__(self):
        self.arriba = True
        self.alias: str | None = None
        self.falla_descarga = False
        self.descargas = 0

    def ping(self):
        return self.arriba

    def version_alias(self):
        if not self.arriba:
            raise ConnectionError("caído")
        return self.alias

    def descargar(self, version):
        if self.falla_descarga:
            raise IOError("descarga interrumpida")
        self.descargas += 1
        return Pronosticador(ModeloBaseline(), {f: 1.0 for f in FAMILIAS}, {"version_prueba": version})


def gestor(fuente, tmp_path):
    return GestorModeloMLflow(fuente, "novamercado-pronostico", "vigente", tmp_path / "cache")


def test_sin_modelo_registrado_no_hay_modelo(tmp_path):
    g = gestor(FuenteFalsa(), tmp_path)
    g.sincronizar()
    assert g.actual() is None and g.mlflow_disponible()


def test_carga_y_recarga_en_caliente_cuando_cambia_el_alias(tmp_path):
    f = FuenteFalsa()
    g = gestor(f, tmp_path)
    f.alias = "1"
    g.sincronizar()
    assert g.actual().version == "1"
    g.sincronizar()
    assert f.descargas == 1  # misma versión: no se vuelve a descargar
    f.alias = "2"
    g.sincronizar()
    assert g.actual().version == "2" and g.actual().pronosticador.info["version_prueba"] == "2"


def test_mlflow_caido_sigue_sirviendo_y_se_recupera(tmp_path):
    f = FuenteFalsa()
    g = gestor(f, tmp_path)
    f.alias = "1"
    g.sincronizar()
    f.arriba = False
    g.sincronizar()
    assert not g.mlflow_disponible() and g.actual().version == "1"
    f.arriba = True
    g.sincronizar()
    assert g.mlflow_disponible()


def test_descarga_fallida_conserva_el_modelo_actual(tmp_path):
    f = FuenteFalsa()
    g = gestor(f, tmp_path)
    f.alias = "1"
    g.sincronizar()
    f.alias, f.falla_descarga = "2", True
    g.sincronizar()
    assert g.actual().version == "1"


def test_reinicio_con_mlflow_caido_usa_la_cache(tmp_path):
    f = FuenteFalsa()
    g = gestor(f, tmp_path)
    f.alias = "4"
    g.sincronizar()
    f.arriba = False
    nuevo = gestor(f, tmp_path)  # "reinicio" del servicio
    nuevo._cargar_cache()
    nuevo.sincronizar()
    assert nuevo.actual().version == "4" and not nuevo.mlflow_disponible()


def test_api_degradada_sin_mlflow_pero_predice_con_la_version_vigente(tmp_path, cat, historico, pred_valida):
    f = FuenteFalsa()
    g = gestor(f, tmp_path)
    f.alias = "7"
    g.sincronizar()
    deps = Dependencias(cat=cat, gestor=g, repo=RepositorioMemoria(historico), orquestador=OrquestadorFalso())
    c = TestClient(create_app(deps))
    assert c.get("/health").json()["estado"] == "ok"
    f.arriba = False
    g.sincronizar()
    h = c.get("/health").json()
    assert h["estado"] == "degradado" and "MLflow" in h["motivo"]
    r = c.post("/v1/prediccion", json=pred_valida)
    assert r.status_code == 200 and r.json()["version_modelo"] == "7"
    assert c.get("/modelo").json() == {"nombre": "novamercado-pronostico", "alias": "vigente", "version": "7"}
