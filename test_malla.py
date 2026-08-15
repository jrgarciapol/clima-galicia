"""Prueba de extremo a extremo de 02_indices.py con NetCDF horarios sinteticos.

Fabrica ficheros con la misma estructura que devuelve el CDS para
`reanalysis-era5-land` (dims valid_time/latitude/longitude, Kelvin, viento en
componentes u/v, mar en NaN, un fichero por anio) y comprueba que el paso 2:

  - agrega bien de horario a diario, incluida la minima nocturna
  - calcula el humidex y la temperatura aparente hora a hora
  - produce un ranking coherente: el interior de Ourense el peor, la costa
    noroccidental la mejor
  - y que el viento alivia mas en la costa, que es el efecto que se buscaba al
    incorporarlo y que con datos diarios no se podia ver
"""
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import xarray as xr

KIT = os.path.dirname(os.path.abspath(__file__))
# Directorio aislado: las pruebas no deben tocar descargas/ reales, que son
# horas de cola en el CDS.
TMP = os.path.join(KIT, "_pruebas_tmp2")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
shutil.copy(os.path.join(KIT, "celdas_galicia.csv"), TMP)
os.environ["GAL_BASE"] = TMP
ENTORNO = dict(os.environ)
DESC = os.path.join(TMP, "descargas")
os.makedirs(DESC)

celdas = pd.read_csv(os.path.join(KIT, "celdas_galicia.csv"))
lats = np.round(np.sort(celdas.lat.unique()), 2)
lons = np.round(np.sort(celdas.lon.unique()), 2)

# 16 anios: suficiente para que se active tambien el calculo de tendencias.
ANIOS = list(range(2010, 2026))
rng = np.random.default_rng(7)

# "continentalidad" sintetica: crece hacia el interior. Reproduce a grandes
# rasgos el gradiente real de Galicia.
cont = np.full((len(lats), len(lons)), np.nan)
for _, r in celdas.iterrows():
    i = int(np.argmin(np.abs(lats - r.lat)))
    j = int(np.argmin(np.abs(lons - r.lon)))
    cont[i, j] = min(r.dist_costa_km, 120) / 120.0

print(f"malla {cont.shape}, {int(np.isfinite(cont).sum())} celdas de tierra")

c = cont[None, :, :]
mar = ~np.isfinite(np.broadcast_to(cont, cont.shape))

for anio in ANIOS:
    horas = pd.date_range(f"{anio}-01-01", f"{anio}-12-31 23:00", freq="h")
    doy = horas.dayofyear.values
    hod = horas.hour.values
    est = np.cos(2 * np.pi * (doy - 200) / 365.25)      # +1 en pleno verano
    ciclo = -np.cos(2 * np.pi * (hod - 3) / 24)         # minimo al amanecer
    sino = pd.Series(rng.normal(0, 1, len(horas))).rolling(72, min_periods=1).mean().values * 6
    ola = np.clip(pd.Series(rng.gumbel(0, 1.2, len(horas))
                            ).rolling(96, min_periods=1).mean().values * 1.6, 0, None)

    base = 13.5 + (4.0 + 6.0 * c) * est[:, None, None]
    amp = (6.0 + 9.0 * c) * (0.55 + 0.45 * np.clip(est, 0, None))[:, None, None]
    t = (base + amp / 2 * ciclo[:, None, None] + sino[:, None, None]
         + (0.5 + 2.2 * c) * (ola * np.clip(est, 0, None))[:, None, None])
    td = np.broadcast_to(base - 2.5 - 5.0 * c, t.shape).copy()
    # la costa se ventila mucho mas, y sobre todo en verano
    u = np.broadcast_to((5.5 - 3.5 * c), t.shape) * \
        (0.8 + 0.5 * np.clip(est, 0, None))[:, None, None]
    v = np.zeros_like(t)

    for a in (t, td, u, v):
        a[:, mar] = np.nan

    xr.Dataset(
        {"t2m": (("valid_time", "latitude", "longitude"), (t + 273.15).astype("float32")),
         "d2m": (("valid_time", "latitude", "longitude"), (td + 273.15).astype("float32")),
         "u10": (("valid_time", "latitude", "longitude"), u.astype("float32")),
         "v10": (("valid_time", "latitude", "longitude"), v.astype("float32"))},
        coords={"valid_time": horas, "latitude": lats, "longitude": lons},
    ).to_netcdf(os.path.join(DESC, f"era5land_{anio}.nc"))
    print(f"  {anio} escrito", end="\r", flush=True)

print(f"\n{len(ANIOS)} ficheros horarios en {DESC}\n")

r = subprocess.run([sys.executable, "02_indices.py"], cwd=KIT,
                   capture_output=True, text=True, env=ENTORNO)
print(r.stdout[-4500:])
if r.returncode != 0:
    print(r.stderr[-4000:])
    sys.exit("02_indices.py fallo")

res = pd.read_csv(os.path.join(TMP, "indices_galicia.csv"))
print(f"\nfilas: {len(res)}   columnas: {len(res.columns)}")

# --- coherencia del ranking --------------------------------------------------
assert len(res) > 300, f"deberian salir >300 celdas, salieron {len(res)}"
assert res.indice_calor.between(0, 100).all()
assert res.ranking.min() == 1
assert res.indice_calor.is_monotonic_increasing, "el fichero debe salir ordenado"

corr = res[["dist_costa_km", "indice_calor"]].corr().iloc[0, 1]
print(f"correlacion distancia-a-costa vs indice de calor: {corr:+.3f}")
assert corr > 0.7, "por construccion el interior debe salir mas caluroso"

mejor, peor = res.iloc[0], res.iloc[-1]
print(f"mejor: {mejor.lat},{mejor.lon} {mejor.provincia}, costa {mejor.dist_costa_km} km")
print(f"peor : {peor.lat},{peor.lon} {peor.provincia}, costa {peor.dist_costa_km} km")
assert mejor.dist_costa_km < 15, "el mejor emplazamiento deberia ser costero"
assert peor.dist_costa_km > 60, "el peor deberia ser de interior profundo"

# --- lo que solo existe por venir de datos horarios --------------------------
for c_ in ("d_tx32", "tx_p99", "noches_trop", "olas_dias", "hx_p99", "at_p99",
           "d_at30", "viento_medio", "viento_dias_calidos",
           "score_calor", "score_confort"):
    assert c_ in res.columns, f"falta la columna {c_} (camino horario)"
    assert res[c_].notna().all(), f"{c_} tiene huecos"

cv = res[["viento_medio", "dist_costa_km"]].corr().iloc[0, 1]
print(f"correlacion viento vs distancia a costa: {cv:+.3f}")
assert cv < -0.7, "por construccion la costa debe ser mas ventosa"

costa = res[res.dist_costa_km < 10]
interior = res[res.dist_costa_km > 60]
alivio_c = (costa.tx_p99 - costa.at_p99).mean()
alivio_i = (interior.tx_p99 - interior.at_p99).mean()
print(f"alivio por viento (tx_p99 - at_p99): costa {alivio_c:+.2f} C, "
      f"interior {alivio_i:+.2f} C")
assert alivio_c > alivio_i, "el viento debe aliviar mas en la costa que en el interior"

# --- la cache diaria ---------------------------------------------------------
cache = os.path.join(TMP, "diarios_galicia.nc")
assert os.path.exists(cache)
d = xr.open_dataset(cache)
print(f"cache: {list(d.data_vars)}, {d.sizes['time']} dias, "
      f"{os.path.getsize(cache) / 1e6:.0f} MB")
for v_ in ("tmax", "tmin", "tmin_noche", "td", "hx_max", "at_max", "viento"):
    assert v_ in d, f"falta {v_} en la cache diaria"

esperados = sum(366 if (a % 4 == 0 and (a % 100 or a % 400 == 0)) else 365 for a in ANIOS)
assert abs(d.sizes["time"] - esperados) <= 2, (d.sizes["time"], esperados)

tn, tx, tm = d.tmin_noche.values, d.tmax.values, d.tmin.values
assert np.nanmean(tn) < np.nanmean(tx), "la minima nocturna no puede superar la maxima"
assert np.nanmean(tn) - np.nanmean(tm) < 3, "la minima nocturna debe parecerse a la diaria"
assert (np.nanmax(d.hx_max.values) >= np.nanmax(tx) - 0.01), \
    "el humidex maximo no puede quedar por debajo de la temperatura maxima"

# --- tendencias --------------------------------------------------------------
tend = pd.read_csv(os.path.join(TMP, "tendencias_galicia.csv"))
print(f"tendencias: {len(tend)} filas, {len(tend.columns)} columnas")
assert len(tend) > 300
assert any(x.startswith("at_p99") for x in tend.columns), \
    "la tendencia debe incluir tambien la temperatura aparente"

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 2 VALIDADO DE EXTREMO A EXTREMO (camino horario)")
