"""Exporta evidencia de funcionamiento desde las APIs de MLflow y Airflow a Markdown.

  evidencia/mlflow.md   experimento, runs con métricas y linaje, versiones y alias
  evidencia/airflow.md  ejecuciones del DAG de reentrenamiento, tareas y resultado

Uso:  python scripts/exportar_evidencia.py [--env .env]
Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

MODELO = "novamercado-pronostico"
EXPERIMENTO = "novamercado-pronostico"


def pedir(url: str, metodo: str = "GET", cuerpo: dict | None = None, token: str | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=datos, method=metodo, headers=h), timeout=30) as r:
        return json.loads(r.read() or b"{}")


def fecha_ms(ms) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S") if ms else ""


def leer_env(ruta: str) -> dict:
    d = {}
    if Path(ruta).exists():
        for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                d[k.strip()] = v.strip()
    return d


# ------------------------------------------------------------------- MLflow


def evidencia_mlflow(url: str) -> str:
    exp = pedir(f"{url}/api/2.0/mlflow/experiments/get-by-name?experiment_name={EXPERIMENTO}")["experiment"]
    runs = pedir(f"{url}/api/2.0/mlflow/runs/search", "POST", {
        "experiment_ids": [exp["experiment_id"]], "max_results": 100,
        "order_by": ["attributes.start_time ASC"]}).get("runs", [])
    modelo = pedir(f"{url}/api/2.0/mlflow/registered-models/get?name={MODELO}")["registered_model"]
    filtro = urllib.parse.quote(f"name='{MODELO}'")
    versiones = pedir(f"{url}/api/2.0/mlflow/model-versions/search?filter={filtro}&max_results=100").get(
        "model_versions", [])
    versiones.sort(key=lambda v: int(v["version"]))
    alias = {a["version"]: a["alias"] for a in modelo.get("aliases", [])}

    L = [f"# Evidencia: MLflow\n", f"Exportado {dt.datetime.now():%Y-%m-%d %H:%M} desde `{url}`.\n",
         f"## Model Registry: `{MODELO}`\n",
         "Alias: " + ", ".join(f"`{a['alias']}` → versión {a['version']}" for a in modelo.get("aliases", [])) + "\n",
         "| Versión | Alias | Creada | Datos hasta | Promovido | Motivo |", "|---|---|---|---|---|---|"]
    for v in versiones:
        tags = {t["key"]: t["value"] for t in v.get("tags", [])}
        L.append(f"| {v['version']} | {alias.get(v['version'], '')} | {fecha_ms(v.get('creation_timestamp'))} | "
                 f"{tags.get('datos_hasta', '')} | {tags.get('promovido', '')} | {tags.get('motivo', '')} |")

    L += [f"\n## Experimento `{EXPERIMENTO}`: runs\n",
          "| Run | Inicio | Origen | Datos hasta | Costo prueba | Costo baseline | Costo vigente | MAE | WAPE |"
          " Filas | Promovido |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        m = {x["key"]: x["value"] for x in r["data"].get("metrics", [])}
        p = {x["key"]: x["value"] for x in r["data"].get("params", [])}
        t = {x["key"]: x["value"] for x in r["data"].get("tags", [])}

        def n(k):
            return f"{m[k]:,.0f}" if k in m else "—"
        L.append(f"| `{r['info']['run_id'][:8]}` | {fecha_ms(r['info']['start_time'])} | {t.get('origen', '')} | "
                 f"{p.get('datos_hasta', '')} | {n('costo')} | {n('costo_baseline')} | {n('costo_vigente')} | "
                 f"{m.get('mae', 0):.1f} | {m.get('wape', 0):.3f} | {p.get('n_filas', '')} | {t.get('promovido', '')} |")

    if runs:
        ult = runs[-1]
        L += ["\n## Linaje del último run\n",
              f"- run `{ult['info']['run_id']}` · artefactos: `{ult['info'].get('artifact_uri', '')}`",
              "- parámetros: " + ", ".join(f"`{x['key']}={x['value']}`" for x in ult["data"].get("params", [])
                                           if not x["key"].startswith("lgbm_")),
              "- etiquetas: " + ", ".join(f"`{x['key']}={x['value']}`" for x in ult["data"].get("tags", [])
                                          if not x["key"].startswith("mlflow.")),
              "- entradas registradas: " + ", ".join(
                  d["dataset"]["name"] for d in ult.get("inputs", {}).get("dataset_inputs", [])),
              "- artefactos: `modelo/` (pyfunc + pronosticador.pkl), `factores_cantidad_sugerida.json`, "
              "`datos_entrenamiento.json`, `importancia_features.json`"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ Airflow


def evidencia_airflow(url: str, usuario: str, clave: str) -> str:
    token = pedir(f"{url}/auth/token", "POST", {"username": usuario, "password": clave})["access_token"]
    base = f"{url}/api/v2/dags/reentrenamiento"
    dag = pedir(base, token=token)
    corridas = pedir(f"{base}/dagRuns?order_by=start_date&limit=100", token=token).get("dag_runs", [])
    L = ["# Evidencia: Airflow\n", f"Exportado {dt.datetime.now():%Y-%m-%d %H:%M} desde `{url}`.\n",
         f"DAG `{dag['dag_id']}` · pausado: {dag['is_paused']} · archivo `{dag.get('relative_fileloc')}`\n",
         "| dag_run_id | Inicio | Duración | Estado | Tareas | Resultado |", "|---|---|---|---|---|---|"]
    for c in corridas:
        tis = pedir(f"{base}/dagRuns/{c['dag_run_id']}/taskInstances", token=token).get("task_instances", [])
        tareas = ", ".join(f"{t['task_id']}={t['state']}" for t in sorted(tis, key=lambda t: t.get("start_date") or ""))
        try:
            x = pedir(f"{base}/dagRuns/{c['dag_run_id']}/taskInstances/reentrenar/xcomEntries/return_value",
                      token=token)["value"]
            x = json.loads(x) if isinstance(x, str) else x
            res = f"promovido={x.get('promovido')} v{x.get('version')}: {x.get('motivo')}"
        except Exception:
            res = "—"
        ini, fin = c.get("start_date"), c.get("end_date")
        dur = ""
        if ini and fin:
            dur = f"{(dt.datetime.fromisoformat(fin.replace('Z', '+00:00')) - dt.datetime.fromisoformat(ini.replace('Z', '+00:00'))).total_seconds():.0f} s"
        L.append(f"| `{c['dag_run_id']}` | {(ini or '')[:19]} | {dur} | {c['state']} | {tareas} | {res} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env")
    ap.add_argument("--mlflow", default="http://localhost:5050")
    ap.add_argument("--airflow", default="http://localhost:8080")
    ap.add_argument("--salida", default="evidencia")
    a = ap.parse_args()
    env = leer_env(a.env)
    out = Path(a.salida)
    out.mkdir(exist_ok=True)
    (out / "mlflow.md").write_text(evidencia_mlflow(a.mlflow), encoding="utf-8")
    (out / "airflow.md").write_text(
        evidencia_airflow(a.airflow, env.get("AIRFLOW_USUARIO", "novamercado"), env.get("AIRFLOW_CLAVE", "")),
        encoding="utf-8")
    print(f"evidencia escrita en {out / 'mlflow.md'} y {out / 'airflow.md'}")


if __name__ == "__main__":
    main()
