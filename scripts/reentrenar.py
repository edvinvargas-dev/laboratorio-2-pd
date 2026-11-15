"""Dispara un reentrenamiento por la API y espera su resultado.

Uso:  python scripts/reentrenar.py [--url http://localhost:8000]
Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def pedir(metodo: str, url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--max-seg", type=int, default=660)
    a = ap.parse_args()

    t0 = time.time()
    s, r = pedir("POST", f"{a.url}/admin/reentrenar")
    print(f"POST /admin/reentrenar → {s} {r}")
    if s != 202:
        return
    i = r["id"]
    while time.time() - t0 < a.max_seg:
        s, e = pedir("GET", f"{a.url}/admin/reentrenar/{i}")
        if e.get("estado") != "en_curso":
            print(f"[{time.time() - t0:5.0f} s] {s} {json.dumps(e, ensure_ascii=False)}")
            break
        time.sleep(5)
    else:
        print("no terminó a tiempo")
    _, m = pedir("GET", f"{a.url}/modelo")
    print(f"GET /modelo → {m}")


if __name__ == "__main__":
    main()
