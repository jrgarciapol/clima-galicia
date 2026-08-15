"""Prueba del paso 7 con series diarias sinteticas de tendencia conocida.

Se fabrican tres estaciones con calentamientos distintos (+0,6, +0,3 y 0,0
grados por decada) mas una cuarta con solo 6 anios, y se comprueba que:

  - la pendiente de Sen recupera la tendencia inyectada
  - un unico verano extremo no la descoloca (esa es la razon de usar Sen y no
    minimos cuadrados)
  - Mann-Kendall marca como significativa la tendencia fuerte y no la nula
  - las estaciones con serie corta quedan fuera
"""
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
TMP = os.path.join(KIT, "_pruebas_tmp3")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP
ENTORNO = dict(os.environ)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "paso07", os.path.join(KIT, "07_evolucion_estaciones.py"))
p7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p7)

print("=== pendiente de Sen frente a minimos cuadrados ===")
x = np.arange(2009, 2026)
y = 10 + 0.5 * (x - 2009)
y_out = y.copy()
# el atipico va cerca del extremo: en el centro exacto no movería
# la pendiente de OLS, solo la ordenada, y la prueba no probaria nada
y_out[15] += 25
s_lim, s_out = p7.sen(x, y), p7.sen(x, y_out)
o_lim, o_out = np.polyfit(x, y, 1)[0], np.polyfit(x, y_out, 1)[0]
print(f"  serie limpia   Sen {s_lim:.3f}   OLS {o_lim:.3f}")
print(f"  con un atipico Sen {s_out:.3f}   OLS {o_out:.3f}")
assert abs(s_lim - 0.5) < 1e-9
assert abs(s_out - 0.5) < 0.06, "Sen no deberia moverse por un solo anio"
assert abs(o_out - 0.5) > 0.15, "OLS si deberia moverse (por eso no lo usamos)"
print("  ok: Sen aguanta el atipico, OLS no")

print("\n=== Mann-Kendall ===")
rng = np.random.default_rng(11)
ruido = rng.normal(0, 1.2, len(x))
_, p_fuerte = p7.mann_kendall(x, 10 + 0.6 * (x - 2009) + ruido)
_, p_nula = p7.mann_kendall(x, 10 + ruido)
print(f"  tendencia fuerte p={p_fuerte:.4f}   tendencia nula p={p_nula:.4f}")
assert p_fuerte < 0.05 and p_nula > 0.05
print("  ok")

# --- serie diaria sintetica -------------------------------------------------
print("\n=== extremo a extremo ===")
CAL = {101: 0.60, 102: 0.30, 103: 0.00}       # C por decada inyectados
filas = []
for est, pend in CAL.items():
    f = pd.date_range("2009-01-01", "2025-12-31", freq="D")
    est_anual = np.cos(2 * np.pi * (f.dayofyear.values - 200) / 365.25)
    calent = pend * (f.year.values - 2009) / 10
    base = 14 + 8 * est_anual + calent
    r = pd.Series(rng.normal(0, 2.2, len(f))).rolling(3, min_periods=1).mean().values * 1.4
    extra = np.clip(pd.Series(rng.gumbel(0, 1.3, len(f))).rolling(4, min_periods=1)
                    .mean().values * 1.6, 0, None) * np.clip(est_anual, 0, None)
    tmax = base + 5 + r + extra
    tmin = base - 5 + r * 0.6
    filas.append(pd.DataFrame({"fecha": f, "tmax": tmax, "tmin": tmin,
                               "tmean": (tmax + tmin) / 2,
                               "hr": np.clip(85 - 1.5 * (tmax - 18), 30, 100),
                               "estacion": est}))
# una estacion con serie corta: debe quedar fuera de las tendencias
f = pd.date_range("2020-01-01", "2025-12-31", freq="D")
filas.append(pd.DataFrame({"fecha": f, "tmax": 20.0, "tmin": 10.0, "tmean": 15.0,
                           "hr": 80.0, "estacion": 999}))
pd.concat(filas).to_csv(os.path.join(TMP, "estaciones_diario.csv"), index=False)
pd.DataFrame({"id": list(CAL) + [999],
              "concello": ["A", "B", "C", "CORTA"],
              "provincia": ["Lugo"] * 4,
              "lat": [43.0] * 4, "lon": [-8.0] * 4, "alt": [100] * 4}
             ).to_csv(os.path.join(TMP, "estaciones_lista.csv"), index=False)

r = subprocess.run([sys.executable, "07_evolucion_estaciones.py"], cwd=KIT,
                   capture_output=True, text=True, env=ENTORNO)
print(r.stdout[-2500:])
if r.returncode != 0:
    print(r.stderr[-3000:])
    sys.exit("07 fallo")

ev = pd.read_csv(os.path.join(TMP, "evolucion_estaciones.csv"))
td = pd.read_csv(os.path.join(TMP, "tendencias_estaciones.csv"))
print(f"\nevolucion: {ev.shape}   tendencias: {td.shape}")
assert set(ev.estacion.unique()) == {101, 102, 103, 999}
assert set(td.estacion.unique()) == {101, 102, 103}, \
    "la estacion de 6 anios no debe tener tendencia estimada"
assert ev[ev.estacion == 101].shape[0] == 17

print("\n  tendencia recuperada de tmean (C/decada):")
for est, esperado in CAL.items():
    obt = td.loc[td.estacion == est, "tmean_sen_dec"].iloc[0]
    pv = td.loc[td.estacion == est, "tmean_p"].iloc[0]
    print(f"    estacion {est}: inyectado {esperado:+.2f}  recuperado {obt:+.2f}"
          f"  p={pv:.4f}")
    assert abs(obt - esperado) < 0.22, (est, esperado, obt)
assert td.loc[td.estacion == 101, "tmean_p"].iloc[0] < 0.05, \
    "un calentamiento de +0,6 C/decada en 17 anios debe salir significativo"
assert td.loc[td.estacion == 103, "tmean_p"].iloc[0] > 0.05, \
    "sin tendencia inyectada no debe salir significativa"
print("  ok")

assert (td.loc[td.estacion == 101, "d_tx30_sen_dec"].iloc[0]
        > td.loc[td.estacion == 103, "d_tx30_sen_dec"].iloc[0]), \
    "la estacion que mas se calienta debe ganar mas dias calidos"

for c in ("d_tx32_sen_dec", "d_tx32_p", "d_tx32_salto", "hx_p99_sen_dec"):
    assert c in td.columns, f"falta {c}"
assert os.path.exists(os.path.join(TMP, "resumen_evolucion.txt"))
txt = open(os.path.join(TMP, "resumen_evolucion.txt")).read()
assert "estabilidad del ranking" not in txt or "correlacion de rangos" in txt

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 7 VALIDADO")
