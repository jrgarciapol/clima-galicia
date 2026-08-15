"""Pruebas del paso 8: ajuste de Gumbel, periodos de retorno y bulbo humedo.

Lo importante que se comprueba:
  - el ajuste por momentos-L recupera los parametros de una Gumbel conocida
  - el nivel de retorno y el periodo son inversos exactos entre si
  - cuanto se pierde por usar momentos-L en vez de maxima verosimilitud
    (spoiler: se pierde algo, y por eso el codigo lo dice en vez de venderlo)
  - el bootstrap produce un intervalo que contiene el valor verdadero
  - el bulbo humedo coincide con valores de referencia publicados
"""
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
TMP = os.path.join(KIT, "_pruebas_tmp4")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP
ENTORNO = dict(os.environ)

import importlib.util  # noqa: E402

from comun import bulbo_humedo, humedad_relativa  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "paso08", os.path.join(KIT, "08_periodos_retorno.py"))
p8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p8)

print("=== bulbo humedo frente a referencias ===")
# Valores de referencia de tablas psicrometricas (Stull 2011, tabla 1)
REF = [(20, 50, 13.7), (30, 50, 22.3), (25, 20, 12.9), (40, 20, 22.7)]
for t, rh, esperado in REF:
    obt = float(bulbo_humedo(t, rh))
    print(f"  T={t} HR={rh}%  esperado {esperado:.1f}  obtenido {obt:.2f}")
    assert abs(obt - esperado) < 0.5, (t, rh, esperado, obt)
# casi saturado (99 %): el bulbo humedo debe quedar justo por debajo de la seca,
# no exactamente igual, porque al 99 % todavia queda un pelo de evaporacion
for t in (10, 25, 35):
    dif = float(bulbo_humedo(t, 99)) - t
    assert -0.30 < dif < 0.0, (t, dif)
# nunca puede superar la temperatura seca
tt = np.linspace(-5, 45, 60)
for rh in (10, 40, 70, 95):
    assert np.all(bulbo_humedo(tt, rh) <= tt + 0.05), rh
print("  ok: coincide con las tablas, satura en T y nunca la supera")

print("\n=== ajuste de Gumbel por momentos-L ===")
MU, SIGMA = 36.0, 2.2
rng = np.random.default_rng(4)
grande = rng.gumbel(MU, SIGMA, 20000)
m, s = p8.gumbel_lmom(grande)
print(f"  con 20.000 datos: mu {m:.3f} (real {MU})   sigma {s:.3f} (real {SIGMA})")
assert abs(m - MU) < 0.06 and abs(s - SIGMA) < 0.06
print("  ok")

print("\n=== nivel de retorno y periodo son inversos ===")
for T in (5, 10, 20, 50, 100):
    x = p8.nivel_retorno(MU, SIGMA, T)
    T2 = p8.periodo_de(MU, SIGMA, x)
    print(f"  T={T:3d} -> {x:.2f} C -> T={T2:.1f}")
    assert abs(T2 - T) < 0.05 * T
# monotonia: a mas periodo, mas temperatura
niveles = [p8.nivel_retorno(MU, SIGMA, T) for T in (2, 5, 10, 20, 50, 100)]
assert all(np.diff(niveles) > 0)
print("  ok")

print("\n=== momentos-L frente a maxima verosimilitud con series cortas ===")
from scipy.stats import gumbel_r  # noqa: E402

err_lmom, err_mle = [], []
verdadero20 = p8.nivel_retorno(MU, SIGMA, 20)
for k in range(300):
    m_ = np.random.default_rng(k).gumbel(MU, SIGMA, 17)   # 17 anios, como el real
    a, b = p8.gumbel_lmom(m_)
    err_lmom.append(p8.nivel_retorno(a, b, 20) - verdadero20)
    c, d = gumbel_r.fit(m_)
    err_mle.append(p8.nivel_retorno(c, d, 20) - verdadero20)
rl, rm = np.sqrt(np.mean(np.square(err_lmom))), np.sqrt(np.mean(np.square(err_mle)))
print(f"  error cuadratico medio del nivel a 20 anios (n=17):")
print(f"    momentos-L {rl:.3f} C     maxima verosimilitud {rm:.3f} C")
# La creencia extendida es que los momentos-L ganan con series cortas. Para una
# Gumbel de DOS parametros no es cierto: eso vale para la GEV de tres. Aqui solo
# se exige que la perdida sea pequena, porque los momentos-L se eligieron por ser
# cerrados y robustos, no por precision.
assert rl < 1.3 * rm, f"la perdida por usar momentos-L no deberia pasar del 30 % ({rl / rm:.2f})"
print(f"  momentos-L pierde un {100 * (rl / rm - 1):.0f} % frente a MV.")
print("  Se aceptan igualmente: no son iterativos (cientos de miles de ajustes")
print("  en el bootstrap) y aguantan mejor un valor anomalo.")

print("\n=== cobertura del bootstrap ===")
dentro = 0
N = 120
for k in range(N):
    m_ = np.random.default_rng(1000 + k).gumbel(MU, SIGMA, 17)
    lo, hi = p8.bootstrap(m_, 20, n=200, semilla=k)
    if np.isfinite(lo) and lo <= verdadero20 <= hi:
        dentro += 1
cob = dentro / N
print(f"  el intervalo del 90 % contiene el valor verdadero en el {cob * 100:.0f} % de los casos")
assert 0.60 < cob < 1.0, cob
print("  ok (con n=17 el bootstrap subcubre algo, es esperable y honesto)")

print("\n=== ajuste NO estacionario ===")
# Sesgo y potencia del estimador de tendencia sobre muchas realizaciones.
# Con una sola serie el ruido es enorme; lo que hay que comprobar es que de
# media acierta y que el contraste no inventa tendencias donde no las hay.
anios = np.arange(1996, 2026)
for inyectado in (0.0, 0.5):
    recup, signif = [], []
    for k in range(200):
        x = np.random.default_rng(k).gumbel(35 + inyectado * (anios - 2011) / 10, 2.0)
        aj = p8.ajusta_no_estacionario(anios, x)
        if aj:
            recup.append(aj["mu1_por_decada"])
            signif.append(aj["tendencia_significativa"])
    recup = np.array(recup)
    tasa = np.mean(signif)
    print(f"  inyectado {inyectado:+.2f} C/dec -> media {recup.mean():+.3f}"
          f"  desv {recup.std():.3f}   detectada en el {tasa*100:.0f} % de los casos")
    assert abs(recup.mean() - inyectado) < 0.12, f"el estimador deberia ser insesgado"
    if inyectado == 0.0:
        # tasa de falsos positivos del contraste: debe rondar el 5 %, no mas
        assert tasa < 0.12, f"demasiados falsos positivos ({tasa:.2f})"
    else:
        # HALLAZGO: con 30 maximas anuales y sigma=2 C, una tendencia de
        # +0,5 C/decada solo se detecta en ~1 de cada 4 casos. El estimador es
        # insesgado, pero su desviacion (0,40) es casi igual a la senial (0,50).
        # No es un defecto del codigo: es el limite de informacion del dato.
        # De ahi que el paso 8 calcule ademas una tendencia REGIONAL agrupando
        # todos los puntos, cuyo error tipico baja con la raiz de N.
        assert 0.15 < tasa < 0.45, f"potencia esperada en torno al 25 % ({tasa:.2f})"
print("  ok: insesgado y con la tasa de falsos positivos correcta;")
print("  la potencia por punto es baja, y por eso hace falta agrupar")

print("\n=== la agrupacion regional recupera la potencia perdida ===")
# Misma tendencia inyectada, pero estimada sobre 100 puntos a la vez.
estimaciones = []
for k in range(100):
    x = np.random.default_rng(5000 + k).gumbel(35 + 0.5 * (anios - 2011) / 10, 2.0)
    aj = p8.ajusta_no_estacionario(anios, x)
    if aj:
        estimaciones.append(aj["mu1_por_decada"])
reg = p8.tendencia_regional(estimaciones)
print(f"  con 1 punto:    {estimaciones[0]:+.3f} C/dec")
print(f"  con {len(estimaciones)} puntos: {reg['media']:+.3f} +/- {reg['error']:.3f} C/dec"
      f"  (IC 95 %: {reg['ic95'][0]:+.3f} a {reg['ic95'][1]:+.3f})")
assert abs(reg["media"] - 0.5) < 0.09, reg["media"]
assert reg["error"] < 0.06, "el error tipico deberia caer con la raiz de N"
assert reg["ic95"][0] > 0, "con 100 puntos la tendencia si debe ser distinguible de cero"
print("  ok: de no poder afirmar nada a un intervalo estrecho que excluye el cero")

print("\n=== niveles evaluados en el tiempo y probabilidad de superacion ===")
x = np.random.default_rng(7).gumbel(35 + 0.6 * (anios - 2011) / 10, 2.0)
aj = p8.ajusta_no_estacionario(anios, x)
n26, n45 = p8.nivel_retorno_en(aj, 20, 2026), p8.nivel_retorno_en(aj, 20, 2045)
print(f"  nivel a 20 anios: {n26:.2f} C en 2026  ->  {n45:.2f} C en 2045")
assert n45 > n26, "con tendencia al alza, el nivel futuro debe ser mayor"
assert p8.nivel_retorno_en(aj, 50, 2026) > n26, "mas periodo, mas temperatura"

ps = [p8.prob_superar(aj, u, 2026, 2055) for u in (30, 35, 40, 45, 50)]
print(f"  P(superar alguna vez en 2026-2055): {[round(v, 3) for v in ps]}")
assert all(0 <= v <= 1 for v in ps), "una probabilidad no puede salirse de [0,1]"
assert all(np.diff(ps) <= 0), "cuanto mas alto el umbral, menos probable superarlo"
assert ps[0] > 0.99, "superar 30 C alguna vez en 30 anios es practicamente seguro"
assert ps[-1] < 0.2, "superar 50 C deberia ser muy improbable"
# ventana mas larga, probabilidad mayor
assert (p8.prob_superar(aj, 42, 2026, 2075)
        > p8.prob_superar(aj, 42, 2026, 2035)), "mas anios expuesto, mas riesgo"
print("  ok")

print("\n=== series demasiado cortas se rechazan ===")
assert p8.analiza(pd.Series([30, 31, 32]), "x") is None
assert not np.isfinite(p8.gumbel_lmom([1, 2, 3])[0])
assert not np.isfinite(p8.gumbel_lmom([5.0] * 20)[0]), "sin varianza no hay ajuste"
assert p8.ajusta_no_estacionario([2020, 2021, 2022], [30, 31, 32]) is None
print("  ok")

print("\n=== extremo a extremo sobre estaciones ===")
filas = []
for est, mu in ((201, 34.0), (202, 40.0)):
    for a in range(2009, 2026):
        filas.append({"estacion": est, "anio": a,
                      "tx_max": np.random.default_rng(est * 100 + a).gumbel(mu, 2.0),
                      "concello": f"E{est}", "provincia": "Lugo",
                      "lat": 43.0, "lon": -8.0, "alt": 100})
pd.DataFrame(filas).to_csv(os.path.join(TMP, "evolucion_estaciones.csv"), index=False)

r = subprocess.run([sys.executable, "08_periodos_retorno.py", "--solo-estaciones"],
                   cwd=KIT, capture_output=True, text=True, env=ENTORNO)
print(r.stdout[-1800:])
if r.returncode != 0:
    print(r.stderr[-2500:])
    sys.exit("08 fallo")

d = pd.read_csv(os.path.join(TMP, "retorno_estaciones.csv"))
print(f"\n  filas: {len(d)}  columnas: {list(d.columns)[:12]}")
assert len(d) == 2
fria = d[d.estacion == 201].iloc[0]
calida = d[d.estacion == 202].iloc[0]
assert calida.retorno_20a > fria.retorno_20a + 4, "debe separar los dos climas"
for T in (5, 10, 20, 50):
    assert f"retorno_{T}a" in d.columns
assert (d.retorno_50a > d.retorno_20a).all() > 0
assert (d.retorno_20a_p5 <= d.retorno_20a).all()
assert (d.retorno_20a_p95 >= d.retorno_20a).all()
assert (d.retorno_20a > d.media_max).all(), "el extremo a 20 anios supera a la media"
print("  ok")

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 8 VALIDADO")
