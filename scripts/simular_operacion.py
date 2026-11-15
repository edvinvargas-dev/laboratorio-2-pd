"""Simula la operación diaria de las tiendas contra la API (evaluador propio).

Las "ventas reales" de cada día simulado salen del histórico de un año antes,
multiplicadas por `--factor` (permite simular un cambio de demanda). Cada día:
  1. se envía la observación del día anterior;
  2. se pide el pronóstico del día (con las promociones del histórico).
Al final se reporta el costo de las cantidades sugeridas.

Uso:
  python scripts/simular_operacion.py --desde 2026-03-01 --dias 10 --factor 1.25
Solo usa la biblioteca estándar más pandas.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd


def post(url: str, cuerpo: dict | None) -> tuple[int, dict]:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--data", default="data")
    ap.add_argument("--desde", default="2026-03-01")
    ap.add_argument("--dias", type=int, default=7)
    ap.add_argument("--factor", type=float, default=1.0, help="multiplica la demanda (cambio de comportamiento)")
    ap.add_argument("--tiendas", default="", help="ej. 1,5,10 (vacío = todas)")
    a = ap.parse_args()

    hist = pd.read_csv(Path(a.data) / "historico_ventas.csv", parse_dates=["fecha"])
    costos = pd.read_csv(Path(a.data) / "costos.csv").set_index("familia_id")
    tiendas = [int(t) for t in a.tiendas.split(",")] if a.tiendas else sorted(hist.tienda_id.unique())

    def reales(dia: pd.Timestamp) -> pd.DataFrame:
        base = hist[(hist.fecha == dia - pd.DateOffset(years=1)) & hist.tienda_id.isin(tiendas)].copy()
        base["ventas"] = (base.ventas * a.factor).round().astype(int)
        base["fecha"] = dia
        return base

    inicio = pd.Timestamp(a.desde)
    costo_total, filas = 0.0, 0
    for i in range(a.dias):
        dia = inicio + pd.Timedelta(days=i)
        if i > 0:  # 1. observación de ayer
            ayer = reales(dia - pd.Timedelta(days=1))
            for t, g in ayer.groupby("tienda_id"):
                s, r = post(f"{a.url}/v1/observaciones", {
                    "tienda_id": int(t), "fecha": str((dia - pd.Timedelta(days=1)).date()),
                    "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(g.familia_id, g.ventas)]})
                if s != 200:
                    print("observación", t, s, r)
        hoy = reales(dia)  # 2. pronóstico de hoy
        costo_dia = 0.0
        for t, g in hoy.groupby("tienda_id"):
            s, r = post(f"{a.url}/v1/prediccion", {
                "tienda_id": int(t), "fecha": str(dia.date()),
                "familias": [{"familia_id": f, "en_promocion": int(p)} for f, p in zip(g.familia_id, g.en_promocion)]})
            if s != 200:
                print("predicción", t, s, r)
                continue
            real = dict(zip(g.familia_id, g.ventas))
            for p in r["predicciones"]:
                cf, cs = costos.loc[p["familia_id"], ["costo_faltante", "costo_sobrante"]]
                v, q = real[p["familia_id"]], p["cantidad_sugerida"]
                costo_dia += cf * max(v - q, 0) + cs * max(q - v, 0)
                filas += 1
        costo_total += costo_dia
        print(f"{dia.date()}  versión={r.get('version_modelo')}  costo del día={costo_dia:,.0f}")
    # observación del último día, para que el reentrenamiento la vea
    ultimo = inicio + pd.Timedelta(days=a.dias - 1)
    for t, g in reales(ultimo).groupby("tienda_id"):
        post(f"{a.url}/v1/observaciones", {
            "tienda_id": int(t), "fecha": str(ultimo.date()),
            "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(g.familia_id, g.ventas)]})
    print(f"\nCosto total {costo_total:,.0f} en {filas} predicciones ({a.dias} días, factor {a.factor})")


if __name__ == "__main__":
    main()
