"""Pruebas del paquete ml con datos sintéticos (no requieren los archivos del GES)."""

import numpy as np
import pandas as pd
import pytest

from ml.catalogos import Catalogos
from ml.costos import calibrar_factores, cantidad_sugerida, costo
from ml.features import FEATURES, construir_features


@pytest.fixture
def cat():
    return Catalogos(
        tiendas=pd.DataFrame({
            "tienda_id": [1, 2], "nombre": ["A", "B"], "ciudad": ["Guatemala", "Cobán"],
            "departamento": ["G", "AV"], "tipo": ["hipermercado", "express"],
            "fecha_apertura": pd.to_datetime(["2019-01-01", "2024-01-20"]),
        }),
        familias=pd.DataFrame({"familia_id": ["abarrotes", "panaderia"], "nombre": ["Abarrotes", "Panadería"]}),
        feriados=pd.DataFrame({
            "fecha": pd.to_datetime(["2024-02-10", "2024-02-12"]), "nombre": ["X", "Y"],
            "tipo": ["feriado", "pago"], "ambito": ["nacional", "Cobán"],
        }),
        costos=pd.DataFrame({"familia_id": ["abarrotes", "panaderia"],
                             "costo_faltante": [1.0, 1.0], "costo_sobrante": [0.2, 2.5]}),
    )


@pytest.fixture
def historia():
    rng = np.random.default_rng(0)
    filas = [
        (d, t, f, int(rng.poisson(100 if t == 1 else 20)), int(rng.integers(0, 4)))
        for d in pd.date_range("2024-01-01", "2024-02-29")
        for t in [1, 2] for f in ["abarrotes", "panaderia"]
    ]
    return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])


def test_features_iguales_en_entrenamiento_y_prediccion(historia, cat):
    """La fila de entrenamiento y la de una solicitud aislada deben tener las mismas features."""
    entreno = construir_features(historia, historia, cat)
    d = pd.Timestamp("2024-02-12")
    solicitud = historia[historia.fecha == d][["fecha", "tienda_id", "familia_id", "en_promocion"]]
    pasado = historia[historia.fecha < d]  # lo único que tendría la API
    servicio = construir_features(pasado, solicitud, cat)
    a = entreno[entreno.fecha == d].sort_values(["tienda_id", "familia_id"])[FEATURES].reset_index(drop=True)
    b = servicio.sort_values(["tienda_id", "familia_id"])[FEATURES].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False)


def test_no_usa_ventas_del_mismo_dia_ni_futuras(historia, cat):
    d = pd.Timestamp("2024-02-12")
    solicitud = historia[historia.fecha == d][["fecha", "tienda_id", "familia_id", "en_promocion"]]
    alterada = historia.copy()
    alterada.loc[alterada.fecha >= d, "ventas"] = 10**6  # si se filtrara, cambiaría el resultado
    a = construir_features(historia, solicitud, cat)[FEATURES]
    b = construir_features(alterada, solicitud, cat)[FEATURES]
    pd.testing.assert_frame_equal(a, b)


def test_feriado_local_solo_en_su_ciudad(historia, cat):
    sol = pd.DataFrame({"fecha": ["2024-02-12"] * 2, "tienda_id": [1, 2],
                        "familia_id": ["abarrotes"] * 2, "en_promocion": [0, 0]})
    X = construir_features(historia, sol, cat).set_index("tienda_id")
    assert X.loc[1, "tipo_fecha"] == 0  # Guatemala: día normal
    assert X.loc[2, "tipo_fecha"] == 4  # Cobán: pago local


def test_historia_vacia_no_falla(cat):
    sol = pd.DataFrame({"fecha": ["2024-03-01"], "tienda_id": [1], "familia_id": ["abarrotes"], "en_promocion": [2]})
    vacia = pd.DataFrame(columns=["fecha", "tienda_id", "familia_id", "ventas"])
    X = construir_features(vacia, sol, cat)
    assert np.isnan(X.loc[0, "lag_1"])


def test_costo_asimetrico():
    assert costo([10], [7], 2.0, 0.1)[0] == pytest.approx(6.0)  # faltan 3 × 2.0
    assert costo([10], [15], 2.0, 0.1)[0] == pytest.approx(0.5)  # sobran 5 × 0.1


def test_cantidad_sugerida_entera_no_negativa():
    s = cantidad_sugerida([-5.0, 0.4, 10.6, np.nan], 1.0)
    assert s.dtype.kind == "i" and list(s) == [0, 0, 11, 0]


def test_factores_siguen_a_los_costos(cat):
    rng = np.random.default_rng(1)
    real = pd.Series(rng.poisson(100, 2000).astype(float))
    pred = pd.Series(np.full(2000, 100.0))
    fam = pd.Series(["abarrotes"] * 1000 + ["panaderia"] * 1000)
    f = calibrar_factores(fam, pred, real, cat.costos)
    assert f["abarrotes"] > 1.0  # faltar es caro → sugerir más
    assert f["panaderia"] < 1.0  # sobrar es caro → sugerir menos
