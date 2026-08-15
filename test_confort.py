"""Pruebas del paso 15, sin tocar la red y con una respuesta conocida.

Se fabrica una serie diaria de estaciones con clima impuesto y se comprueba
lo unico que de verdad importa aqui: que las dos hipotesis de humedad hagan
lo que dicen hacer. Con el punto de rocio fijo el humidex tiene que subir
EXACTAMENTE lo que sube la temperatura; con la humedad relativa fija tiene
que subir mas. Si eso se invirtiera, todo el paso diria lo contrario.
"""
import importlib.util
import os
import shutil

import numpy as np
import pandas as pd

KIT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(KIT, "_pruebas_confort")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP

spec = importlib.util.spec_from_file_location("p15", os.path.join(KIT, "15_confort.py"))
p15 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p15)

# --- estaciones falsas: una costera humeda y una interior seca -------------
EST = [dict(id=1, concello="COSTA", provincia="A Coruña", lat=43.2, lon=-9.0, alt=10,
            t0=20.0, amp=6.0, hr=85.0),
       dict(id=2, concello="INTERIOR", provincia="Ourense", lat=42.3, lon=-7.8, alt=140,
            t0=24.0, amp=11.0, hr=62.0)]
FECHAS = pd.date_range("2011-01-01", "2025-12-31", freq="D")
rng = np.random.default_rng(15)

filas = []
for e in EST:
    est_anual = e["amp"] * np.sin(2 * np.pi * (FECHAS.dayofyear - 110) / 365.25)
    tmax = e["t0"] + est_anual + rng.normal(0, 2.5, len(FECHAS))
    filas.append(pd.DataFrame({"fecha": FECHAS, "estacion": e["id"],
                               "tmax": tmax, "tmin": tmax - 8.0,
                               "tmean": tmax - 4.0,
                               "hr": np.clip(e["hr"] + rng.normal(0, 4, len(FECHAS)), 30, 99)}))
pd.concat(filas).to_csv(os.path.join(TMP, "estaciones_diario.csv"), index=False)
pd.DataFrame([{k: e[k] for k in ("id", "concello", "provincia", "lat", "lon", "alt")}
              for e in EST]).to_csv(os.path.join(TMP, "estaciones_lista.csv"), index=False)

# --- proyecciones falsas: anomalia impuesta -------------------------------
DELTA = 3.0
pr = []
for la in np.arange(41.8, 43.8, 0.05):
    for lo in np.arange(-9.3, -6.9, 0.05):
        for var in ("tasmaxp99", "tmean"):
            for esc in p15.ESCENARIOS:
                for per in p15.PERIODOS:
                    pr.append(dict(variable=var, escenario=esc, lat=round(la, 3),
                                   lon=round(lo, 3), filtro="JJA", periodo=per,
                                   tipo="anom", valor=DELTA, p10=DELTA-1, p90=DELTA+1))
pd.DataFrame(pr).to_csv(os.path.join(TMP, "proyecciones_galicia.csv.gz"),
                        index=False, compression="gzip")

print("=== inversion del punto de rocio ===")
t, hr = 30.0, 70.0
td = p15.rocio_desde_hr(t, hr)
from comun import humedad_relativa
print(f"  T {t} C con HR {hr} % -> rocio {td:.2f} C -> HR recuperada "
      f"{float(humedad_relativa(t, td)):.1f} %")
assert abs(float(humedad_relativa(t, td)) - hr) < 0.5

print("\n=== las dos hipotesis, sobre un caso a mano ===")
from comun import humidex
hx0 = float(humidex(t, td))
hx_a = float(humidex(t + DELTA, td))                       # rocio fijo
hx_b = float(humidex(t + DELTA, p15.rocio_desde_hr(t + DELTA, hr)))   # HR fija
print(f"  humidex hoy {hx0:.2f} | +{DELTA} C con rocio fijo {hx_a:.2f} "
      f"(sube {hx_a-hx0:+.2f}) | con HR fija {hx_b:.2f} (sube {hx_b-hx0:+.2f})")
assert abs((hx_a - hx0) - DELTA) < 0.01, \
    "con el rocio fijo el humidex tiene que subir EXACTAMENTE lo que la temperatura"
assert hx_b - hx0 > (hx_a - hx0) * 1.3, \
    "con la humedad relativa fija tiene que subir bastante mas: si no, la cota superior no lo es"

print("\n=== el paso completo ===")
import sys
sys.argv = ["15_confort.py"]
p15.main()
t = pd.read_csv(os.path.join(TMP, "confort_estaciones.csv"))
print(f"  {len(t)} filas, {t.id.nunique()} estaciones, "
      f"hipotesis: {sorted(t.hipotesis.unique())}")
assert set(t.hipotesis) == {"medido", "rocio_fijo", "hr_fija"}

hoy = t[t.periodo == "hoy"].set_index("id")
fut = t[(t.periodo == "medium_future") & (t.escenario == "ssp245")]
a_ = fut[fut.hipotesis == "rocio_fijo"].set_index("id")
b_ = fut[fut.hipotesis == "hr_fija"].set_index("id")

print("\n  estacion   hx hoy   rocio fijo   HR fija")
for i in hoy.index:
    print(f"  {hoy.loc[i,'concello']:10s} {hoy.loc[i,'hx_p99']:7.1f} "
          f"{a_.loc[i,'hx_p99']:11.1f} {b_.loc[i,'hx_p99']:9.1f}")
    sube_a = a_.loc[i, "hx_p99"] - hoy.loc[i, "hx_p99"]
    assert abs(sube_a - DELTA) < 0.25, \
        f"rocio fijo deberia subir {DELTA} y sube {sube_a:.2f} en {hoy.loc[i,'concello']}"
    assert b_.loc[i, "hx_p99"] > a_.loc[i, "hx_p99"], "la cota superior tiene que estar arriba"

print("\n=== la temperatura sube lo mismo en las dos hipotesis ===")
for i in hoy.index:
    assert abs(a_.loc[i, "tx_p99"] - b_.loc[i, "tx_p99"]) < 0.01, \
        "la humedad no puede cambiar la temperatura: solo el humidex"
print("  ok: la hipotesis solo mueve el humidex, no el termometro")

print("\n=== grados-dia de refrigeracion ===")
print(f"  costa {hoy.loc[1,'cdd']:.0f}  interior {hoy.loc[2,'cdd']:.0f}  "
      f"(interior +{hoy.loc[2,'cdd']-hoy.loc[1,'cdd']:.0f})")
assert hoy.loc[2, "cdd"] > hoy.loc[1, "cdd"], "el interior, mas calido, tiene que acumular mas"
assert (a_.cdd > hoy.cdd).all(), "con +3 C tienen que subir"

print("\n=== la ola de calor es RELATIVA al clima de cada sitio ===")
print(f"  dias de ola al anio: costa {hoy.loc[1,'ola_dias']:.1f}  "
      f"interior {hoy.loc[2,'ola_dias']:.1f}")
assert abs(hoy.loc[1, "ola_dias"] - hoy.loc[2, "ola_dias"]) < 4, \
    ("el umbral es el percentil 95 de cada sitio, asi que dos sitios con la misma "
     "variabilidad tienen que dar parecido aunque uno sea 4 C mas calido")

texto = open(os.path.join(TMP, "resumen_confort.txt"), encoding="utf-8").read()
assert "cota inferior" in texto and "cota superior" in texto
assert "NO es incertidumbre de los modelos" in texto
print("\n  el informe deja dicho que la horquilla es desconocimiento, no ruido")

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 15 VALIDADO")
