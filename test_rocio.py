"""Pruebas del paso 13 sin tocar la red.

Se fabrica un tar.gz con la misma estructura que publica AEMET -- rejilla en
polo rotado, coordenadas lat/lon en 2D, ausencias como -9999 y, sobre todo, el
MISMO nombre de fichero para tmax y para tmin -- y se comprueba que el recorte
a Galicia y el analisis de tendencia hacen lo que deben.
"""
import os
import shutil
import tarfile
import importlib.util

import numpy as np
import pandas as pd
import xarray as xr

KIT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(KIT, "_pruebas_rocio")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP

spec = importlib.util.spec_from_file_location("p13", os.path.join(KIT, "13_rocio.py"))
p13 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p13)

print("=== construccion de las URL ===")
u = p13.url_de("tmax", 2010, 2019)
print(f"  {u}")
assert u.endswith("/tmax/Serie_AEMET_v1_tmax_2010a2019_netcdf.tar.gz"), u
assert p13.url_de("tmin", 2021, 2021).endswith(
    "/tmin/Serie_AEMET_v1_tmin_2021_netcdf.tar.gz"), p13.url_de("tmin", 2021, 2021)
print("  ok: decadas como 2010a2019 y anios sueltos como 2021")

# ---------------------------------------------------------------------------
# Rejilla nacional falsa, con la estructura del README
# ---------------------------------------------------------------------------
NY, NX = 60, 70                      # a escala; la real es 240x280
lats = np.linspace(35.0, 44.0, NY)
lons = np.linspace(-9.8, 4.0, NX)
LON, LAT = np.meshgrid(lons, lats)
TEND = 0.30                          # C por decada, impuesta

rng = np.random.default_rng(11)


def anio_falso(anio, var, ruta):
    fechas = pd.date_range(f"{anio}-01-01", f"{anio}-12-31", freq="D")
    t = (anio - 1951) / 10
    est = 10 * np.sin(2 * np.pi * (fechas.dayofyear.values - 110) / 365.25)
    # gradiente norte-sur y variabilidad decenal, como en la realidad
    campo = (18 - 0.35 * (LAT - 35) + TEND * t
             + 1.4 * np.sin(2 * np.pi * (anio - 1951) / 21))
    dat = (campo[None] + est[:, None, None]
           + rng.normal(0, 2.5, (len(fechas), NY, NX))).astype("float32")
    if var == "tmin":
        dat -= 8.0
    dat[:, LAT < 36.5] = -9999.0      # mar / fuera de mascara
    nombre = p13.VARIABLES[var][0]
    xr.Dataset(
        {nombre: (("time", "rlat", "rlon"), dat,
                  {"units": "C", "missing_value": -9999.0})},
        coords={"time": fechas,
                "lat": (("rlat", "rlon"), LAT.astype("float32")),
                "lon": (("rlat", "rlon"), LON.astype("float32"))},
    ).to_netcdf(ruta)


print("\n=== recorte a Galicia y deteccion de la variable ===")
os.makedirs(p13.DIR, exist_ok=True)
crudo = os.path.join(TMP, "crudo")
os.makedirs(crudo, exist_ok=True)
# OJO: el nombre es el mismo para tmax y para tmin. Es la trampa del conjunto.
n_nac = os.path.join(crudo, "sfcan20100101a20101231_rot_mask.nc")
anio_falso(2010, "tmax", n_nac)
dest = os.path.join(p13.DIR, "tmax_2010.nc")
dias = p13.recorta(n_nac, "tmax", dest)
rec = xr.open_dataset(dest)
print(f"  nacional {NY}x{NX} -> Galicia {rec.lat.shape}, {dias} dias")
s, o, n, e = p13.BBOX
assert rec.lat.values.min() >= s - 0.2 and rec.lat.values.max() <= n + 0.2
assert rec.lon.values.min() >= o - 0.2 and rec.lon.values.max() <= e + 0.2
assert rec.lat.size < LAT.size / 8, "el recorte tiene que reducir de verdad"
assert not (rec.tmax.values < -900).any(), "-9999 debe quedar como ausencia"
assert np.isfinite(rec.tmax.values).mean() > 0.5, "y no debe borrarlo todo"
mb_nac = os.path.getsize(n_nac) / 1e6
mb_rec = os.path.getsize(dest) / 1e6
print(f"  {mb_nac:.1f} MB -> {mb_rec:.2f} MB ({mb_rec / mb_nac:.1%})")
rec.close()

# el fallo que se cazaria: extraer tmin encima de tmax
n2 = os.path.join(crudo, "sfcan20110101a20111231_rot_mask.nc")
anio_falso(2011, "tmin", n2)
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    p13.recorta(n2, "tmax", os.path.join(p13.DIR, "_prueba.nc"))
aviso = buf.getvalue()
print(f"  al pasarle un fichero de tmin como tmax: {aviso.strip()[:80]}")
assert "AVISO" in aviso, \
    ("los ficheros de tmax y tmin se llaman IGUAL; si no se comprueba la "
     "variable de dentro, se acaba con minimas etiquetadas como maximas")
os.remove(os.path.join(p13.DIR, "_prueba.nc"))
print("  ok")

print("\n=== ni un aviso al leer muchos ficheros seguidos ===")
# El aviso de numpy por reducir una celda toda NaN deberia salir UNA vez. Pero
# abrir un fichero con xarray reinicia el registro de avisos de Python, asi que
# se reimprime una vez por fichero: con 72 son 144 lineas de golpe, y parece un
# bucle infinito. Aqui se comprueba que no sale ninguno.
import warnings as _w
shutil.rmtree(p13.DIR, ignore_errors=True)
os.makedirs(p13.DIR)
for anio in range(2000, 2006):
    tmp = os.path.join(crudo, "y.nc")
    anio_falso(anio, "tmax", tmp)
    p13.recorta(tmp, "tmax", os.path.join(p13.DIR, f"tmax_{anio}.nc"))
    os.remove(tmp)
with _w.catch_warnings(record=True) as capturados:
    _w.simplefilter("always")
    try:
        p13.analizar(ventana=3)
    except SystemExit:
        pass
runtime = [c for c in capturados if issubclass(c.category, RuntimeWarning)]
print(f"  6 ficheros con celdas de mar -> {len(runtime)} avisos de numpy")
assert not runtime, \
    f"no deberia emitirse ninguno; salieron {[str(c.message)[:40] for c in runtime[:3]]}"
print("  ok: no se silencian, es que no se producen")

print("\n=== analisis: tendencia larga frente a ventanas de 15 anios ===")
shutil.rmtree(p13.DIR)
os.makedirs(p13.DIR)
for anio in range(1951, 2023):
    tmp = os.path.join(crudo, "x.nc")
    anio_falso(anio, "tmax", tmp)
    p13.recorta(tmp, "tmax", os.path.join(p13.DIR, f"tmax_{anio}.nc"))
    os.remove(tmp)
print(f"  {len(os.listdir(p13.DIR))} anios preparados")

p13.analizar(ventana=15)
texto = open(os.path.join(TMP, "resumen_rocio.txt"), encoding="utf-8").read()
print()
for l in texto.splitlines():
    if "tx_verano" in l or "tendencia sobre" in l or "ventanas de 15" in l:
        print("  " + l.strip())

import re
m = re.search(r"tendencia 1951-2022: mediana ([+-][\d.]+)", texto)
assert m, texto[:400]
larga = float(m.group(1))
print(f"\n  recuperada {larga:+.3f} C/decada frente a {TEND:+.2f} impuesta")
assert abs(larga - TEND) < 0.12, f"deberia recuperar la tendencia, dio {larga}"

m2 = re.search(r"ventanas de 15 anios: mediana [+-][\d.]+, de ([+-][\d.]+) a ([+-][\d.]+)",
               texto)
lo, hi = float(m2.group(1)), float(m2.group(2))
print(f"  ventanas de 15 anios: de {lo:+.2f} a {hi:+.2f}")
assert hi - lo > abs(TEND), \
    ("las ventanas cortas tienen que dispersarse mucho mas que la larga: es "
     "todo el argumento de este paso")
assert hi > TEND * 2, "alguna ventana corta debe exagerar; si no, no hay nada que avisar"
assert "ventanas recientes" in texto
assert "se abre la brecha" in texto
tab = pd.read_csv(os.path.join(TMP, "rocio_tendencias.csv"))
print(f"  rocio_tendencias.csv: {len(tab)} celdas, "
      f"columnas {list(tab.columns)}")
assert {"lat", "lon", "tx_verano_clim", "tx_verano_tend"} <= set(tab.columns)
assert tab.tx_verano_tend.between(-2, 2).all()
# en los datos sinteticos la tendencia es la misma en todas partes, asi que la
# brecha no debe abrirse: si saliera que si, seria un artefacto del calculo
import re as _re
d = _re.search(r"diferencia: ([+-][\d.]+) C/decada", texto)
assert d and abs(float(d.group(1))) < 0.08, \
    ("con una tendencia uniforme impuesta, la brecha no puede abrirse: "
     f"salio {d.group(1) if d else '?'}")
print(f"  brecha con tendencia uniforme: {d.group(1)} C/decada (debe ser ~0)")

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 13 VALIDADO")
