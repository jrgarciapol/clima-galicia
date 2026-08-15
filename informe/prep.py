import base64, json, os
import numpy as np, pandas as pd

R = os.environ.get("GAL_DATOS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = {}

# ---------------------------------------------------------------- 1 km raster
a = pd.read_csv(f"{R}/alta_resolucion.csv.gz")
a = a[a.tierra == 1].copy()
PASO = 0.01
S, N = 41.66, 43.99
O, E = -9.56, -6.58
ny = int(round((N - S) / PASO)); nx = int(round((E - O) / PASO))
iy = ((a.lat - S) / PASO).astype(int).clip(0, ny - 1)
ix = ((a.lon - O) / PASO).astype(int).clip(0, nx - 1)

def rasteriza(valores):
    suma = np.zeros((ny, nx)); cuenta = np.zeros((ny, nx))
    np.add.at(suma, (iy, ix), valores)
    np.add.at(cuenta, (iy, ix), 1)
    with np.errstate(invalid="ignore"):
        m = np.where(cuenta > 0, suma / np.maximum(cuenta, 1), np.nan)
    # rellenar huecos de 1 celda con la media de los vecinos
    for _ in range(2):
        hueco = ~np.isfinite(m)
        if not hueco.any(): break
        p = np.pad(m, 1, constant_values=np.nan)
        vec = np.stack([p[0:-2,1:-1], p[2:,1:-1], p[1:-1,0:-2], p[1:-1,2:],
                        p[0:-2,0:-2], p[0:-2,2:], p[2:,0:-2], p[2:,2:]])
        import warnings
        with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            med = np.nanmean(vec, axis=0)
        n_vec = np.isfinite(vec).sum(0)
        m = np.where(hueco & (n_vec >= 4), med, m)
    return m

def cuantiza(m, lo, hi):
    q = np.clip((m - lo) / (hi - lo), 0, 1)
    b = np.where(np.isfinite(m), np.round(q * 254) + 1, 0).astype(np.uint8)
    return base64.b64encode(b.tobytes()).decode()

tx = rasteriza(a.tx_p99_1km.values)
hx = rasteriza(a.hx_p99_1km.values)
alt = rasteriza(a.altitud.values)
LO_TX, HI_TX = 18.0, 42.0
LO_HX, HI_HX = 22.0, 48.0
OUT["malla"] = {"s": S, "o": O, "paso": PASO, "ny": ny, "nx": nx,
                "tx": {"lo": LO_TX, "hi": HI_TX, "d": cuantiza(tx, LO_TX, HI_TX)},
                "hx": {"lo": LO_HX, "hi": HI_HX, "d": cuantiza(hx, LO_HX, HI_HX)},
                "alt": {"lo": 0.0, "hi": 1800.0, "d": cuantiza(alt, 0, 1800)}}
print(f"malla {ny}x{nx}, cobertura {np.isfinite(tx).mean():.1%}, "
      f"tx {np.nanmin(tx):.1f}-{np.nanmax(tx):.1f}")

# ------------------------------------------------------- deltas de proyeccion
d = pd.read_csv(f"{R}/proyecciones_galicia.csv.gz")
ESC = ["ssp126", "ssp245", "ssp370", "ssp585"]
PER = {"near_future": "2011-2040", "medium_future": "2041-2070",
       "far_future": "2071-2100"}
an = d[(d.variable == "tasmaxp99") & (d.tipo == "anom") & (d.filtro == "JJA")]
celdas = an[["lat", "lon"]].drop_duplicates().sort_values(["lat", "lon"])
OUT["delta"] = {"lat": [round(x, 3) for x in sorted(celdas.lat.unique())],
                "lon": [round(x, 3) for x in sorted(celdas.lon.unique())], "v": {}}
la_i = {v: i for i, v in enumerate(OUT["delta"]["lat"])}
lo_i = {v: i for i, v in enumerate(OUT["delta"]["lon"])}
for e in ESC:
    for p in PER:
        g = an[(an.escenario == e) & (an.periodo == p)]
        m = np.full((len(la_i), len(lo_i)), np.nan)
        m[[la_i[round(x,3)] for x in g.lat], [lo_i[round(x,3)] for x in g.lon]] = g.valor.values
        OUT["delta"]["v"][f"{e}|{p}"] = [None if not np.isfinite(x) else round(float(x),2)
                                         for x in m.ravel()]
print(f"delta {len(la_i)}x{len(lo_i)} x {len(OUT['delta']['v'])} capas")
json.dump(OUT, open("datos_mapa.json", "w"), separators=(",", ":"))
print("datos_mapa.json", os.path.getsize("datos_mapa.json")/1e6, "MB")
