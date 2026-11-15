"""Envía los ejemplos de data/ejemplos a la API y guarda las respuestas como evidencia.

Uso:  python scripts/probar_ejemplos.py [--url http://localhost:8000] [--salida evidencia/respuestas]
Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def enviar(url: str, cuerpo: bytes) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=cuerpo, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--ejemplos", default="data/ejemplos")
    ap.add_argument("--salida", default="evidencia/respuestas")
    a = ap.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)

    archivos = sorted(Path(a.ejemplos).glob("*.json")) + sorted(Path(a.ejemplos).glob("errores/*.json"))
    for f in archivos:
        es_obs = "observacion" in f.name or any(c in f.name for c in ("E08", "E09", "E10"))
        endpoint = "/v1/observaciones" if es_obs else "/v1/prediccion"
        cuerpo = f.read_bytes()
        estado, resp = enviar(a.url + endpoint, cuerpo)
        (salida / f.name).write_text(json.dumps(
            {"endpoint": endpoint, "solicitud": json.loads(cuerpo), "status": estado, "respuesta": resp},
            ensure_ascii=False, indent=2), encoding="utf-8")
        cal = resp.get("calidad", {})
        print(f"{f.stem:28} {estado}  {cal.get('estado', resp.get('detail', ''))}")
        for o in cal.get("observaciones", []):
            print(f"{'':34}{o['accion']:9} {o['campo']}: {o['detalle'][:90]}")


if __name__ == "__main__":
    main()
