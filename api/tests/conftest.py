"""Fixtures: catálogo y datos sintéticos, modelo baseline, dependencias en memoria.

Nada aquí requiere MLflow, PostgreSQL, Airflow ni los archivos del GES.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.dependencias import Dependencias
from app.main import create_app
from app.servicios.modelo import GestorModeloFijo, ModeloCargado
from app.servicios.orquestador import OrquestadorFalso
from app.servicios.repositorio import RepositorioMemoria
from ml.catalogos import Catalogos
from ml.modelos import ModeloBaseline, Pronosticador

FAMILIAS = ["abarrotes", "bebe", "bebidas", "carnes", "cuidado_personal", "frutas_verduras",
            "lacteos", "licores", "limpieza", "mascotas", "panaderia", "snacks"]
FECHA = "2025-11-17"


@pytest.fixture
def cat():
    return Catalogos(
        tiendas=pd.DataFrame({
            "tienda_id": [1, 5, 10],
            "nombre": ["NovaMercado Zona 10", "NovaMercado Quetzaltenango", "NovaMercado Express Zona 16"],
            "ciudad": ["Guatemala", "Quetzaltenango", "Guatemala"], "departamento": ["G", "Q", "G"],
            "tipo": ["hipermercado", "hipermercado", "express"],
            "fecha_apertura": pd.to_datetime(["2019-01-01", "2019-01-01", "2025-03-15"]),
        }),
        familias=pd.DataFrame({"familia_id": FAMILIAS, "nombre": [
            "Abarrotes", "Bebé", "Bebidas", "Carnes", "Cuidado personal", "Frutas y verduras",
            "Lácteos", "Licores", "Limpieza", "Mascotas", "Panadería", "Snacks y dulces"]}),
        feriados=pd.DataFrame({"fecha": pd.to_datetime(["2024-03-28", "2025-11-01", "2026-12-31"]),
                               "nombre": ["Jueves Santo", "Todos los Santos", "Fin de año"],
                               "tipo": ["feriado", "feriado", "medio_dia"], "ambito": ["nacional"] * 3}),
        costos=pd.DataFrame({"familia_id": FAMILIAS, "costo_faltante": 1.0, "costo_sobrante": 0.5}),
    )


@pytest.fixture
def historico():
    rng = np.random.default_rng(0)
    filas = [(d, t, f, int(rng.poisson(50)), 0)
             for d in pd.date_range("2025-09-15", "2025-11-16") for t in [1, 5, 10] for f in FAMILIAS]
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


@pytest.fixture
def modelo():
    pron = Pronosticador(ModeloBaseline(), {f: 1.2 for f in FAMILIAS})
    return ModeloCargado(pron, nombre="novamercado-pronostico", alias="vigente", version="3")


@pytest.fixture
def deps(cat, historico, modelo):
    return Dependencias(cat=cat, gestor=GestorModeloFijo(modelo), repo=RepositorioMemoria(historico),
                        orquestador=OrquestadorFalso())


@pytest.fixture
def client(deps):
    return TestClient(create_app(deps))


@pytest.fixture
def pred_valida():
    return {"tienda_id": 5, "fecha": FECHA,
            "familias": [{"familia_id": f, "en_promocion": i % 3} for i, f in enumerate(FAMILIAS)]}


@pytest.fixture
def obs_valida():
    return {"tienda_id": 5, "fecha": FECHA,
            "ventas": [{"familia_id": f, "ventas": 40 + i} for i, f in enumerate(FAMILIAS)]}
