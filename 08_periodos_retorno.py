"""PASO 8 - Periodos de retorno: no cuantas veces, sino cuan mal se puede poner.

Contar dias por encima de 32 C responde a "con que frecuencia". Para una casa
que vas a habitar treinta anios, la pregunta util es otra: **cual es la maxima
que toca una vez cada 10, 20 o 50 anios en este sitio**. Eso es un periodo de
retorno, y se estima ajustando una distribucion de valores extremos a la serie
de maximas anuales.

Metodo
------
Distribucion de **Gumbel** (valores extremos tipo I), que es la que se usa por
convenio para maximas anuales de temperatura. Se ajusta por **momentos-L**:

    sigma = l2 / ln(2)
    mu    = l1 - 0.5772 * sigma

y el nivel de retorno para un periodo T sale de:

    x(T) = mu - sigma * ln(-ln(1 - 1/T))

Nota honesta sobre esa eleccion: se suele repetir que los momentos-L baten a la
maxima verosimilitud con series cortas, y `test_retorno.py` lo comprueba y
resulta **falso** para una Gumbel de dos parametros: con n=17 la maxima
verosimilitud sale ligeramente mejor en error cuadratico medio (~1,6 C frente a
~1,8 C). Esa ventaja de los momentos-L es real para la GEV de tres parametros,
donde el parametro de forma es dificil de estimar, y aqui no aplica.

Se usan igualmente, por dos razones que si se sostienen:

  - **Son cerrados y no iterativos.** El bootstrap hace 500 ajustes por punto y
    hay cientos de puntos: son cientos de miles de ajustes. La maxima
    verosimilitud es iterativa y puede no converger; los momentos-L no fallan
    nunca ni tienen que converger.
  - **Aguantan mejor un valor anomalo**, que en series de maximas observadas es
    exactamente lo que hay que temer.

La diferencia entre ambos metodos (0,2 C) es pequena al lado de la incertidumbre
real del intervalo de confianza, que ronda los 2 C.

La incertidumbre se estima por **bootstrap**: se remuestrea la serie de maximas
500 veces y se toman los percentiles 5 y 95. Con series cortas ese intervalo es
ancho, y verlo es parte del resultado.

Dos advertencias que van impresas en la salida, porque importan
--------------------------------------------------------------
1. **Extrapolar mas alla de 2 o 3 veces la longitud del registro es
   especulativo.** Con 17 anios, el valor a 20 anios es solido y el de 50 es
   orientativo. Con los 30 de ERA5-Land, el de 50 ya se sostiene.
2. **Gumbel supone un clima estacionario**, y el clima no lo es. Si hay
   tendencia, el periodo de retorno calculado sobre todo el registro subestima
   el riesgo actual. Por eso se calcula tambien sobre la segunda mitad del
   periodo y se comparan: la diferencia es una medida directa de cuanto se ha
   movido el terreno bajo los pies.

Uso:
    python 08_periodos_retorno.py            # estaciones y malla, lo que haya
    python 08_periodos_retorno.py --solo-estaciones
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
PERIODOS = (5, 10, 20, 50)
EULER = 0.5772156649015329


def gumbel_lmom(x):
    """Ajusta Gumbel por momentos-L. Devuelve (mu, sigma)."""
    x = np.sort(np.asarray(x, dtype=float))
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 8:
        return np.nan, np.nan
    l1 = x.mean()
    # segundo momento-L mediante momentos ponderados por probabilidad
    i = np.arange(1, n + 1)
    b1 = np.sum((i - 1) / (n - 1) * x) / n
    l2 = 2 * b1 - l1
    if l2 <= 0:
        return np.nan, np.nan
    sigma = l2 / np.log(2)
    mu = l1 - EULER * sigma
    return float(mu), float(sigma)


def nivel_retorno(mu, sigma, T):
    """Valor esperado una vez cada T anios."""
    if not np.isfinite(mu) or not np.isfinite(sigma):
        return np.nan
    return float(mu - sigma * np.log(-np.log(1 - 1 / T)))


def periodo_de(mu, sigma, x):
    """Cada cuantos anios se espera un valor de al menos x."""
    if not np.isfinite(mu) or not np.isfinite(sigma):
        return np.nan
    p = np.exp(-np.exp(-(x - mu) / sigma))       # probabilidad de no superarlo
    return float(np.inf) if p >= 1 else float(1 / (1 - p))


def bootstrap(x, T, n=500, semilla=0):
    """Intervalo del 90 % para el nivel de retorno, por remuestreo."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 8:
        return np.nan, np.nan
    rng = np.random.default_rng(semilla)
    vals = []
    for _ in range(n):
        m, s = gumbel_lmom(rng.choice(x, len(x), replace=True))
        v = nivel_retorno(m, s, T)
        if np.isfinite(v):
            vals.append(v)
    if len(vals) < n // 4:
        return np.nan, np.nan
    return float(np.percentile(vals, 5)), float(np.percentile(vals, 95))


# ---------------------------------------------------------------------------
# Ajuste NO estacionario: la posicion de la distribucion se mueve con el tiempo
# ---------------------------------------------------------------------------

def _neg_ll(par, t, x, con_tendencia):
    """Menos log-verosimilitud de una Gumbel con mu(t) = mu0 + mu1*t."""
    if con_tendencia:
        mu0, mu1, logs = par
        mu = mu0 + mu1 * t
    else:
        mu0, logs = par
        mu = mu0
        mu1 = 0.0
    sigma = np.exp(logs)
    z = (x - mu) / sigma
    return float(len(x) * logs + np.sum(z) + np.sum(np.exp(-z)))


def ajusta_no_estacionario(anios, x, anio_ref=None):
    """Gumbel con posicion lineal en el tiempo, por maxima verosimilitud.

    Aqui SI se usa maxima verosimilitud y no momentos-L: los momentos-L no
    tienen version no estacionaria, y ademas hace falta la verosimilitud para
    poder contrastar los dos modelos entre si.

    Devuelve un dict con los parametros, el contraste de razon de verosimilitud
    frente al modelo estacionario y su p-valor.
    """
    from scipy.optimize import minimize
    from scipy.stats import chi2

    anios = np.asarray(anios, dtype=float)
    x = np.asarray(x, dtype=float)
    ok = np.isfinite(x) & np.isfinite(anios)
    anios, x = anios[ok], x[ok]
    if len(x) < 10:
        return None
    if anio_ref is None:
        anio_ref = float(np.median(anios))
    t = anios - anio_ref

    mu_l, sg_l = gumbel_lmom(x)
    if not np.isfinite(mu_l):
        return None
    p0_est = [mu_l, np.log(max(sg_l, 1e-3))]
    p0_ten = [mu_l, 0.0, np.log(max(sg_l, 1e-3))]

    r_est = minimize(_neg_ll, p0_est, args=(t, x, False), method="Nelder-Mead",
                     options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-8})
    r_ten = minimize(_neg_ll, p0_ten, args=(t, x, True), method="Nelder-Mead",
                     options={"maxiter": 8000, "xatol": 1e-6, "fatol": 1e-8})
    if not (r_est.success and r_ten.success):
        return None

    ll_est, ll_ten = -r_est.fun, -r_ten.fun
    D = 2 * (ll_ten - ll_est)
    p_lrt = float(chi2.sf(D, 1)) if D > 0 else 1.0
    mu0, mu1, logs = r_ten.x
    return {"anio_ref": anio_ref, "mu0": float(mu0), "mu1_por_decada": float(mu1) * 10,
            "sigma": float(np.exp(logs)), "lrt": float(D), "p_tendencia": p_lrt,
            "tendencia_significativa": bool(p_lrt < 0.05)}


def tendencia_regional(mu1_por_punto):
    """Agrupa las tendencias de muchos puntos en una sola estimacion.

    Por que hace falta: `test_retorno.py` mide que, con 30 maximas anuales y una
    dispersion tipica de 2 C, el contraste solo detecta una tendencia de
    +0,5 C/decada en uno de cada cuatro puntos. El estimador es insesgado pero
    su ruido (0,40) casi iguala a la senial (0,50). Por punto no se puede
    afirmar casi nada.

    Agrupando, en cambio, el error tipico cae con la raiz del numero de puntos,
    y Galicia entera se calienta a la vez, asi que la media regional es una
    estimacion mucho mas solida que cualquiera de las individuales. Lo sensato
    es usar la tendencia regional para proyectar y quedarse con las
    individuales solo como indicacion de si un sitio se desvia del conjunto.
    """
    v = np.asarray([x for x in mu1_por_punto if np.isfinite(x)], dtype=float)
    if len(v) < 5:
        return None
    media = float(v.mean())
    error = float(v.std(ddof=1) / np.sqrt(len(v)))
    return {"n": int(len(v)), "media": media, "mediana": float(np.median(v)),
            "error": error, "desv": float(v.std(ddof=1)),
            "ic95": (round(media - 1.96 * error, 4), round(media + 1.96 * error, 4))}


def nivel_retorno_en(aj, T, anio):
    """Nivel de retorno T evaluado en un anio concreto del modelo con tendencia."""
    mu = aj["mu0"] + (aj["mu1_por_decada"] / 10) * (anio - aj["anio_ref"])
    return float(mu - aj["sigma"] * np.log(-np.log(1 - 1 / T)))


def prob_superar(aj, umbral, anio_ini, anio_fin):
    """Probabilidad de superar `umbral` AL MENOS UNA VEZ entre dos anios.

    Esta es la cifra que de verdad corresponde a una decision de vivienda, y no
    el periodo de retorno: "una vez cada 50 anios" suena raro, pero la
    probabilidad de verlo alguna vez en 30 anios de ocupacion no lo es.
    """
    anios = np.arange(anio_ini, anio_fin + 1)
    mu = aj["mu0"] + (aj["mu1_por_decada"] / 10) * (anios - aj["anio_ref"])
    p_no = np.exp(-np.exp(-(umbral - mu) / aj["sigma"]))   # no superarlo cada anio
    return float(1 - np.prod(np.clip(p_no, 0, 1)))


def analiza(maximas, etiqueta, semilla=0):
    """Ficha completa de una serie de maximas anuales."""
    s = pd.Series(maximas).dropna().sort_index()
    if len(s) < 8:
        return None
    mu, sigma = gumbel_lmom(s.values)
    r = {"n_anios": len(s), "media_max": round(float(s.mean()), 2),
         "max_observada": round(float(s.max()), 2),
         "gumbel_mu": round(mu, 3), "gumbel_sigma": round(sigma, 3)}
    for T in PERIODOS:
        r[f"retorno_{T}a"] = round(nivel_retorno(mu, sigma, T), 2)
    lo, hi = bootstrap(s.values, 20, semilla=semilla)
    r["retorno_20a_p5"], r["retorno_20a_p95"] = round(lo, 2), round(hi, 2)
    r["periodo_de_la_maxima"] = round(periodo_de(mu, sigma, s.max()), 1)

    # no estacionariedad: mismo ajuste sobre la segunda mitad del registro
    if len(s) >= 14:
        corte = s.index[len(s) // 2]
        m2, s2 = gumbel_lmom(s[s.index > corte].values)
        if np.isfinite(m2):
            r["retorno_20a_2a_mitad"] = round(nivel_retorno(m2, s2, 20), 2)
            r["desplazamiento"] = round(r["retorno_20a_2a_mitad"] - r["retorno_20a"], 2)
    # --- modelo no estacionario -------------------------------------------
    aj = ajusta_no_estacionario(s.index.values, s.values)
    if aj:
        r["ns_tendencia_dec"] = round(aj["mu1_por_decada"], 3)
        r["ns_p_tendencia"] = round(aj["p_tendencia"], 4)
        r["ns_significativa"] = aj["tendencia_significativa"]
        r["ns_retorno_20a_2026"] = round(nivel_retorno_en(aj, 20, 2026), 2)
        r["ns_retorno_20a_2045"] = round(nivel_retorno_en(aj, 20, 2045), 2)
        # sesgo del modelo estacionario frente al riesgo de hoy
        r["sesgo_estacionario"] = round(r["ns_retorno_20a_2026"] - r["retorno_20a"], 2)
        # probabilidad de superar el propio maximo historico en 30 anios
        r["p_superar_max_30a"] = round(
            prob_superar(aj, float(s.max()), 2026, 2055), 3)
    r["serie"] = etiqueta
    return r


# ---------------------------------------------------------------------------

def desde_estaciones():
    ruta = os.path.join(BASE, "evolucion_estaciones.csv")
    if not os.path.exists(ruta):
        print("(sin evolucion_estaciones.csv: ejecuta antes 07_evolucion_estaciones.py)")
        return None
    ev = pd.read_csv(ruta)
    filas = []
    for est, g in ev.groupby("estacion"):
        g = g.set_index("anio").sort_index()
        for var, etq in (("tx_max", "temperatura maxima"),):
            if var not in g:
                continue
            r = analiza(g[var], etq, semilla=int(est) % 10000)
            if r is None:
                continue
            r["estacion"] = est
            for c in ("concello", "provincia", "lat", "lon", "alt"):
                if c in g:
                    r[c] = g[c].iloc[0]
            filas.append(r)
    if not filas:
        return None
    d = pd.DataFrame(filas)
    pri = [c for c in ("estacion", "concello", "provincia", "alt", "serie") if c in d]
    d = d[pri + [c for c in d.columns if c not in pri]]
    d.sort_values("retorno_20a").to_csv(
        os.path.join(BASE, "retorno_estaciones.csv"), index=False)
    print(f"retorno_estaciones.csv: {len(d)} estaciones")
    return d


def desde_malla():
    cache = os.path.join(BASE, "diarios_galicia.nc")
    if not os.path.exists(cache):
        print("(sin diarios_galicia.nc: ejecuta antes 01 y 02)")
        return None
    import xarray as xr

    ds = xr.open_dataset(cache)
    tiempo = pd.DatetimeIndex(ds.time.values)
    lats, lons = ds.latitude.values, ds.longitude.values
    meta = None
    rm = os.path.join(BASE, "celdas_galicia.csv")
    if os.path.exists(rm):
        meta = pd.read_csv(rm)
        meta["clave"] = meta.lat.round(2).astype(str) + "_" + meta.lon.round(2).astype(str)
        meta = meta.set_index("clave")

    VARS = [("tmax", "temperatura maxima"), ("wb_max", "bulbo humedo"),
            ("at_max", "temperatura aparente"), ("hx_max", "humidex")]
    disp = [(v, e) for v, e in VARS if v in ds]
    print(f"malla: {len(lats)}x{len(lons)} celdas, variables {[v for v, _ in disp]}")

    filas = []
    datos = {v: ds[v].values for v, _ in disp}
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            if np.isnan(datos["tmax"][:, i, j]).mean() > 0.2:
                continue
            clave = f"{round(float(la), 2)}_{round(float(lo), 2)}"
            if meta is not None and clave not in meta.index:
                continue
            for v, etq in disp:
                serie = pd.Series(datos[v][:, i, j], index=tiempo)
                anuales = serie.groupby(serie.index.year).max()
                # solo anios con datos suficientes
                cuenta = serie.groupby(serie.index.year).count()
                anuales = anuales[cuenta >= 300]
                r = analiza(anuales, etq, semilla=i * 1000 + j)
                if r is None:
                    continue
                r["lat"], r["lon"] = round(float(la), 2), round(float(lo), 2)
                if meta is not None:
                    r["provincia"] = meta.loc[clave, "provincia"]
                    r["dist_costa_km"] = meta.loc[clave, "dist_costa_km"]
                filas.append(r)
    if not filas:
        return None
    d = pd.DataFrame(filas)
    d.to_csv(os.path.join(BASE, "retorno_malla.csv"), index=False, encoding="utf-8")
    print(f"retorno_malla.csv: {len(d)} filas "
          f"({d.lat.nunique() * d.lon.nunique()} celdas x {d.serie.nunique()} variables)")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-estaciones", action="store_true")
    args = ap.parse_args()

    est = desde_estaciones()
    malla = None if args.solo_estaciones else desde_malla()

    with open(os.path.join(BASE, "resumen_retorno.txt"), "w", encoding="utf-8") as fh:
        def p(*a):
            print(*a)
            print(*a, file=fh)

        p("PERIODOS DE RETORNO DE LA TEMPERATURA MAXIMA")
        p("=" * 60)
        if est is not None and "ns_tendencia_dec" in est:
            reg = tendencia_regional(est.ns_tendencia_dec.values)
            if reg:
                p("\nTENDENCIA REGIONAL DE LAS MAXIMAS ANUALES")
                p(f"  media de {reg['n']} puntos: {reg['media']:+.3f} C/decada")
                p(f"  intervalo del 95 %: {reg['ic95'][0]:+.3f} a {reg['ic95'][1]:+.3f}")
                p(f"  dispersion entre puntos: {reg['desv']:.3f} C/decada")
                sig = est.ns_significativa.mean() * 100 if "ns_significativa" in est else 0
                p(f"\n  Solo en el {sig:.0f} % de los puntos la tendencia es")
                p("  significativa por si sola. Eso NO significa que no exista: con 17")
                p("  o 30 maximas anuales el ruido casi iguala a la senial, y el")
                p("  contraste individual carece de potencia. La media regional, en")
                p("  cambio, tiene un error tipico varias veces menor y es la cifra")
                p("  que conviene usar para proyectar.")
                if reg["ic95"][0] > 0:
                    p("  El intervalo regional excluye el cero: el calentamiento de los")
                    p("  extremos si es detectable al agrupar.")

        if est is not None:
            n = int(est.n_anios.median())
            p(f"\nEstaciones: {len(est)}, mediana de {n} anios de registro.")
            p(f"AVISO: con {n} anios, el nivel a 20 anios es solido y el de 50 es")
            p("orientativo. Extrapolar mas de 2 o 3 veces la longitud del registro")
            p("no esta respaldado por los datos.")
            cols = [c for c in ("concello", "provincia", "alt", "max_observada",
                                "retorno_10a", "retorno_20a", "retorno_20a_p5",
                                "retorno_20a_p95", "retorno_50a", "desplazamiento")
                    if c in est]
            p("\n--- 15 estaciones con el extremo a 20 anios mas bajo ---")
            p(est.nsmallest(15, "retorno_20a")[cols].to_string(index=False))
            p("\n--- 10 con el extremo mas alto ---")
            p(est.nlargest(10, "retorno_20a")[cols].to_string(index=False))
            anchura = (est.retorno_20a_p95 - est.retorno_20a_p5).median()
            p(f"\nAnchura mediana del intervalo del 90 % a 20 anios: {anchura:.1f} C.")
            p("Esa es la incertidumbre real de estas cifras; si dos sitios difieren")
            p("menos que eso, no se pueden separar con este registro.")
            if "sesgo_estacionario" in est:
                b = est.sesgo_estacionario.dropna()
                p(f"\nSESGO DEL MODELO ESTACIONARIO")
                p(f"  El nivel a 20 anios evaluado en 2026 con el modelo que")
                p(f"  incorpora tendencia es {b.median():+.2f} C distinto del que sale")
                p(f"  suponiendo clima quieto (mediana; rango {b.min():+.2f} a {b.max():+.2f}).")
                p("  Un valor positivo significa que el calculo estacionario")
                p("  SUBESTIMA el riesgo de hoy, que es lo esperable si el clima")
                p("  se ha calentado durante el registro.")
            if "p_superar_max_30a" in est:
                q = est.p_superar_max_30a.dropna()
                p(f"\nPROBABILIDAD DE BATIR EL RECORD ACTUAL EN 30 ANIOS (2026-2055)")
                p(f"  mediana {q.median():.2f}, rango {q.min():.2f} a {q.max():.2f}")
                p("  Esta es la cifra que corresponde a una decision de vivienda,")
                p("  y no el periodo de retorno: 'una vez cada 50 anios' suena raro,")
                p("  pero verlo alguna vez en 30 anios de ocupacion no lo es.")
            if "desplazamiento" in est:
                d = est.desplazamiento.dropna()
                p(f"\nNo estacionariedad: el nivel a 20 anios estimado solo con la")
                p(f"segunda mitad del registro es {d.median():+.2f} C distinto de la")
                p(f"estimacion completa (mediana; rango {d.min():+.2f} a {d.max():+.2f}).")
                p(f"En {(d > 0).mean() * 100:.0f} % de las estaciones el desplazamiento")
                p("es al alza, que es la firma esperable del calentamiento.")

        if malla is not None:
            p(f"\n\n--- malla ERA5-Land ---")
            for etq, g in malla.groupby("serie"):
                p(f"\n{etq}: retorno a 20 anios entre {g.retorno_20a.min():.1f} y "
                  f"{g.retorno_20a.max():.1f} C")
                cols = [c for c in ("lat", "lon", "provincia", "dist_costa_km",
                                    "retorno_20a", "retorno_50a") if c in g]
                p("  las 8 celdas mas benignas:")
                p(g.nsmallest(8, "retorno_20a")[cols].to_string(index=False))

    print("\nSube retorno_estaciones.csv, retorno_malla.csv y resumen_retorno.txt")


if __name__ == "__main__":
    main()
