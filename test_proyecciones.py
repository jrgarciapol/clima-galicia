"""Pruebas del paso 9 sin tocar la red.

Se fabrica un fichero con la MISMA estructura que AdapteCCa -- ejes member /
time_filter / period / lat / lon, etiquetas en bytes, y las tres variables
(absoluta, anomalia y anomalia relativa) -- y se comprueba que el recorte, el
resumen entre modelos y el analisis hacen lo que deben.

Lo que de verdad se vigila aqui es la seleccion de ejes. Un eje mal
seleccionado no da error: da numeros. Si 'JJA' se confundiera con 'Jan', el
informe saldria igual de bonito y diria lo contrario de la verdad.
"""
import importlib.util
import io
import contextlib
import os
import shutil

import numpy as np
import pandas as pd
import xarray as xr

KIT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(KIT, "_pruebas_proy")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP

spec = importlib.util.spec_from_file_location("p9", os.path.join(KIT, "09_proyecciones.py"))
p9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p9)

TF = ["Apr", "Aug", "Dec", "Feb", "Jan", "Jul", "Jun", "Mar", "May", "Nov",
      "Oct", "Sep", "DJF", "JJA", "MAM", "SON", "year"]
PER = ["far_future", "medium_future", "near_future", "reference"]
MEM = ["average"] + [f"MODELO{i}" for i in range(11)]

# Rejilla nacional, como la real: 0,05 grados
LAT = np.round(np.arange(33.475, 45.98, 0.05), 3)
LON = np.round(np.arange(-13.175, 6.78, 0.05), 3)

# Verdad que se impone y que el analisis tiene que recuperar
SALTO = {"reference": 0.0, "near_future": 1.0, "medium_future": 3.0,
         "far_future": 6.0}
rng = np.random.default_rng(9)


def fabrica(var, esc, ruta, brecha=0.0):
    """Fichero falso. 'brecha' hace que los sitios calidos se calienten mas."""
    nt, npd, nm = len(TF), len(PER), len(MEM)
    # clima base: gradiente oeste-este, o sea la costa mas fresca
    base = 20 + 8 * (LON[None, :] - LON.min()) / (LON.max() - LON.min()) \
        + 0 * LAT[:, None]
    base = base + 0 * np.zeros((LAT.size, LON.size))
    abso = np.zeros((nm, nt, npd, LAT.size, LON.size), dtype="float32")
    anom = np.zeros_like(abso)
    for im in range(nm):
        # el miembro 0 ('average') es el central; los modelos se dispersan
        desv = 0.0 if im == 0 else (im - 6) * 0.25
        for it, f in enumerate(TF):
            est = 6.0 if f in ("JJA", "Jul", "Aug") else 0.0
            for ip, pnom in enumerate(PER):
                # un pelin de ruido: sin el, con brecha=0 el delta seria
                # exactamente constante y la correlacion no existiria
                ruido = rng.normal(0, 0.02, base.shape) * (pnom != "reference")
                d = (SALTO[pnom] * (1 + brecha * (base - base.mean()) / 4.0)
                     + desv * (pnom != "reference") + ruido)
                abso[im, it, ip] = base + est + d
                anom[im, it, ip] = d
    # mar: al oeste del todo, ausente
    abso[..., :3] = np.nan
    anom[..., :3] = np.nan
    xr.Dataset(
        {var: (("member", "time_filter", "period", "lat", "lon"), abso,
               {"units": "degC"}),
         var + "_anom": (("member", "time_filter", "period", "lat", "lon"), anom,
                         {"units": "degC"}),
         var + "_relanom": (("member", "time_filter", "period", "lat", "lon"),
                            anom * 5, {"units": "%"})},
        coords={"lat": LAT, "lon": LON,
                "time_filter": np.array([t.encode() for t in TF]),
                "period": np.array([p.encode() for p in PER]),
                "member": np.array([m.encode() for m in MEM])},
    ).to_netcdf(ruta)


print("=== etiquetas de los ejes: lo que confirmo --describe ===")
assert p9.FILTROS == ("JJA", "year"), p9.FILTROS
assert list(p9.PERIODOS) == ["reference", "near_future", "medium_future",
                             "far_future"], list(p9.PERIODOS)
print(f"  filtros {p9.FILTROS}  periodos {list(p9.PERIODOS)}")

print("\n=== un eje que no cuadra tiene que ABORTAR, no seguir ===")
try:
    p9._indices(["Jan", "Feb"], ["JJA"], "time_filter")
    raise AssertionError("tenia que abortar")
except SystemExit as e:
    print(f"  {str(e).splitlines()[0][:70]}")
print("  ok: no se elige 'lo mas parecido', se para")

print("\n=== recorte a Galicia y resumen entre modelos ===")
nac = os.path.join(TMP, "nacional.nc")
fabrica("tasmaxp99", "ssp585", nac)
mb_nac = os.path.getsize(nac) / 1e6




# se parchea solo la apertura, para ejercitar TODO lo demas de baja_uno
_abrir = xr.open_dataset
xr.open_dataset = lambda u, **k: _abrir(nac, **{k2: v for k2, v in k.items()
                                                if k2 != "decode_timedelta"})
p9.url_dods = lambda up: "loquesea"
dest = os.path.join(TMP, "tasmaxp99_ssp585.csv")
# El mar es NaN en los 11 modelos. Reducirlo hace que numpy avise una vez por
# fichero, y con 28 ficheros son 28 avisos que asustan sin motivo.
import warnings as _w
with _w.catch_warnings(record=True) as capturados:
    _w.simplefilter("always")
    filas = p9.baja_uno("tasmaxp99", "ssp585", dest)
avisos = [c for c in capturados if "All-NaN" in str(c.message)]
print(f"  celdas de mar reducidas -> {len(avisos)} avisos de numpy")
assert not avisos, f"no deberia salir ninguno: {[str(c.message) for c in avisos[:2]]}"
xr.open_dataset = _abrir
t = pd.read_csv(dest)
print(f"  nacional {mb_nac:.0f} MB -> {os.path.getsize(dest) / 1e6:.2f} MB, {filas:,} filas")
print(f"  columnas: {list(t.columns)}")

celdas = t[["lat", "lon"]].drop_duplicates()
print(f"  {len(celdas)} celdas, lat {celdas.lat.min():.2f}-{celdas.lat.max():.2f}, "
      f"lon {celdas.lon.min():.2f}-{celdas.lon.max():.2f}")
assert celdas.lat.between(p9.SUR - 0.06, p9.NORTE + 0.06).all()
assert celdas.lon.between(p9.OESTE - 0.06, p9.ESTE + 0.06).all()
assert len(celdas) < LAT.size * LON.size / 20, "el recorte tiene que reducir de verdad"
assert set(t.filtro) == {"JJA", "year"}, set(t.filtro)
assert set(t.periodo) == set(PER), set(t.periodo)
assert set(t.tipo) == {"abs", "anom"}, "hacen falta las dos: absoluta y anomalia"

print("\n=== recupera el salto impuesto, y JJA no es Jan ===")
a = t[(t.tipo == "anom") & (t.filtro == "JJA")]
for p, esperado in SALTO.items():
    v = a[a.periodo == p].valor.median()
    print(f"  {p:15s} impuse {esperado:+.1f}  recupero {v:+.2f}")
    assert abs(v - esperado) < 0.05, f"{p}: {v} != {esperado}"

ab = t[(t.tipo == "abs") & (t.filtro == "JJA") & (t.periodo == "reference")]
an_ = t[(t.tipo == "abs") & (t.filtro == "year") & (t.periodo == "reference")]
j = ab.set_index(["lat", "lon"]).valor - an_.set_index(["lat", "lon"]).valor
print(f"  JJA menos 'year' en la referencia: {j.median():+.2f} (impuse +6,0)")
assert abs(j.median() - 6.0) < 0.05, \
    ("si esto falla es que se ha seleccionado el filtro equivocado: el informe "
     "saldria igual de bonito y diria otra cosa")

print("\n=== la horquilla entre modelos ===")
h = a[a.periodo == "far_future"]
print(f"  far_future: p10 {h.p10.median():+.2f}  media {h.valor.median():+.2f}  "
      f"p90 {h.p90.median():+.2f}")
assert h.p10.median() < h.valor.median() < h.p90.median(), \
    "la horquilla tiene que rodear al miembro 'average'"

print("\n=== analisis completo ===")
os.makedirs(p9.DIR, exist_ok=True)
shutil.copy(dest, os.path.join(p9.DIR, "tasmaxp99_ssp585.csv"))
# un segundo escenario, con brecha impuesta: los calidos se calientan mas
nac2 = os.path.join(TMP, "nacional2.nc")
fabrica("tasmaxp99", "ssp245", nac2, brecha=0.8)
xr.open_dataset = lambda u, **k: _abrir(nac2, **{k2: v for k2, v in k.items()
                                                 if k2 != "decode_timedelta"})
p9.baja_uno("tasmaxp99", "ssp245", os.path.join(p9.DIR, "tasmaxp99_ssp245.csv"))
xr.open_dataset = _abrir

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    p9.analizar()
texto = open(os.path.join(TMP, "resumen_proyecciones.txt"), encoding="utf-8").read()

for l in texto.splitlines():
    if any(k in l for k in ("error maximo", "ok: los dos", "OJO:", "rho ",
                            "aguanta", "C/decada")):
        print("  " + l.strip()[:110])

assert "ok: los dos caminos dan lo mismo" in texto, \
    "la anomalia tiene que ser exactamente futuro - referencia"

# con brecha impuesta en ssp245 la correlacion debe ser claramente positiva;
# sin brecha en ssp585 debe rondar cero. Si sale al reves, el calculo esta mal.
import re
lineas = [l for l in texto.splitlines() if l.strip().startswith(("ssp245:", "ssp585:"))]
rhos = {}
for l in lineas:
    m = re.match(r"\s*(ssp\d+): rho ([+-][\d.]+)", l)
    if m:
        rhos[m.group(1)] = float(m.group(2))
print(f"  brecha: {rhos}")
assert rhos.get("ssp245", 0) > 0.7, "impuse brecha en ssp245 y no la ve"
assert abs(rhos.get("ssp585", 1)) < 0.2, "en ssp585 no hay brecha y se la inventa"

print("\n=== la union con el ranking de 1 km no puede dejar la costa fuera ===")
# La primera version buscaba lat y lon por separado. En la costa ese par cae
# sobre celdas de mar, que no estan en la tabla, y 31 de 400 puntos se quedaban
# sin delta -- justo los mas bajos y frescos, o sea los candidatos buenos.
celdas = pd.read_csv(os.path.join(p9.DIR, "tasmaxp99_ssp245.csv"))
celdas = celdas[(celdas.tipo == "anom") & (celdas.filtro == "JJA")
                & (celdas.periodo == "medium_future")][["lat", "lon"]].drop_duplicates()
# puntos de "1 km" pegados a la costa: en el borde oeste, donde empieza el mar
borde = celdas.lon.min()
rank = pd.DataFrame({
    "lat": np.random.default_rng(3).choice(celdas.lat.unique(), 60),
    "lon": borde - 0.03,                       # al oeste de la primera celda
    "altitud": 20.0, "tx_p99_1km": 24.0})
rank.to_csv(os.path.join(TMP, "ranking_60_40.csv"), index=False)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    p9.analizar()
texto = open(os.path.join(TMP, "resumen_proyecciones.txt"), encoding="utf-8").read()
linea = [l for l in texto.splitlines() if "union con la rejilla" in l]
print("  " + (linea[0].strip() if linea else "SIN LINEA DE UNION"))
assert linea, "el informe tiene que decir como fue la union"
assert "0 puntos sin delta" in linea[0], \
    ("ningun punto costero puede quedarse sin delta: si se queda, el informe "
     "lo cuenta como 'sale del top 20' cuando lo que pasa es que falta el dato")
rc = pd.read_csv(os.path.join(TMP, "ranking_con_proyeccion.csv"))
assert rc.d_ssp245.notna().all(), "quedaron NaN en el delta"
print("  ok: 60 puntos al oeste de la primera celda, todos con delta")

assert "no publica ningun indice de confort con humedad" in texto, \
    "el limite tiene que ir en el informe, no solo en el README"
assert os.path.exists(os.path.join(TMP, "proyecciones_galicia.csv.gz"))

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 9 VALIDADO")
