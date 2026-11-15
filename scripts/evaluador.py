"""Evaluador propio: simula la operación diaria tal como la describe el enunciado.

Durante `--dias` días posteriores al histórico:
  - cada día, primero las observaciones del día anterior y luego las solicitudes de
    pronóstico de todas las tiendas; una fracción llega con defectos que NO están en el
    catálogo (otros nombres de campo, formatos de fecha y número, familias mal escritas…);
  - reentrenamientos periódicos por POST /admin/reentrenar (se espera su resultado);
  - una interrupción de MLflow (se mide cuánto tarda /health en reflejarla);
  - un `docker compose down` + `up` sin borrar volúmenes;
  - un cambio de demanda a partir de `--dia-cambio` (factor `--factor-cambio`).

Cada respuesta se valida contra el contrato. Al final se compara el costo de las
cantidades sugeridas con el de un baseline (mediana del mismo día de la semana en las
4 semanas previas, sugerida tal cual) y se escribe un reporte en Markdown y JSON.

Las ventas "reales" de cada día salen del histórico de 52 semanas antes (mismo día de
la semana), multiplicadas por el factor de demanda vigente.

Uso:
  python scripts/evaluador.py --proyecto nmeval --dir-compose RUTA [--dias 28]
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- http


def http(metodo: str, url: str, cuerpo=None, timeout: int = 60) -> tuple[int, dict]:
    datos = None if cuerpo is None else (cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode())
    req = urllib.request.Request(url, data=datos, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {}
    except Exception as e:  # servicio caído
        return 0, {"error": str(e)}


# ----------------------------------------------------------------- contrato


def validar_calidad(c) -> list[str]:
    err = []
    if not isinstance(c, dict) or c.get("estado") not in ("ok", "corregido", "advertencia"):
        return [f"calidad inválida: {c}"]
    obs = c.get("observaciones", [])
    acciones = {o.get("accion") for o in obs}
    if not acciones <= {"reparar", "advertir"}:
        err.append(f"acción inválida {acciones}")
    esperado = "advertencia" if "advertir" in acciones else "corregido" if acciones else "ok"
    if c["estado"] != esperado:
        err.append(f"estado {c['estado']} incoherente con acciones {acciones}")
    for o in obs:
        if not all(isinstance(o.get(k), str) for k in ("campo", "accion", "detalle")):
            err.append(f"observación mal formada {o}")
    return err


def validar_prediccion(r: dict, tienda: int, fecha: str, familias: set[str]) -> list[str]:
    err = []
    for k in ("tienda_id", "fecha", "version_modelo", "predicciones", "calidad"):
        if k not in r:
            err.append(f"falta {k}")
    if err:
        return err
    if r["tienda_id"] != tienda or r["fecha"] != fecha:
        err.append(f"tienda/fecha {r['tienda_id']}/{r['fecha']} ≠ {tienda}/{fecha}")
    if not isinstance(r["version_modelo"], str):
        err.append("version_modelo no es texto")
    vistas = set()
    for p in r["predicciones"]:
        if not isinstance(p.get("cantidad_sugerida"), int) or isinstance(p.get("cantidad_sugerida"), bool) \
                or p["cantidad_sugerida"] < 0:
            err.append(f"cantidad_sugerida inválida {p}")
        if not isinstance(p.get("venta_esperada"), (int, float)):
            err.append(f"venta_esperada inválida {p}")
        vistas.add(p.get("familia_id"))
    if not familias <= vistas:
        err.append(f"faltan predicciones para {sorted(familias - vistas)}")
    return err + validar_calidad(r["calidad"])


def validar_observacion(r: dict) -> list[str]:
    if not isinstance(r.get("registros_guardados"), int) or r["registros_guardados"] < 0:
        return [f"registros_guardados inválido {r}"]
    return validar_calidad(r.get("calidad"))


# ---------------------------------------------------- defectos fuera del catálogo

NOMBRES_FAMILIA = {
    "abarrotes": ["ABARROTES", "Abarrotes ", "abarrote"], "bebe": ["Bebé", "BEBÉ", "bebes"],
    "bebidas": ["Bebidas", "bebida"], "carnes": ["CARNES", "Carne"],
    "cuidado_personal": ["Cuidado Personal", "cuidado-personal", "CuidadoPersonal"],
    "frutas_verduras": ["Frutas y verduras", "FRUTAS_VERDURAS"], "lacteos": ["Lácteos", "lácteo"],
    "licores": ["Licores", "LICOR"], "limpieza": ["Limpieza", "limpiesa"],
    "mascotas": ["Mascotas", "mascota"], "panaderia": ["Panadería", "PANADERIA"],
    "snacks": ["Snacks y dulces", "SNACKS"],
}


def defectuosa_prediccion(sol: dict, rng: random.Random) -> tuple[dict, str]:
    s = json.loads(json.dumps(sol))
    tipo = rng.choice(["clave_tienda", "fecha", "tienda_texto", "familia_nombre", "promo_formato",
                       "campo_extra", "familias_objeto", "clave_promo", "envuelta", "promo_nula"])
    if tipo == "clave_tienda":
        s[rng.choice(["TiendaID", "store_id", "idTienda"])] = s.pop("tienda_id")
    elif tipo == "fecha":
        f = pd.Timestamp(s["fecha"])
        s["fecha"] = rng.choice([f.strftime("%Y/%m/%d"), f.strftime("%Y-%m-%d 00:00:00"),
                                 f.strftime("%d-%m-%Y") if f.day > 12 else f.strftime("%Y%m%d"),
                                 f"{f.day} de {['enero','febrero','marzo','abril'][f.month-1]} de {f.year}"])
    elif tipo == "tienda_texto":
        s["tienda_id"] = rng.choice([f"Tienda-{s['tienda_id']}", f" {s['tienda_id']} ", float(s["tienda_id"]),
                                     f"T{s['tienda_id']:03d}"])
    elif tipo == "familia_nombre":
        for f in rng.sample(s["familias"], 3):
            f["familia_id"] = rng.choice(NOMBRES_FAMILIA[f["familia_id"]])
    elif tipo == "promo_formato":
        for f in rng.sample(s["familias"], 3):
            f["en_promocion"] = rng.choice([str(f["en_promocion"]), float(f["en_promocion"]), f" {f['en_promocion']} "])
    elif tipo == "campo_extra":
        s[rng.choice(["canal", "version_cliente", "usuario"])] = "pos-7"
    elif tipo == "familias_objeto":
        s["familias"] = {f["familia_id"]: f["en_promocion"] for f in s["familias"]}
    elif tipo == "clave_promo":
        for f in s["familias"]:
            f["promocion"] = f.pop("en_promocion")
    elif tipo == "envuelta":
        s = {"solicitud": s}
    elif tipo == "promo_nula":
        rng.choice(s["familias"])["en_promocion"] = None
    return s, tipo


def defectuosa_observacion(obs: dict, rng: random.Random) -> tuple[dict, str]:
    o = json.loads(json.dumps(obs))
    tipo = rng.choice(["miles", "decimal_coma", "clave_ventas", "fecha", "familia_nombre"])
    if tipo == "miles":
        for v in o["ventas"]:
            if v["ventas"] >= 1000:
                v["ventas"] = f"{v['ventas']:,}"
    elif tipo == "decimal_coma":
        v = rng.choice(o["ventas"])
        v["ventas"] = f"{v['ventas']},0"
    elif tipo == "clave_ventas":
        for v in o["ventas"]:
            v["unidades"] = v.pop("ventas")
    elif tipo == "fecha":
        f = pd.Timestamp(o["fecha"])
        o["fecha"] = f.strftime("%Y/%m/%d")
    elif tipo == "familia_nombre":
        for v in rng.sample(o["ventas"], 2):
            v["familia_id"] = rng.choice(NOMBRES_FAMILIA[v["familia_id"]])
    return o, tipo


# ----------------------------------------------------------------- operación


class Evaluador:
    def __init__(self, a):
        self.a = a
        self.url = a.url.rstrip("/")
        self.rng = random.Random(a.semilla)
        self.hist = pd.read_csv(Path(a.data) / "historico_ventas.csv", parse_dates=["fecha"])
        c = pd.read_csv(Path(a.data) / "costos.csv").set_index("familia_id")
        self.cf, self.cs = c.costo_faltante.to_dict(), c.costo_sobrante.to_dict()
        self.tiendas = sorted(self.hist.tienda_id.unique())
        self.inicio = pd.Timestamp(a.desde)
        self.conocidas = self.hist[["fecha", "tienda_id", "familia_id", "ventas"]].copy()  # para el baseline
        self.errores: list[str] = []
        self.eventos: list[dict] = []
        self.filas: list[dict] = []
        self.calidad = Counter()
        self.defectos = Counter()
        self.status = Counter()
        self.versiones = Counter()

    def log(self, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def factor(self, dia: pd.Timestamp) -> float:
        return self.a.factor_cambio if (dia - self.inicio).days >= self.a.dia_cambio else 1.0

    def reales(self, dia: pd.Timestamp) -> pd.DataFrame:
        b = self.hist[self.hist.fecha == dia - pd.Timedelta(days=364)].copy()
        b["ventas"] = (b.ventas * self.factor(dia)).round().astype(int)
        b["fecha"] = dia
        return b

    def compose(self, *args: str) -> None:
        subprocess.run(["docker", "compose", "-p", self.a.proyecto, *args], cwd=self.a.dir_compose,
                       check=True, capture_output=True)

    def esperar_health(self, patron: str, max_seg: int) -> float | None:
        t0 = time.time()
        while time.time() - t0 < max_seg:
            s, r = http("GET", f"{self.url}/health", timeout=5)
            if s == 200 and r.get("estado") == patron:
                return round(time.time() - t0, 1)
            time.sleep(2)
        return None

    # ------------------------------------------------------------- un día

    def observar(self, dia: pd.Timestamp) -> None:
        r = self.reales(dia)
        self.conocidas = pd.concat([self.conocidas, r[["fecha", "tienda_id", "familia_id", "ventas"]]])
        for t, g in r.groupby("tienda_id"):
            obs = {"tienda_id": int(t), "fecha": str(dia.date()),
                   "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(g.familia_id, g.ventas)]}
            if self.rng.random() < self.a.prob_defecto:
                obs, tipo = defectuosa_observacion(obs, self.rng)
                self.defectos[f"obs:{tipo}"] += 1
            s, resp = http("POST", f"{self.url}/v1/observaciones", obs)
            self.status[f"obs {s}"] += 1
            if s != 200:
                self.errores.append(f"{dia.date()} obs tienda {t}: HTTP {s} {resp}")
                continue
            for e in validar_observacion(resp):
                self.errores.append(f"{dia.date()} obs tienda {t}: {e}")
            self.calidad[f"obs {resp['calidad']['estado']}"] += 1
            if self.rng.random() < 0.1:  # reenvío idéntico: debe guardar 0
                s2, r2 = http("POST", f"{self.url}/v1/observaciones", obs)
                if s2 != 200 or r2.get("registros_guardados") != 0:
                    self.errores.append(f"{dia.date()} reenvío tienda {t}: {s2} {r2}")

    def baseline(self, dia: pd.Timestamp) -> dict[tuple[int, str], int]:
        previas = self.conocidas[self.conocidas.fecha.isin([dia - pd.Timedelta(days=7 * k) for k in (1, 2, 3, 4)])]
        return previas.groupby(["tienda_id", "familia_id"]).ventas.median().round().astype(int).to_dict()

    def pronosticar(self, dia: pd.Timestamp) -> None:
        r = self.reales(dia)
        base = self.baseline(dia)
        for t, g in r.groupby("tienda_id"):
            sol = {"tienda_id": int(t), "fecha": str(dia.date()),
                   "familias": [{"familia_id": f, "en_promocion": int(p)} for f, p in zip(g.familia_id, g.en_promocion)]}
            enviada, tipo = sol, "valida"
            if self.rng.random() < self.a.prob_defecto:
                enviada, tipo = defectuosa_prediccion(sol, self.rng)
                self.defectos[f"pred:{tipo}"] += 1
            s, resp = http("POST", f"{self.url}/v1/prediccion", enviada)
            self.status[f"pred {s}"] += 1
            if s != 200:
                self.errores.append(f"{dia.date()} pred tienda {t} ({tipo}): HTTP {s} {resp}")
                continue
            for e in validar_prediccion(resp, int(t), str(dia.date()), set(g.familia_id)):
                self.errores.append(f"{dia.date()} pred tienda {t} ({tipo}): {e}")
            self.calidad[f"pred {resp['calidad']['estado']}"] += 1
            self.versiones[resp["version_modelo"]] += 1
            reales = dict(zip(g.familia_id, g.ventas))
            for p in resp["predicciones"]:
                f = p["familia_id"]
                if f not in reales:
                    continue
                v, q, b = reales[f], p["cantidad_sugerida"], base.get((int(t), f), p["cantidad_sugerida"])
                self.filas.append({
                    "fecha": dia, "tienda_id": int(t), "familia_id": f, "real": v, "sugerida": q,
                    "esperada": p["venta_esperada"], "baseline": b, "version": resp["version_modelo"],
                    "costo": self.cf[f] * max(v - q, 0) + self.cs[f] * max(q - v, 0),
                    "costo_baseline": self.cf[f] * max(v - b, 0) + self.cs[f] * max(b - v, 0),
                })

    # ------------------------------------------------------------- eventos

    def reentrenar(self, dia) -> None:
        t0 = time.time()
        s, r = http("POST", f"{self.url}/admin/reentrenar")
        if s != 202:
            self.errores.append(f"{dia.date()} reentrenar: HTTP {s} {r}")
            self.eventos.append({"dia": str(dia.date()), "evento": "reentrenar", "status": s})
            return
        i = r["id"]
        while time.time() - t0 < 660:
            s, e = http("GET", f"{self.url}/admin/reentrenar/{i}")
            if e.get("estado") in ("exitoso", "fallido"):
                break
            time.sleep(5)
        dur = time.time() - t0
        espera_modelo = None
        if e.get("promovido"):
            t1 = time.time()
            while time.time() - t1 < 150:
                if http("GET", f"{self.url}/modelo")[1].get("version") == e.get("version"):
                    espera_modelo = time.time() - t1
                    break
                time.sleep(2)
            if espera_modelo is None:
                self.errores.append(f"{dia.date()} el servicio no adoptó la versión {e.get('version')} en 150 s")
        for k in ("estado", "promovido", "version", "motivo"):
            if k not in e:
                self.errores.append(f"{dia.date()} estado de reentrenamiento sin '{k}': {e}")
        self.log(f"reentrenamiento {e.get('estado')} en {dur:.0f} s: promovido={e.get('promovido')} "
                 f"v{e.get('version')} — {e.get('motivo')}")
        self.eventos.append({"dia": str(dia.date()), "evento": "reentrenar", "segundos": round(dur),
                             "adopcion_seg": None if espera_modelo is None else round(espera_modelo), **e})

    def caida_mlflow(self, dia) -> None:
        self.compose("stop", "mlflow")
        t_deg = self.esperar_health("degradado", 120)
        s, r = http("GET", f"{self.url}/modelo")
        self.log(f"MLflow detenido: health degradado en {t_deg} s; /modelo {s} {r}")
        if t_deg is None or t_deg > 60:
            self.errores.append(f"health no reflejó la caída de MLflow en 60 s ({t_deg})")
        self.eventos.append({"dia": str(dia.date()), "evento": "mlflow_detenido", "degradado_seg": t_deg})

    def vuelta_mlflow(self, dia) -> None:
        self.compose("start", "mlflow")
        t_ok = self.esperar_health("ok", 240)
        self.log(f"MLflow iniciado: health ok en {t_ok} s")
        if t_ok is None or t_ok > 120:
            self.errores.append(f"health no volvió a ok en 120 s tras MLflow ({t_ok})")
        self.eventos.append({"dia": str(dia.date()), "evento": "mlflow_iniciado", "ok_seg": t_ok})

    def reinicio(self, dia) -> None:
        self.compose("down")
        t0 = time.time()
        self.compose("up", "-d")
        t_ok = self.esperar_health("ok", 600)
        self.log(f"down + up: health ok en {t_ok} s")
        if t_ok is None:
            self.errores.append("el producto no volvió a ok en 10 min tras down/up")
        self.eventos.append({"dia": str(dia.date()), "evento": "down_up", "ok_seg": t_ok,
                             "total_seg": round(time.time() - t0)})

    # ------------------------------------------------------------- correr

    def correr(self) -> dict:
        a = self.a
        for i in range(a.dias):
            dia = self.inicio + pd.Timedelta(days=i)
            if i > 0:
                self.observar(dia - pd.Timedelta(days=1))
            if i == a.dia_caida_mlflow:
                self.caida_mlflow(dia)
            if i == a.dia_caida_mlflow + 2:
                self.vuelta_mlflow(dia)
            if i == a.dia_reinicio:
                self.reinicio(dia)
            if i > 0 and i % a.cada_reentreno == 0:
                self.reentrenar(dia)
            self.pronosticar(dia)
            costo = sum(f["costo"] for f in self.filas if f["fecha"] == dia)
            base = sum(f["costo_baseline"] for f in self.filas if f["fecha"] == dia)
            self.log(f"{dia.date()} factor={self.factor(dia):.2f} costo={costo:,.0f} baseline={base:,.0f} "
                     f"errores={len(self.errores)}")
        self.observar(self.inicio + pd.Timedelta(days=a.dias - 1))
        return self.reporte()

    def reporte(self) -> dict:
        df = pd.DataFrame(self.filas)
        df["semana"] = ((df.fecha - self.inicio).dt.days // 7) + 1
        por_semana = df.groupby("semana").agg(costo=("costo", "sum"), costo_baseline=("costo_baseline", "sum"),
                                              mae=("esperada", lambda s: np.nan))
        por_semana["mae"] = df.assign(e=(df.esperada - df.real).abs()).groupby("semana").e.mean()
        por_semana["ahorro_vs_baseline"] = 1 - por_semana.costo / por_semana.costo_baseline
        por_familia = df.groupby("familia_id")[["costo", "costo_baseline"]].sum()
        total, total_b = df.costo.sum(), df.costo_baseline.sum()
        return {
            "dias": self.a.dias, "predicciones": len(df), "errores_contrato": self.errores,
            "costo_total": round(total), "costo_baseline": round(total_b),
            "ahorro_vs_baseline": round(1 - total / total_b, 4),
            "mae": round(float((df.esperada - df.real).abs().mean()), 2),
            "por_semana": por_semana.round(3).reset_index().to_dict("records"),
            "por_familia": por_familia.round(0).reset_index().to_dict("records"),
            "calidad": dict(self.calidad), "defectos_enviados": dict(self.defectos),
            "status_http": dict(self.status), "versiones_usadas": dict(self.versiones), "eventos": self.eventos,
        }


def escribir_markdown(r: dict, ruta: Path, a) -> None:
    L = [f"# Evaluación de operación simulada\n",
         f"Periodo: {a.desde} + {a.dias} días · cambio de demanda ×{a.factor_cambio} desde el día {a.dia_cambio} · "
         f"{a.prob_defecto:.0%} de solicitudes con defectos fuera del catálogo · semilla {a.semilla}\n",
         "## Resultado\n",
         f"| Métrica | Valor |\n|---|---|",
         f"| Predicciones evaluadas | {r['predicciones']} |",
         f"| Errores de contrato | **{len(r['errores_contrato'])}** |",
         f"| Costo del servicio | {r['costo_total']:,} |",
         f"| Costo del baseline | {r['costo_baseline']:,} |",
         f"| Ahorro frente al baseline | **{r['ahorro_vs_baseline']:.1%}** |",
         f"| MAE de la venta esperada | {r['mae']} |\n",
         "## Por semana\n", "| Semana | Costo | Baseline | Ahorro | MAE |", "|---|---|---|---|---|"]
    for s in r["por_semana"]:
        L.append(f"| {s['semana']} | {s['costo']:,.0f} | {s['costo_baseline']:,.0f} | "
                 f"{s['ahorro_vs_baseline']:.1%} | {s['mae']:.1f} |")
    L += ["\n## Eventos\n", "| Día | Evento | Detalle |", "|---|---|---|"]
    for e in r["eventos"]:
        det = {k: v for k, v in e.items() if k not in ("dia", "evento")}
        L.append(f"| {e['dia']} | {e['evento']} | {json.dumps(det, ensure_ascii=False)} |")
    L += ["\n## Calidad de las respuestas\n", "```", json.dumps(r["calidad"], ensure_ascii=False, indent=1), "```",
          "\n## Defectos enviados (no están en el catálogo)\n", "```",
          json.dumps(r["defectos_enviados"], ensure_ascii=False, indent=1), "```",
          "\n## Versiones del modelo que respondieron\n", "```", json.dumps(r["versiones_usadas"]), "```",
          "\n## Errores de contrato\n"]
    L += [f"- {e}" for e in r["errores_contrato"][:50]] or ["Ninguno."]
    ruta.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--data", default="data")
    ap.add_argument("--proyecto", required=True, help="nombre del proyecto de docker compose")
    ap.add_argument("--dir-compose", default=".", help="carpeta con docker-compose.yml")
    ap.add_argument("--desde", default="2026-03-01")
    ap.add_argument("--dias", type=int, default=28)
    ap.add_argument("--cada-reentreno", type=int, default=7)
    ap.add_argument("--dia-caida-mlflow", type=int, default=9)
    ap.add_argument("--dia-reinicio", type=int, default=17)
    ap.add_argument("--dia-cambio", type=int, default=14)
    ap.add_argument("--factor-cambio", type=float, default=1.3)
    ap.add_argument("--prob-defecto", type=float, default=0.3)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", default="evidencia/evaluacion")
    a = ap.parse_args()

    r = Evaluador(a).correr()
    salida = Path(a.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.with_suffix(".json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    escribir_markdown(r, salida.with_suffix(".md"), a)
    print(f"\nErrores de contrato: {len(r['errores_contrato'])} · costo {r['costo_total']:,} vs baseline "
          f"{r['costo_baseline']:,} (ahorro {r['ahorro_vs_baseline']:.1%}) · reporte en {salida.with_suffix('.md')}")


if __name__ == "__main__":
    main()
