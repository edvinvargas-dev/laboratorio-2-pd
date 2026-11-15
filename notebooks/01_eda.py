# %% [markdown]
# # 01 — Exploración de datos de NovaMercado
# Objetivo: entender los datos antes de diseñar features, modelo y políticas de limpieza.
# Ejecutar desde la raíz del repo:  .venv\Scripts\python notebooks\01_eda.py
# (o celda por celda en VS Code).

# %%
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DATA = Path("data")
FIG = Path("notebooks/figuras")
FIG.mkdir(parents=True, exist_ok=True)
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)

ventas = pd.read_csv(DATA / "historico_ventas.csv", parse_dates=["fecha"])
tiendas = pd.read_csv(DATA / "tiendas.csv", parse_dates=["fecha_apertura"])
familias = pd.read_csv(DATA / "familias.csv")
feriados = pd.read_csv(DATA / "feriados.csv", parse_dates=["fecha"])
costos = pd.read_csv(DATA / "costos.csv")

df = ventas.merge(tiendas[["tienda_id", "ciudad", "tipo"]], on="tienda_id")

# %% [markdown]
# ## 1. Cobertura y calidad del histórico

# %%
print("== 1. COBERTURA ==")
print("Rango:", df.fecha.min().date(), "->", df.fecha.max().date(), "| filas:", len(df))
dias = pd.date_range(df.fecha.min(), df.fecha.max())
print("Días calendario:", len(dias))
cob = df.groupby("tienda_id").agg(
    desde=("fecha", "min"), hasta=("fecha", "max"),
    dias=("fecha", "nunique"), filas=("ventas", "size"),
)
cob["familias_por_dia"] = (cob.filas / cob.dias).round(2)
print(cob)
print("Nulos por columna:\n", df.isna().sum().to_string())
print("Ventas negativas:", (df.ventas < 0).sum(), "| ventas = 0:", (df.ventas == 0).sum())
print("Duplicados (fecha,tienda,familia):", df.duplicated(["fecha", "tienda_id", "familia_id"]).sum())
# Días faltantes por tienda dentro de su propio rango
for t, g in df.groupby("tienda_id"):
    rango = pd.date_range(g.fecha.min(), g.fecha.max())
    falt = rango.difference(g.fecha.unique())
    if len(falt):
        print(f"  tienda {t}: {len(falt)} días faltantes, ej. {[d.date() for d in falt[:5]]}")

# %% [markdown]
# ## 2. Escala por tipo de tienda y familia

# %%
print("\n== 2. ESCALA (venta media diaria) ==")
piv = df.pivot_table(index="familia_id", columns="tipo", values="ventas", aggfunc="mean").round(0)
print(piv)
print("\nVenta media diaria total por tienda:")
print(df.groupby(["tienda_id", "tipo"]).ventas.sum().div(df.groupby("tienda_id").fecha.nunique().values).round(0))

# %% [markdown]
# ## 3. Estacionalidad semanal

# %%
print("\n== 3. DÍA DE LA SEMANA (índice vs. media de la familia) ==")
df["dow"] = df.fecha.dt.day_of_week  # 0 = lunes
idx = df.groupby(["familia_id", "dow"]).ventas.mean().unstack()
idx = idx.div(idx.mean(axis=1), axis=0).round(2)
idx.columns = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
print(idx)

# %% [markdown]
# ## 4. Tendencia y cambios en el tiempo

# %%
print("\n== 4. TENDENCIA (ventas totales por mes, tiendas 1-9) ==")
mens = df[df.tienda_id != 10].set_index("fecha").ventas.resample("MS").sum()
dias_mes = df[df.tienda_id != 10].set_index("fecha").ventas.resample("MS").size() / (9 * 12)
print((mens / dias_mes).round(0).to_string())

fig, ax = plt.subplots(figsize=(12, 4))
diario = df.groupby(["fecha", "tipo"]).ventas.sum().unstack()
diario.rolling(7).mean().plot(ax=ax)
ax.set_title("Ventas diarias por tipo de tienda (media móvil 7 días)")
fig.tight_layout(); fig.savefig(FIG / "tendencia_por_tipo.png", dpi=110); plt.close(fig)

# %% [markdown]
# ## 5. Efecto de feriados y fechas especiales
# Comparamos la venta de cada (tienda, familia) en el día especial contra la mediana
# de ese mismo día de la semana en las 4 semanas previas.

# %%
print("\n== 5. FERIADOS / FECHAS ESPECIALES ==")
base = df.sort_values("fecha").copy()
base["ref"] = (
    base.groupby(["tienda_id", "familia_id", "dow"]).ventas
    .transform(lambda s: s.shift(1).rolling(4, min_periods=2).median())
)
fer = feriados.copy()
nac = fer[fer.ambito == "nacional"].merge(tiendas[["tienda_id"]], how="cross")
loc = fer[fer.ambito != "nacional"].merge(tiendas[["tienda_id", "ciudad"]], left_on="ambito", right_on="ciudad")
fer_t = pd.concat([nac, loc])[["fecha", "tienda_id", "nombre", "tipo"]].rename(columns={"tipo": "tipo_fecha"})
m = base.merge(fer_t, on=["fecha", "tienda_id"])
m = m[m.ref > 0]
m["ratio"] = m.ventas / m.ref
print("Ratio medio por tipo de fecha:")
print(m.groupby("tipo_fecha").ratio.median().round(2).to_string())
print("\nRatio por fecha (mediana entre tiendas y familias):")
print(m.groupby(["nombre"]).ratio.median().sort_values().round(2).to_string())
print("\nFamilias más sensibles en feriado:")
print(m[m.tipo_fecha == "feriado"].groupby("familia_id").ratio.median().sort_values().round(2).to_string())
# ¿El feriado local mueve solo a su ciudad?
loc_names = fer[fer.ambito != "nacional"].nombre.unique()
for n in loc_names:
    fechas = fer[fer.nombre == n].fecha
    ciudad = fer[fer.nombre == n].ambito.iloc[0]
    sub = base[base.fecha.isin(fechas) & (base.ref > 0)].copy()
    sub["es_local"] = sub.ciudad == ciudad
    r = (sub.ventas / sub.ref).groupby(sub.es_local).median().round(2)
    print(f"  {n} ({ciudad}): ciudad={r.get(True)}  resto={r.get(False)}")

# %% [markdown]
# ## 6. Día del mes (quincena / fin de mes)

# %%
print("\n== 6. DÍA DEL MES (índice vs. media) ==")
df["dia_mes"] = df.fecha.dt.day
dm = df.groupby("dia_mes").ventas.mean()
print((dm / dm.mean()).round(2).to_string())

# %% [markdown]
# ## 7. Promociones

# %%
print("\n== 7. PROMOCIONES ==")
print("Distribución de en_promocion:\n", df.en_promocion.describe().round(2).to_string())
print("% filas con promo > 0 por familia:")
print((df.groupby("familia_id").en_promocion.apply(lambda s: (s > 0).mean()) * 100).round(1).to_string())
base["ratio_ref"] = base.ventas / base.ref
base["promo_bin"] = pd.cut(base.en_promocion, [-1, 0, 2, 5, 10, 1000], labels=["0", "1-2", "3-5", "6-10", ">10"])
print("\nVentas / referencia semanal según nivel de promoción:")
print(base[base.ref > 0].groupby("promo_bin", observed=True).ratio_ref.median().round(2).to_string())

# %% [markdown]
# ## 8. Tienda 10 (apertura 2025-03-15)

# %%
print("\n== 8. TIENDA 10 vs. otras express ==")
exp = df[df.tipo == "express"].set_index("fecha").groupby("tienda_id").ventas.resample("MS").sum().unstack(0)
print(exp.tail(14).to_string())

# %% [markdown]
# ## 9. Variabilidad: ¿qué tan ruidosas son las familias?
# Coeficiente de variación del error de un pronóstico ingenuo (mediana 4 semanas mismo día).
# Esto anticipa cuánto "colchón" necesita la cantidad sugerida.

# %%
print("\n== 9. RUIDO Y CUANTIL CRÍTICO ==")
b = base[base.ref > 0].copy()
b["err_rel"] = (b.ventas - b.ref) / b.ref
c = costos.copy()
c["cuantil_critico"] = (c.costo_faltante / (c.costo_faltante + c.costo_sobrante)).round(3)
ruido = b.groupby("familia_id").err_rel.agg(["std"]).round(3).rename(columns={"std": "std_err_rel"})
print(c.set_index("familia_id").join(ruido).sort_values("cuantil_critico").to_string())

# %% [markdown]
# ## 10. Primera intuición: ¿cuánto vale elegir bien la cantidad sugerida?
# Pronóstico ingenuo (mediana 4 semanas, mismo día) evaluado en los últimos 60 días.
# Comparamos sugerir exactamente el pronóstico vs. ajustarlo al cuantil crítico
# usando los errores relativos observados ANTES del periodo de validación.

# %%
print("\n== 10. COSTO: pronóstico puro vs. ajuste por cuantil ==")
corte = df.fecha.max() - pd.Timedelta(days=59)
tr, va = b[b.fecha < corte], b[b.fecha >= corte].merge(costos, on="familia_id")
q = c.set_index("familia_id").cuantil_critico
factor = tr.groupby("familia_id").apply(lambda g: 1 + g.err_rel.quantile(q[g.name]), include_groups=False)
va["sug_puro"] = va.ref.round()
va["sug_q"] = (va.ref * va.familia_id.map(factor)).round().clip(lower=0)


def costo(real, sug, cf, cs):
    return cf * np.maximum(real - sug, 0) + cs * np.maximum(sug - real, 0)


va["c_puro"] = costo(va.ventas, va.sug_puro, va.costo_faltante, va.costo_sobrante)
va["c_q"] = costo(va.ventas, va.sug_q, va.costo_faltante, va.costo_sobrante)
res = va.groupby("familia_id")[["c_puro", "c_q"]].sum().round(0)
res["factor"] = factor.round(3)
res.loc["TOTAL"] = res.sum(numeric_only=True)
res.loc["TOTAL", "factor"] = np.nan
print(res.to_string())
print(f"\nMAE ingenuo en validación: {(va.ventas - va.ref).abs().mean():.1f} unidades")
print(f"Ahorro por cuantil: {(1 - res.loc['TOTAL', 'c_q'] / res.loc['TOTAL', 'c_puro']) * 100:.1f}%")

# %%
fig, axes = plt.subplots(3, 4, figsize=(14, 8), sharex=True)
for ax, (fam, g) in zip(axes.flat, df[df.tienda_id == 1].groupby("familia_id")):
    g.set_index("fecha").ventas.plot(ax=ax, lw=0.6)
    ax.set_title(fam, fontsize=9)
fig.suptitle("Tienda 1 — ventas diarias por familia")
fig.tight_layout(); fig.savefig(FIG / "tienda1_familias.png", dpi=110); plt.close(fig)
print("\nFiguras en", FIG)
