"""PASO 11 - Mapa interactivo de las 147 estaciones.

Escribe estaciones_galicia.html: un fichero autonomo, sin conexion, con las
estaciones sobre la silueta de Galicia, coloreables por cualquiera de los diez
indices, y la serie anual de la estacion que se elija con su pendiente de Sen.

La distancia al mar se mide al OCEANO -- la mancha de agua conectada con el
borde del dominio -- y no a cualquier masa de agua. Sin esa distincion, Castrelo
de Miño, que esta en un embalse a 59 km del Atlantico, cuenta como estacion
costera; y con ella entran tambien Leiro, A Arnoia, Chantada y Viana do Bolo,
que son de lo mas caluroso de Galicia.

Uso:  python 11_mapa_estaciones.py
"""
import base64, io, json
import numpy as np, pandas as pd
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree

import os, sys
D = (os.environ.get("GAL_BASE")
     or os.path.dirname(os.path.abspath(__file__))) + os.sep
est = pd.read_csv(D + "indices_estaciones.csv")
evo = pd.read_csv(D + "evolucion_estaciones.csv")
alta = pd.read_csv(D + "alta_resolucion.csv.gz")

# --- silueta de Galicia a partir de la mascara de tierra del WRF -------------
n = len(alta)
R = min(((np.nanmean(np.abs(np.diff(alta.lat.values.reshape(r, n // r), axis=1))), r)
         for r in range(100, 400) if n % r == 0))[1]
C = n // R
tie = alta.tierra.values.reshape(R, C).astype(bool)
lat = alta.lat.values.reshape(R, C); lon = alta.lon.values.reshape(R, C)

LAT0, LAT1, LON0, LON1, PASO = 41.78, 43.85, -9.42, -6.68, 0.0075
glat = np.arange(LAT1, LAT0, -PASO); glon = np.arange(LON0, LON1, PASO)
GX, GY = np.meshgrid(glon, glat)
arb = cKDTree(np.column_stack([lon.ravel(), lat.ravel()]))
dist, idx = arb.query(np.column_stack([GX.ravel(), GY.ravel()]))
silueta = (tie.ravel()[idx] & (dist < 0.012)).reshape(GX.shape)
img = np.zeros(silueta.shape + (4,), np.uint8)
img[silueta] = (215, 214, 206, 255)
buf = io.BytesIO(); Image.fromarray(img, "RGBA").save(buf, "PNG", optimize=True)
b64 = base64.b64encode(buf.getvalue()).decode()
print("silueta", len(b64) // 1024, "KB")

# --- distancia al oceano (no a cualquier agua: los embalses no son costa) ----
lab, _ = ndimage.label(~tie)
borde = set(np.unique(lab[:, 0])) | set(np.unique(lab[0, :])) | set(np.unique(lab[-1, :]))
borde.discard(0)
oc = np.isin(lab, list(borde))
arb_oc = cKDTree(np.column_stack([lon[oc], lat[oc]]))
d_oc, _ = arb_oc.query(est[["lon", "lat"]].values)
est["mar_km"] = (d_oc * 100).round(1)

# --- variables ofrecidas ----------------------------------------------------
VARS = [
    ("d_tx30",      "Días por encima de 30 °C",        "días/año",  1),
    ("d_tx32",      "Días por encima de 32 °C",        "días/año",  1),
    ("tx_p99",      "Tmax del percentil 99",           "°C",        1),
    ("tx_max",      "Máxima absoluta registrada",      "°C",        1),
    ("tx_verano",   "Máxima media de verano",          "°C",        1),
    ("hx_p99",      "Humidex del percentil 99",        "°C",        1),
    ("d_hx35",      "Días con humidex > 35",           "días/año",  1),
    ("noches_trop", "Noches tropicales (mín ≥ 20 °C)", "noches/año",1),
    ("tmean",       "Temperatura media anual",         "°C",        1),
    ("d_helada",    "Días de helada",                  "días/año", -1),
]
CLIMA = [v for v, _, _, _ in VARS]

est = est[est.n_anios >= 8].copy()
filas = []
for _, s in est.iterrows():
    e = {"n": s.concello.title(), "p": s.provincia, "lat": round(s.lat, 4),
         "lon": round(s.lon, 4), "alt": int(s.alt), "mar": float(s.mar_km),
         "an": int(s.n_anios), "id": s.id}
    for v in CLIMA:
        e[v] = None if pd.isna(s.get(v)) else round(float(s[v]), 1)
    sub = evo[evo.estacion == s.id].sort_values("anio")
    e["y"] = [int(a) for a in sub.anio]
    e["s"] = {v: [None if pd.isna(x) else round(float(x), 1) for x in sub[v]]
              for v in CLIMA if v in sub}
    filas.append(e)

datos = json.dumps({"b64": b64, "extent": [LON0, LON1, LAT0, LAT1],
                    "vars": [{"k": k, "t": t, "u": u, "sg": sg}
                             for k, t, u, sg in VARS],
                    "est": filas}, ensure_ascii=False)

aqui = os.path.dirname(os.path.abspath(__file__))
plantilla = os.path.join(aqui, "plantilla_est.html")
if not os.path.exists(plantilla):
    sys.exit("Falta plantilla_est.html, que viene en el mismo kit.")
html = open(plantilla, encoding="utf-8").read().replace("{{JSON}}", datos)
salida = os.path.join(D, "estaciones_galicia.html")
with open(salida, "w", encoding="utf-8") as fh:
    fh.write(html)
print(f"{len(filas)} estaciones, {sum(len(f['y']) for f in filas)} anios-estacion")
print(f"escrito {salida} ({len(html) // 1024} KB)")
