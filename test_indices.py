"""Prueba del calculo de indices con series sinteticas realistas.

Genera dos climas contrastados (costa atlantica vs valle interior de Ourense),
comprueba que los indices los separan en la direccion correcta y que el codigo
no falla con huecos ni con series cortas.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import (heat_index, humedad_relativa, humidex, indices_punto,  # noqa: E402
                   percentil_calendario, presion_vapor, rachas,
                   rh_a_porcentaje, temp_aparente)

rng = np.random.default_rng(42)
fechas = pd.date_range("1996-01-01", "2025-12-31", freq="D")
doy = fechas.dayofyear.values
est = np.cos(2 * np.pi * (doy - 200) / 365.25)  # +1 en pleno verano
anio = fechas.year.values
calent = (anio - 1996) * 0.045  # ~0.45 C/decada


def clima(tmed, amp_est, amp_diaria, ruido, cola, td_off):
    """Serie diaria sintetica. `cola` amplifica los eventos calidos extremos."""
    base = tmed + amp_est * est + calent
    r = rng.normal(0, ruido, len(fechas))
    # persistencia: media movil de 3 dias para que existan rachas reales
    r = pd.Series(r).rolling(3, min_periods=1).mean().values * 1.4
    # Las olas de calor son persistentes: el termino extra se suaviza a 4 dias
    # para que existan rachas de verdad y no picos aislados de un solo dia.
    extra = cola * np.clip(rng.gumbel(0, 1.3, len(fechas)), 0, None)
    extra = pd.Series(extra).rolling(4, min_periods=1).mean().values * 1.6
    extra *= np.clip(est, 0, None)
    tmax = base + amp_diaria / 2 + r + extra
    tmin = base - amp_diaria / 2 + r * 0.6
    td = tmin - td_off + rng.normal(0, 1.0, len(fechas))
    return pd.DataFrame({"tmax": tmax, "tmin": tmin,
                         "tmean": (tmax + tmin) / 2, "td": np.minimum(td, tmax - 0.5)},
                        index=fechas)


costa = clima(tmed=14.0, amp_est=4.5, amp_diaria=6.0, ruido=1.6, cola=0.6, td_off=1.0)
valle = clima(tmed=14.5, amp_est=9.0, amp_diaria=12.0, ruido=2.4, cola=1.5, td_off=4.0)

print("=== funciones de humedad ===")
assert abs(humedad_relativa(20.0, 20.0) - 100) < 0.5, "HR con T=Td debe ser 100%"
assert humedad_relativa(30.0, 10.0) < 30, "aire seco"
assert humidex(30.0, 25.0) > 40, "30C con rocio 25C es humidex alto"
assert humidex(20.0, -10.0) == 20.0, "aire muy seco: el humidex no baja de la temperatura real"
assert heat_index(20.0, 80.0) == 20.0, "por debajo de 26.7C devuelve T"
assert heat_index(35.0, 70.0) > 40, "35C con 70% HR es peligroso"

# --- humedad relativa en fraccion vs en porcentaje -------------------------
# El WRF de MeteoGalicia declara rh con units="1" (0-1). Si eso se usa como si
# fuera un porcentaje, el humidex se queda igual que la temperatura seca y el
# bochorno desaparece sin dar ningun error: es el peor tipo de fallo.
frac = np.array([0.12, 0.55, 0.98])
pct = np.array([12.0, 55.0, 98.0])
assert np.allclose(rh_a_porcentaje(frac), pct), rh_a_porcentaje(frac)
assert np.allclose(rh_a_porcentaje(pct), pct), "un porcentaje no se debe tocar"
assert np.allclose(rh_a_porcentaje(pct, unidades="1"), pct), \
    "mandan los datos, no el atributo: aqui units miente"
assert np.allclose(rh_a_porcentaje(np.array([0.4]), unidades="%"), [40.0]), \
    "un valor pequenio aislado sigue siendo fraccion"
assert np.isnan(rh_a_porcentaje(np.array([np.nan])))[0]

# y el efecto sobre el humidex, que es lo que de verdad importa
t, rh_real = 34.0, 0.60
e_bien = rh_a_porcentaje(np.array([rh_real]))[0] / 100 * presion_vapor(t)
e_mal = np.clip(rh_real, 1, 100) / 100 * presion_vapor(t)
hx_bien = max(t + 0.5555 * (e_bien - 10.0), t)
hx_mal = max(t + 0.5555 * (e_mal - 10.0), t)
print(f"  34 C con 60% HR -> humidex {hx_bien:.1f}; sin convertir saldria {hx_mal:.1f}")
assert hx_bien > 44 and hx_mal == t, \
    "sin la conversion, un dia de bochorno se contabiliza como aire seco"

# temperatura aparente: a diferencia del humidex, SI puede bajar de la
# temperatura real, porque incorpora el efecto refrescante del viento
sin_viento = temp_aparente(30.0, 20.0, 0.0)
con_brisa = temp_aparente(30.0, 20.0, 6.0)
assert con_brisa < sin_viento - 3, f"6 m/s deben aliviar ({sin_viento:.1f} -> {con_brisa:.1f})"
assert temp_aparente(30.0, 25.0, 0.0) > temp_aparente(30.0, 10.0, 0.0), \
    "a igual viento, mas humedad debe dar mas sensacion de calor"
assert temp_aparente(30.0, 28.0, 0.0) > 30, "muy humedo y sin viento: peor que la seca"
assert temp_aparente(30.0, 5.0, 8.0) < 30, "seco y ventoso: mejor que la seca"
assert temp_aparente(30.0, 20.0, -5.0) == temp_aparente(30.0, 20.0, 0.0), \
    "un viento negativo no debe calentar"
print("  ok")

print("\n=== rachas ===")
m = np.array([0, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 0], dtype=bool)
assert rachas(m, 3) == (2, 8), rachas(m, 3)
assert rachas(m, 5) == (1, 5), rachas(m, 5)
assert rachas(np.zeros(10, bool), 3) == (0, 0)
assert rachas(np.ones(10, bool), 3) == (1, 10)
print("  ok")

print("\n=== percentil de calendario ===")
u = percentil_calendario(costa.index, costa.tmax.values, ventana=15, q=95)
assert u.notna().all(), "no debe quedar ningun dia sin umbral"
jul = u[u.index.month == 7].mean()
ene = u[u.index.month == 1].mean()
assert jul > ene + 4, f"el umbral de verano debe superar al de invierno ({jul:.1f} vs {ene:.1f})"
frac = (costa.tmax.values > u.values).mean()
assert 0.03 < frac < 0.08, f"el p95 movil debe superarse ~5% de los dias, no {frac:.3f}"
print(f"  umbral jul {jul:.1f}C / ene {ene:.1f}C, superado el {frac*100:.1f}% de los dias")

print("\n=== indices sobre los dos climas ===")
ic = indices_punto(costa)
iv = indices_punto(valle)
cols = ["d_tx30", "d_tx32", "d_tx35", "tx_p99", "tx_max", "noches_trop",
        "olas_n", "olas_dias", "hx_p99", "d_hx35", "amplitud", "d_helada", "rango_anual"]
print(f"{'indice':16s} {'costa':>9s} {'valle':>9s}")
for c in cols:
    print(f"{c:16s} {ic.get(c, float('nan')):9.2f} {iv.get(c, float('nan')):9.2f}")

assert iv["d_tx32"] > ic["d_tx32"], "el valle debe tener mas dias de calor"
assert iv["tx_p99"] > ic["tx_p99"]
assert iv["amplitud"] > ic["amplitud"]
assert iv["hx_p99"] > ic["hx_p99"]
assert iv["d_helada"] > ic["d_helada"]
# las olas de calor son relativas al clima local: ambos sitios deben tener
# un numero comparable de episodios, esa es justamente la idea del indice
assert 0.5 < ic["olas_n"] / iv["olas_n"] < 2.0, (ic["olas_n"], iv["olas_n"])
assert ic["n_anios"] == 30
print("  ok: el indice separa los dos climas en la direccion esperada")

print("\n=== robustez ===")
huecos = costa.copy()
idx = rng.choice(len(huecos), 3000, replace=False)
huecos.iloc[idx, :] = np.nan
h = indices_punto(huecos.dropna(subset=["tmax", "tmin"]))
assert h and abs(h["tx_p99"] - ic["tx_p99"]) < 1.0, "con 27% de huecos debe seguir siendo estable"
print(f"  con 27% de huecos: tx_p99 {h['tx_p99']:.2f} vs {ic['tx_p99']:.2f}  ok")

corta = costa.iloc[:200]
assert indices_punto(corta) == {}, "series de menos de un anio deben descartarse"
print("  serie corta descartada  ok")

sin_td = costa.drop(columns=["td"])
s = indices_punto(sin_td)
assert s and "hx_p99" not in s, "sin punto de rocio no debe inventar indices de humedad"
print("  sin punto de rocio: degrada limpiamente  ok")

print("\n=== tendencia detectada ===")
for nombre, serie, metrica in [
    ("costa", costa, lambda s: s.tmax[s.index.month.isin([6, 7, 8])].mean()),
    ("valle", valle, lambda s: s.tmax[s.index.month.isin([6, 7, 8])].mean()),
    ("valle d_tx32", valle, lambda s: float((s.tmax >= 32).sum())),
]:
    pa = serie.groupby(serie.index.year).apply(metrica, include_groups=False)
    pend = np.polyfit(pa.index, pa.values, 1)[0] * 10
    print(f"  {nombre:14s} {pend:+.2f} por decada")
    if nombre.startswith(("costa", "valle d")) or nombre == "valle":
        assert pend > 0, f"{nombre}: debe detectar la tendencia al alza inyectada"

pa = costa.groupby(costa.index.year).apply(
    lambda s: s.tmax[s.index.month.isin([6, 7, 8])].mean(), include_groups=False)
pend = np.polyfit(pa.index, pa.values, 1)[0] * 10
assert 0.3 < pend < 0.6, (
    f"la pendiente recuperada ({pend:+.2f}) debe parecerse al +0.45 C/decada inyectado")
print(f"  recuperado {pend:+.2f} C/decada frente a +0.45 inyectado  ok")

print("\nTODAS LAS COMPROBACIONES OK")
