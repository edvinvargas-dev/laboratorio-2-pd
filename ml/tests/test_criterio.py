"""Criterio de reemplazo y ventana de evaluación (sin MLflow)."""

import pandas as pd
import pytest

from ml.criterio import Evaluacion, decidir


def ev(**kw):
    base = dict(costo_candidato=900.0, costo_baseline=1200.0, costo_vigente=1000.0,
                dias_evaluacion=14, version_vigente="3")
    return Evaluacion(**{**base, **kw})


def test_promueve_si_mejora_al_vigente():
    d = decidir(ev())
    assert d.promover and "900 vs 1 000 del vigente" in d.motivo


def test_promueve_si_empata_dentro_de_la_tolerancia():
    assert decidir(ev(costo_candidato=1015.0)).promover  # +1.5 %: no es una regresión


def test_no_promueve_si_empeora_mas_que_la_tolerancia():
    d = decidir(ev(costo_candidato=1030.0))  # +3 %
    assert not d.promover and "se conserva el vigente" in d.motivo


def test_no_promueve_si_no_supera_al_baseline():
    d = decidir(ev(costo_candidato=1300.0, costo_vigente=2000.0))
    assert not d.promover and "baseline" in d.motivo


def test_sin_vigente_promueve_si_supera_baseline():
    assert decidir(ev(version_vigente=None, costo_vigente=None)).promover


def test_vigente_no_evaluable_promueve():
    assert decidir(ev(costo_vigente=None)).promover


def test_pocos_dias_no_promueve():
    d = decidir(ev(dias_evaluacion=3))
    assert not d.promover and "3 días" in d.motivo


@pytest.mark.parametrize("kw", [{"candidato_valido": False, "problema_candidato": "negativos"},
                                {"costo_candidato": float("nan")}])
def test_candidato_invalido_no_promueve(kw):
    assert not decidir(ev(**kw)).promover


def test_ventana_usa_solo_dias_no_vistos_por_el_vigente():
    from ml.modelos import ModeloBaseline, Pronosticador
    from ml.pipeline import _ventana
    from ml.registro import ModeloRegistrado

    fin = pd.Timestamp("2026-03-20")
    vig = ModeloRegistrado(Pronosticador(ModeloBaseline(), {}, {"datos_hasta": "2026-03-10"}), "2")
    inicio, nuevos = _ventana(fin, vig)
    assert inicio == pd.Timestamp("2026-03-11") and nuevos == 10
    # Con muchos días nuevos la ventana se limita a los últimos 28
    vig.pronosticador.info["datos_hasta"] = "2025-12-31"
    assert _ventana(fin, vig)[0] == pd.Timestamp("2026-02-21")
    assert _ventana(fin, None) == (pd.Timestamp("2026-02-21"), 28)
