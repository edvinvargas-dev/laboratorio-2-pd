"""Carga de los archivos estáticos publicados en el GES (catálogos, feriados, costos)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Tipos de fecha especial. El orden define la prioridad cuando un día tiene varias.
TIPOS_FECHA = {"normal": 0, "feriado": 1, "medio_dia": 2, "comercial": 3, "pago": 4}
TIPOS_TIENDA = {"express": 0, "supermercado": 1, "hipermercado": 2}


@dataclass
class Catalogos:
    tiendas: pd.DataFrame  # tienda_id, nombre, ciudad, departamento, tipo, fecha_apertura
    familias: pd.DataFrame  # familia_id, nombre
    feriados: pd.DataFrame  # fecha, nombre, tipo, ambito
    costos: pd.DataFrame  # familia_id, costo_faltante, costo_sobrante

    @property
    def lista_familias(self) -> list[str]:
        return sorted(self.familias.familia_id.tolist())

    @property
    def lista_tiendas(self) -> list[int]:
        return sorted(self.tiendas.tienda_id.astype(int).tolist())

    def codigo_familia(self) -> dict[str, int]:
        return {f: i for i, f in enumerate(self.lista_familias)}

    def fechas_especiales(self) -> pd.DataFrame:
        """Tabla (fecha, tienda_id, tipo_fecha) con el feriado que aplica a cada tienda.

        Un feriado `nacional` aplica a todas; uno local solo a las tiendas de esa ciudad.
        Si coinciden varios el mismo día, gana el de menor código (más prioritario).
        """
        fer = self.feriados.copy()
        fer["cod"] = fer.tipo.map(TIPOS_FECHA).fillna(0).astype(int)
        tiendas = self.tiendas[["tienda_id", "ciudad"]]
        nac = fer[fer.ambito == "nacional"].merge(tiendas[["tienda_id"]], how="cross")
        loc = fer[fer.ambito != "nacional"].merge(tiendas, left_on="ambito", right_on="ciudad")
        todo = pd.concat([nac, loc], ignore_index=True)[["fecha", "tienda_id", "cod"]]
        return todo.groupby(["fecha", "tienda_id"], as_index=False).cod.min().rename(columns={"cod": "tipo_fecha"})


def cargar_catalogos(directorio: str | Path) -> Catalogos:
    d = Path(directorio)
    return Catalogos(
        tiendas=pd.read_csv(d / "tiendas.csv", parse_dates=["fecha_apertura"]),
        familias=pd.read_csv(d / "familias.csv"),
        feriados=pd.read_csv(d / "feriados.csv", parse_dates=["fecha"]),
        costos=pd.read_csv(d / "costos.csv"),
    )


def cargar_historico(directorio: str | Path) -> pd.DataFrame:
    return pd.read_csv(Path(directorio) / "historico_ventas.csv", parse_dates=["fecha"])
