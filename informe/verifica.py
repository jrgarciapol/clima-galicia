import os
"""Comprueba que cada cifra del informe sale de los datos, no de la memoria."""
import json, re, numpy as np, pandas as pd
R = os.environ.get("GAL_DATOS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open("datos_informe.json"))
html = open("informe_galicia.html", encoding="utf-8").read()
fallos, ok = [], 0

def comprueba(etiqueta, esperado, real, tol):
    global ok
    if abs(esperado - real) <= tol: ok += 1; print(f"  ok   {etiqueta}: {esperado} vs {real:.3f}")
    else: fallos.append(f"{etiqueta}: el informe dice {esperado}, los datos dan {real:.3f}")

def rho(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(pd.Series(a[m]).rank(), pd.Series(b[m]).rank())[0, 1])

print("=== correlaciones citadas en el pie de la seccion 'brecha' ===")
ro = np.array(d["rocio"]); comprueba("rho ROCIO", 0.82, rho(ro[:,0], ro[:,1]), 0.01)
ae = d["brecha_aemet"];    comprueba("rho AEMET", 0.54, rho([r[0] for r in ae], [r[1] for r in ae]), 0.01)
pr = np.array(d["brecha_proy"]["ssp245"]); comprueba("rho CMIP6", 0.61, rho(pr[:,0], pr[:,1]), 0.01)
assert len(ae) == 10, f"el texto dice 'solo hay diez' y hay {len(ae)}"
print(f"  ok   'solo hay diez' estaciones: {len(ae)}")
mon = [r for r in ae if "Monforte" in r[2]]
assert mon and mon[0][1] < 0, "el texto cita Monforte como contraejemplo; su tendencia debe ser <= 0"
print(f"  ok   Monforte de Lemos apunta al reves: {mon[0][1]:+.2f} dias/decada")

print("\n=== cifras de los escenarios ===")
t = d["escenarios"]["tasmaxp99"]
comprueba("SSP2-4.5 2041-2070", 2.9, t["ssp245"]["medium_future"][0], 0.01)
comprueba("SSP5-8.5 2071-2100", 6.64, t["ssp585"]["far_future"][0], 0.01)
n40 = [t[e]["near_future"][0] for e in t]
assert max(n40) - min(n40) < 0.2, f"el texto dice que hasta 2040 coinciden: {n40}"
print(f"  ok   'hasta 2040 los cuatro coinciden': {min(n40):.2f} a {max(n40):.2f}")
comprueba("noches tropicales 2041-2070", 0.26, d["escenarios"]["tasminNa20"]["ssp245"]["medium_future"][0], 0.01)

print("\n=== ranking y validacion ===")
p = d["puntos"]
comprueba("mejor punto, tx_p99 crudo", 19.91, p[0]["tx_p99_1km"], 0.01)
assert p[0]["wrf_n_ge32"] == 0, p[0]
print(f"  ok   el primero tiene 0 dias >32 C, cerca de {p[0]['cerca']}")
r = pd.read_csv(f"{R}/ranking_con_proyeccion.csv")
hoy = set(map(tuple, r.nsmallest(20, "tx_p99_1km")[["lat","lon"]].values))
fut = set(map(tuple, r.nsmallest(20, "tx_p99_ssp245")[["lat","lon"]].values))
comprueba("'19 de 20 siguen'", 19, len(hoy & fut), 0)
a = pd.read_csv(f"{R}/alta_resolucion.csv.gz"); a = a[a.tierra == 1]
rango = a.tx_p99_1km.max() - a.tx_p99_1km.min()
comprueba("'16,5 C de diferencia'", 16.5, rango, 0.6)
comprueba("'0 vs 169 dias >32'", 169, a.wrf_n_ge32.max(), 0)

print("\n=== el mapa apunta al norte ===")
M = json.load(open("datos_mapa.json"))["malla"]
import base64
by = base64.b64decode(M["tx"]["d"])
def val(la, lo):
    sy = round((la - M["s"])/M["paso"] - 0.5); sx = round((lo - M["o"])/M["paso"] - 0.5)
    q = by[sy*M["nx"] + sx]
    return None if q == 0 else M["tx"]["lo"] + (q-1)/254*(M["tx"]["hi"]-M["tx"]["lo"]) + 2.74
cor, our = val(43.37, -8.40), val(42.34, -7.86)
print(f"  A Coruña {cor:.1f} C (termometro 26,5-28,1) · Ourense {our:.1f} C (termometro 39,2-39,8)")
assert cor < our - 5, "Ourense tiene que salir MUCHO mas caluroso que A Coruña"
assert 26 < cor < 31 and 35 < our < 40, f"valores fuera de rango: {cor}, {our}"
ok += 1; print("  ok   la orientacion norte-sur es correcta")

print("\n=== los extremos que se pintan en los mapas pequenios ===")
ex = d["extremos"]
for lado in ("frescos", "calidos"):
    n_sitios = len({q["cerca"] for q in ex[lado]})
    print("  " + lado + ": " + ", ".join(f"{q['cerca']} ({q['tx']})" for q in ex[lado]))
    assert n_sitios == 4, f"los cuatro tienen que ser sitios distintos, hay {n_sitios}"
    ok += 1
# ninguno puede caer fuera de Galicia: el fallo real fue tener Caminha entre los
# cuatro sitios mas frescos "de Galicia"
for q in ex["frescos"] + ex["calidos"]:
    assert q["lat"] > 41.80, f"{q['cerca']} en {q['lat']} esta al sur del Mino: es Portugal"
    assert q["lon"] < -6.75, f"{q['cerca']} en {q['lon']} esta demasiado al este"
ok += 1
print(f"  ok   ninguno cae fuera de Galicia ({d['mascara']['dentro']:,} de "
      f"{d['mascara']['total']:,} puntos dentro de la mascara)")
comprueba("Baiona entre los mas frescos", 23.4,
          [q["tx"] for q in ex["frescos"] if q["cerca"] == "Baiona"][0], 0.05)

print("\n=== glosario: cada termino marcado tiene definicion ===")
marcados = set(re.findall(r'class="gl" data-t="([a-z0-9]+)"', html))
definidos = set(re.findall(r'^  ([a-z0-9]+): \["', html, re.M))
faltan = marcados - definidos
if faltan: fallos.append(f"terminos sin definicion: {faltan}")
else: ok += 1; print(f"  ok   {len(marcados)} terminos marcados, todos definidos")
sobran = definidos - marcados
if sobran: print(f"  aviso: definidos y no usados en el texto: {sobran}")

print("\n=== textos que prometen algo ===")
for frase, cond in [("40.050", "40.050 puntos" in html), ("1.657 celdas", "1.657" in html),
                    ("−6,46 °C/km", "−6,46" in html), ("0,962", "0,962" in html),
                    ("+2,7 °C de sesgo", "+2,7" in html),
                    ("la capa de tendencia", "Cuánto se calienta" in html),
                    ("el aviso del dominio", "no es Galicia, es un rectángulo" in html),
                    ("la aclaración del humidex", "lo que no tiene proyección es la\nhumedad" in html)]:
    if cond: ok += 1; print(f"  ok   aparece {frase}")
    else: fallos.append(f"falta la mencion de {frase}")

print(f"\n{'='*60}\n{ok} comprobaciones pasadas, {len(fallos)} fallos")
for f in fallos: print("  FALLO: " + f)
raise SystemExit(1 if fallos else 0)
