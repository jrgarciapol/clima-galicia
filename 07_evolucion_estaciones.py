"""PASO 7 - Evolucion temporal de cada estacion: la curva, no la media.

Los indices del paso 3 son medias de 17 anios. Eso esconde justo lo que importa
en un contexto de cambio climatico: si un sitio esta empeorando deprisa, su media
lo disimula. Este paso descompone cada indice anio a anio.

No descarga nada: reutiliza estaciones_diario.csv, que ya escribio el paso 3.

Metodo
------
Para cada estacion y cada anio con al menos 300 dias validos se recalculan los
indices. Sobre esa serie anual se aplica:

  - **Pendiente de Sen** en vez de minimos cuadrados. Con 17 puntos, un solo
    verano extremo (2022, por ejemplo) inclina una recta de regresion de forma
    desproporcionada. La pendiente de Sen es la mediana de las pendientes entre
    todos los pares de puntos: un anio anomalo no la mueve.
  - **Test de Mann-Kendall** (tau de Kendall) para saber si la tendencia se
    distingue del ruido. Con 17 anios y la variabilidad interanual gallega,
    muchas estaciones NO daran una tendencia significativa, y eso es un
    resultado honesto, no un fallo.
  - **Salto** entre la primera y la segunda mitad del periodo, que es mas facil
    de interpretar que una pendiente.

Ademas comprueba si el **ranking** entre estaciones se mantiene: si los sitios
frescos siguen siendo los mismos, la decision es robusta aunque todo se caliente.

Uso:  python 07_evolucion_estaciones.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import humedad_relativa, humidex  # noqa: E402

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
MIN_DIAS = 300      # dias validos para dar un anio por bueno
MIN_ANIOS = 12      # anios para estimar una tendencia


def sen(x, y):
    """Pendiente de Sen: mediana de las pendientes entre todos los pares."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3:
        return np.nan
    i, j = np.triu_indices(n, 1)
    dx = x[j] - x[i]
    ok = dx != 0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def mann_kendall(x, y):
    """Devuelve (tau, p). Es el test estandar para tendencias climaticas cortas:
    no exige normalidad ni linealidad, solo monotonia."""
    from scipy.stats import kendalltau
    t, p = kendalltau(x, y)
    return float(t), float(p)


def indices_anio(sub):
    """Indices de un anio para una estacion."""
    tmax, tmin = sub.tmax.values, sub.tmin.values
    fuera = {
        "n_dias": len(sub),
        "d_tx30": float((tmax >= 30).sum()),
        "d_tx32": float((tmax >= 32).sum()),
        "d_tx35": float((tmax >= 35).sum()),
        "tx_p99": float(np.nanpercentile(tmax, 99)),
        "tx_max": float(np.nanmax(tmax)),
        "tx_verano": float(np.nanmean(tmax[sub.index.month.isin([6, 7, 8])])),
        "noches_trop": float((tmin >= 20).sum()),
        "tmean": float(np.nanmean((tmax + tmin) / 2)),
        "d_helada": float((tmin <= 0).sum()),
    }
    if "hr" in sub and sub.hr.notna().sum() > 300:
        hr = sub.hr.clip(1, 100) / 100.0
        g = np.log(hr) + 17.67 * sub.tmax / (sub.tmax + 243.5)
        td = 243.5 * g / (17.67 - g)
        hx = humidex(tmax, td.values)
        fuera["hx_p99"] = float(np.nanpercentile(hx, 99))
        fuera["d_hx35"] = float((hx >= 35).sum())
    return fuera


METRICAS = ["d_tx30", "d_tx32", "d_tx35", "tx_p99", "tx_verano", "noches_trop",
            "tmean", "d_helada", "hx_p99", "d_hx35"]


def main():
    ruta = os.path.join(BASE, "estaciones_diario.csv")
    if not os.path.exists(ruta):
        sys.exit("Falta estaciones_diario.csv. Ejecuta antes 03_estaciones_meteogalicia.py")

    print("Leyendo la serie diaria ...")
    d = pd.read_csv(ruta, parse_dates=["fecha"])
    lista = pd.read_csv(os.path.join(BASE, "estaciones_lista.csv"))
    print(f"  {len(d):,} filas, {d.estacion.nunique()} estaciones, "
          f"{d.fecha.dt.year.min()}-{d.fecha.dt.year.max()}")

    filas = []
    for est, g in d.groupby("estacion"):
        g = g.set_index("fecha").sort_index().dropna(subset=["tmax", "tmin"])
        for anio, sub in g.groupby(g.index.year):
            if len(sub) < MIN_DIAS:
                continue
            r = indices_anio(sub)
            r.update({"estacion": est, "anio": anio})
            filas.append(r)

    ev = pd.DataFrame(filas)
    ev = ev.merge(lista, left_on="estacion", right_on="id", how="left")
    ev.to_csv(os.path.join(BASE, "evolucion_estaciones.csv"), index=False, encoding="utf-8")
    print(f"\nevolucion_estaciones.csv: {len(ev):,} filas "
          f"({ev.estacion.nunique()} estaciones x anios)")

    # --- tendencia por estacion ---------------------------------------------
    tend = []
    for est, g in ev.groupby("estacion"):
        g = g.sort_values("anio")
        if len(g) < MIN_ANIOS:
            continue
        t = {"estacion": est, "n_anios": len(g),
             "anio_ini": int(g.anio.min()), "anio_fin": int(g.anio.max())}
        mitad = g.anio.median()
        for m in METRICAS:
            if m not in g or g[m].isna().all():
                continue
            sub = g.dropna(subset=[m])
            if len(sub) < MIN_ANIOS:
                continue
            t[f"{m}_sen_dec"] = round(sen(sub.anio, sub[m]) * 10, 3)
            tau, p = mann_kendall(sub.anio, sub[m])
            t[f"{m}_p"] = round(p, 4)
            t[f"{m}_salto"] = round(float(sub[sub.anio > mitad][m].mean()
                                          - sub[sub.anio <= mitad][m].mean()), 2)
        tend.append(t)

    td = pd.DataFrame(tend).merge(lista, left_on="estacion", right_on="id", how="left")
    td.to_csv(os.path.join(BASE, "tendencias_estaciones.csv"), index=False, encoding="utf-8")
    print(f"tendencias_estaciones.csv: {len(td)} estaciones")

    # --- resumen legible ------------------------------------------------------
    with open(os.path.join(BASE, "resumen_evolucion.txt"), "w", encoding="utf-8") as fh:
        def p(*a):
            print(*a)
            print(*a, file=fh)

        p(f"Periodo: {ev.anio.min()}-{ev.anio.max()}   estaciones: {len(td)}")
        p("\n--- tendencia mediana en Galicia (pendiente de Sen por decada) ---")
        p(f"{'metrica':14s} {'mediana':>9s} {'p10':>8s} {'p90':>8s} "
          f"{'% signif.':>10s}  {'% al alza':>10s}")
        for m in METRICAS:
            c, cp = f"{m}_sen_dec", f"{m}_p"
            if c not in td:
                continue
            v, pv = td[c].dropna(), td[cp].dropna()
            sig = (pv < 0.05).mean() * 100
            alza = (v > 0).mean() * 100
            p(f"{m:14s} {v.median():+9.2f} {v.quantile(.1):+8.2f} "
              f"{v.quantile(.9):+8.2f} {sig:9.0f}% {alza:10.0f}%")

        p("\n--- media de Galicia por anio ---")
        anual = ev.groupby("anio").agg(
            n=("estacion", "size"), tmean=("tmean", "mean"),
            tx_verano=("tx_verano", "mean"), d_tx30=("d_tx30", "mean"),
            d_tx32=("d_tx32", "mean"), noches_trop=("noches_trop", "mean")).round(2)
        p(anual.to_string())

        # --- estabilidad del ranking ----------------------------------------
        med = ev.anio.median()
        a = ev[ev.anio <= med].groupby("estacion").d_tx32.mean()
        b = ev[ev.anio > med].groupby("estacion").d_tx32.mean()
        j = pd.concat([a.rename("prim"), b.rename("seg")], axis=1).dropna()
        if len(j) > 20:
            rho = j.prim.rank().corr(j.seg.rank(), method="spearman")
            p(f"\n--- estabilidad del ranking (dias >32 C) ---")
            p(f"  correlacion de rangos entre {ev.anio.min()}-{med:.0f} y "
              f"{med + 1:.0f}-{ev.anio.max()}: {rho:.3f}")
            p("  (1.0 = el orden de los sitios no ha cambiado nada;")
            p("   si es alto, elegir por la media de 17 anios es una decision robusta)")
            j["cambio"] = j.seg.rank(pct=True) - j.prim.rank(pct=True)
            j = j.merge(lista.set_index("id")[["concello", "provincia"]],
                        left_index=True, right_index=True, how="left")
            p("\n  los que mas EMPEORAN en el ranking:")
            p(j.nlargest(8, "cambio")[["concello", "provincia", "prim", "seg", "cambio"]]
              .round(2).to_string())
            p("\n  los que mas MEJORAN en el ranking:")
            p(j.nsmallest(8, "cambio")[["concello", "provincia", "prim", "seg", "cambio"]]
              .round(2).to_string())

    print("\nSube evolucion_estaciones.csv, tendencias_estaciones.csv y "
          "resumen_evolucion.txt al repositorio.")


if __name__ == "__main__":
    main()
