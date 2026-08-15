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
    print("  " + lado + ": " + ", ".join(f"{q['cerca']} ({q['tx']})"
                                          for q in ex[lado][:6]) + " ...")
    # Se comprueba la separacion GEOGRAFICA, no que el nombre sea distinto: el
    # nombre es el de la estacion mas cercana y puede repetirse legitimamente
    # (dos puntos a 12 km uno de otro pueden tener la misma estacion al lado).
    kk = np.cos(np.radians(43.0))
    for i in range(len(ex[lado])):
        for j in range(i + 1, len(ex[lado])):
            a_, b_ = ex[lado][i], ex[lado][j]
            sep = np.hypot(a_["lat"] - b_["lat"], (a_["lon"] - b_["lon"]) * kk) * 111
            assert sep > 11.5, (f"{a_['cerca']} y {b_['cerca']} estan a {sep:.1f} km: "
                                "se taparian en el mapa")
    ok += 1
    print(f"  ok   los {len(ex[lado])} estan separados mas de 12 km entre si")

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

print("\n=== el indice: descrito Y usado, que era lo que fallaba ===")
assert all("ind" in q for q in ex["frescos"]), "las listas tienen que llevar el indice"
_f = [q["ind"] for q in ex["frescos"]]
_c = [q["ind"] for q in ex["calidos"]]
assert _f == sorted(_f, reverse=True), f"los frescos no estan ordenados por indice: {_f}"
assert _c == sorted(_c), f"los calidos no estan ordenados por indice: {_c}"
assert abs(_f[0] - 100) < 0.1 and abs(_c[0]) < 0.1, "la escala tiene que ir de 0 a 100"
ok += 2
print(f"  ok   listas ordenadas por indice: frescos {_f[0]:.0f}-{_f[-1]:.0f}, "
      f"calidos {_c[0]:.0f}-{_c[-1]:.0f}")
assert '"ind"' in html and "Índice 60/40" in html, "el indice tiene que ser una capa del mapa"
ok += 1
print("  ok   el indice es la primera capa del mapa")

print("\n=== la compresion del humidex ===")
_cp = d["compresion"]
_our = _cp["ourense"]["tx"] - _cp["ourense"]["hx"]
_cor = _cp["coruna_interior"]["tx"] - _cp["coruna_interior"]["hx"]
comprueba("Ourense: tx", 36.1, _cp["ourense"]["tx"], 0.05)
comprueba("Ourense: humidex", 37.1, _cp["ourense"]["hx"], 0.05)
comprueba("A Coruña interior: tx", 32.3, _cp["coruna_interior"]["tx"], 0.05)
comprueba("A Coruña interior: humidex", 35.4, _cp["coruna_interior"]["hx"], 0.05)
_dtx = _cp["ourense"]["tx"] - _cp["coruna_interior"]["tx"]
_dhx = _cp["ourense"]["hx"] - _cp["coruna_interior"]["hx"]
comprueba("los 3,8 C de diferencia en seco", 3.8, _dtx, 0.05)
comprueba("se quedan en 1,7 de humidex", 1.7, _dhx, 0.05)
assert _dhx < _dtx, "el texto dice que el humidex COMPRIME; si no, hay que reescribirlo"
ok += 1

print("\n=== las 153 estaciones proyectadas ===")
_ef = d["estaciones_futuro"]
assert len(_ef) == 153, f"deberian ser 153 y hay {len(_ef)}"
_dd = [x["d"] for x in _ef]
comprueba("anomalia minima", 1.48, min(_dd), 0.02)
comprueba("anomalia maxima", 4.02, max(_dd), 0.02)
# "ninguna adelanta a otra por mucho": lo que hay que medir no es cuantos pares
# se cruzan sino CUANTO. Un par separado por 0,3 C que se invierte a 0,4 no
# reordena nada relevante; lo grave seria un adelantamiento de grados.
_cr = [(abs(_ef[i]["hoy"] - _ef[j]["hoy"]), abs(_ef[i]["fut"] - _ef[j]["fut"]))
       for i in range(len(_ef)) for j in range(i + 1, len(_ef))
       if (_ef[i]["hoy"] - _ef[j]["hoy"]) * (_ef[i]["fut"] - _ef[j]["fut"]) < 0]
_pares = len(_ef) * (len(_ef) - 1) // 2
_grandes = sum(1 for _, f in _cr if f > 1.0)
_rho = float(np.corrcoef(pd.Series([x["hoy"] for x in _ef]).rank(),
                         pd.Series([x["fut"] for x in _ef]).rank())[0, 1])
print(f"  {len(_ef)} estaciones; {len(_cr)} pares se cruzan de {_pares:,} "
      f"({len(_cr)/_pares:.1%}), y solo {_grandes} lo hacen por mas de 1 C")
comprueba("correlacion de rangos hoy vs futuro", 0.99, _rho, 0.005)
assert _grandes < 30, f"{_grandes} adelantamientos de mas de 1 C: eso ya no es 'por poco'"
ok += 1

print("\n=== el peso 60/40, que es la afirmacion mas fragil del informe ===")
import pandas as _pd
from scipy.spatial import ConvexHull as _CH
from matplotlib.path import Path as _P
_est = _pd.read_csv(f"{R}/estaciones_lista.csv")
_gal = _P(_est[["lon", "lat"]].values[_CH(_est[["lon", "lat"]].values).vertices])
_a = _pd.read_csv(f"{R}/alta_resolucion.csv.gz")
_a = _a[(_a.tierra == 1) & (_a.altitud < 400)].dropna(subset=["tx_p99_1km", "hx_p99_1km"])
# la misma mascara de Galicia que usa el informe: si no, no es el mismo conjunto
_a = _a[_gal.contains_points(_a[["lon", "lat"]].values, radius=0.08)]
assert abs(len(_a) - 11794) < 5, f"el informe dice 11.794 puntos y hay {len(_a)}"
print(f"  ok   11.794 puntos: {len(_a)}")
_z = lambda x: (x - x.mean()) / x.std()
_a = _a.assign(zt=_z(_a.tx_p99_1km), zh=_z(_a.hx_p99_1km))
_corr = float(np.corrcoef(_a.tx_p99_1km, _a.hx_p99_1km)[0, 1])
comprueba("correlacion entre las dos mitades", 0.95, _corr, 0.01)
_top = lambda w: set(map(tuple, _a.assign(n=w*_a.zt + (1-w)*_a.zh)
                         .nsmallest(12, "n")[["lat", "lon"]].round(4).values))
_b = _top(0.6)
for _w, _min in ((0.8, 11), (0.5, 11), (0.4, 10)):
    _c = len(_top(_w) & _b)
    assert _c >= _min, f"con peso {_w}, solo {_c}/12 coinciden y el texto promete {_min}"
    print(f"  ok   peso {_w:.0%}/{1-_w:.0%}: {_c}/12 de los mejores coinciden")
ok += 3

print("\n=== referencias cruzadas ===")
_anclas = set(re.findall(r'id="([a-z]+)"', html))
_refs = set(re.findall(r'class="ref" href="#([a-z]+)"', html) +
            re.findall(r'href="#([a-z]+)" class="ref"', html))
_rotas = _refs - _anclas
if _rotas: fallos.append(f"referencias a secciones que no existen: {_rotas}")
else: ok += 1; print(f"  ok   {len(_refs)} destinos referenciados, todos existen")

print("\n=== nada de tuteo: lo lee cualquiera, no solo quien lo encargo ===")
_cuerpo = html[html.index('<section id="intro">'):html.index('<div id="pista"')]
_mal = re.findall(r'\b(tenías razón|te dije|tu comentario|pincha|verás|pruébala|contigo)\b',
                  _cuerpo, re.I)
if _mal: fallos.append(f"quedan formas de segunda persona: {set(_mal)}")
else: ok += 1; print("  ok   el cuerpo del informe no interpela al lector")

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
