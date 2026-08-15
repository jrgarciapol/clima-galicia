"""PASO 15 - Confort de verano en las estaciones, hoy y proyectado.

Que resuelve
------------
El informe tiene un hueco reconocido: las proyecciones climaticas publican
temperatura pero NINGUN indice de confort con humedad. Asi que la mitad del
criterio -- el bochorno -- estaba medida en el presente y sin futuro.

Este paso cierra ese hueco por la unica via honesta que existe con los datos
disponibles: coger la serie DIARIA real de cada estacion, sumarle la anomalia
de temperatura que proyectan los modelos, y recalcular el humidex dia a dia.
No inventa humedad futura: la mantiene, y hace explicito que "mantener la
humedad" significa dos cosas distintas que dan resultados muy distintos.

Las dos hipotesis, y por que hacen falta las dos
------------------------------------------------
El humidex es  hx = T + 0,5555 * (e - 10),  donde `e` es la presion de vapor.

  A) PUNTO DE ROCIO CONSTANTE (humedad absoluta fija).
     El aire lleva la misma cantidad de agua que hoy. `e` no cambia, asi que
     el humidex sube EXACTAMENTE lo mismo que la temperatura.
     Es la hipotesis conservadora, la cota inferior.

  B) HUMEDAD RELATIVA CONSTANTE.
     El aire mantiene el mismo porcentaje de saturacion. Como el aire caliente
     admite mas vapor (Clausius-Clapeyron, ~7 % por grado), `e` sube y el
     humidex sube MAS que la temperatura, tipicamente el doble.
     Es la cota superior.

Ninguna de las dos es "la verdad". La fisica dice que sobre el oceano la
humedad relativa se conserva bastante -- hay agua infinita debajo -- y que
sobre tierra adentro tiende a bajar al calentarse, porque el suelo se seca.
Es decir: la costa gallega se parecera mas a (B) y el interior mas a (A).
Publicar solo una de las dos seria elegir el resultado.

Por que el umbral de 35 en el humidex
-------------------------------------
La escala de Environment Canada, que es quien define el indice:
    por debajo de 30   sin molestia
    30 a 39            molestia notable
    40 a 45            fuerte malestar, conviene evitar el esfuerzo
    por encima de 45   peligro, riesgo de golpe de calor
35 es el centro de la banda de molestia: el punto en que un dia deja de ser
simplemente caluroso y pasa a condicionar lo que se hace con el. Se cuentan
tambien 30 y 40 para poder ver la curva entera, no un solo corte.

Uso:
    python 15_confort.py
    python 15_confort.py --escenario ssp245 --periodo medium_future

Necesita en la carpeta: estaciones_diario.csv (lo genera el paso 3),
estaciones_lista.csv, indices_estaciones.csv y proyecciones_galicia.csv.gz
(paso 9).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import humidex, humedad_relativa, percentil_calendario, rachas  # noqa: E402

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
ESCENARIOS = ("ssp126", "ssp245", "ssp370", "ssp585")
PERIODOS = ("near_future", "medium_future", "far_future")
UMBRALES_HX = (30, 35, 40)
BASE_CDD = 18.0          # grados-dia de refrigeracion: grados por encima de 18 C


def presion_vapor(td):
    return 6.112 * np.exp((17.67 * td) / (td + 243.5))


def rocio_desde_hr(t, hr):
    """Punto de rocio a partir de temperatura y humedad relativa (Magnus inversa)."""
    h = np.clip(np.asarray(hr, dtype=float), 1, 100) / 100.0
    g = np.log(h) + 17.67 * t / (t + 243.5)
    return 243.5 * g / (17.67 - g)


# ---------------------------------------------------------------------------
def indices(tmax, tmin, tmed, td, fechas, n_anios):
    """Los seis factores del ranking, para una serie diaria cualquiera."""
    o = {}
    o["tx_p99"] = float(np.nanpercentile(tmax, 99))
    o["d_tx30"] = float(np.nansum(tmax >= 30)) / n_anios
    o["noches_trop"] = float(np.nansum(tmin >= 20)) / n_anios

    # grados-dia de refrigeracion: cuanto y cuanto tiempo se pasa de 18 C
    o["cdd"] = float(np.nansum(np.clip(tmed - BASE_CDD, 0, None))) / n_anios

    # ola de calor: rachas de 3 dias o mas por encima del percentil 95 del
    # propio calendario. El umbral es local a proposito: una ola es un episodio
    # anomalo PARA ESE SITIO, no un valor absoluto igual en toda Galicia.
    umbral = percentil_calendario(fechas, tmax, ventana=15, q=95).values
    ola = tmax > umbral
    _, dias = rachas(ola, min_len=3)
    o["ola_dias"] = dias / n_anios
    o["ola_max"] = float(max(_rachas_largo(ola), default=0))

    if td is not None:
        hx = humidex(tmax, td)
        o["hx_p99"] = float(np.nanpercentile(hx, 99))
        for u in UMBRALES_HX:
            o[f"d_hx{u}"] = float(np.nansum(hx >= u)) / n_anios
        o["hr_verano"] = float(np.nanmean(
            humedad_relativa(tmax, td)[np.isin(fechas.month, [6, 7, 8])]))
    return o


def _rachas_largo(mask):
    """Longitudes de todas las rachas de True. Para la ola mas larga."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return []
    d = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
    return list(np.flatnonzero(d == -1) - np.flatnonzero(d == 1))


# ---------------------------------------------------------------------------
def anomalias_por_estacion(est):
    """Anomalia de tasmaxp99 y de tmean para cada estacion, por celda mas proxima.

    Union en 2D y solo entre celdas que existen: buscar la latitud y la
    longitud mas parecidas por separado deja sin dato a las estaciones
    costeras, porque ese par cae sobre mar. Es el fallo que ya costo 31 puntos
    en el paso 9.
    """
    ruta = os.path.join(BASE, "proyecciones_galicia.csv.gz")
    if not os.path.exists(ruta):
        sys.exit(f"Falta {ruta}. Ejecuta antes: python 09_proyecciones.py --analizar")
    p = pd.read_csv(ruta)
    an = p[(p.tipo == "anom") & (p.filtro == "JJA")]
    k = np.cos(np.radians(float(est.lat.mean())))
    salida = {}
    for var in ("tasmaxp99", "tmean"):
        for e in ESCENARIOS:
            for per in PERIODOS:
                g = an[(an.variable == var) & (an.escenario == e) & (an.periodo == per)]
                if g.empty:
                    continue
                cl = g.groupby(["lat", "lon"]).valor.mean().reset_index()
                d = np.hypot(est.lat.values[:, None] - cl.lat.values[None, :],
                             (est.lon.values[:, None] - cl.lon.values[None, :]) * k)
                i = d.argmin(1)
                salida[(var, e, per)] = cl.valor.values[i]
                salida[("_km", e, per)] = d[np.arange(len(est)), i] * 111
    return salida


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minimo-anios", type=int, default=8)
    a = ap.parse_args()

    rd = os.path.join(BASE, "estaciones_diario.csv")
    if not os.path.exists(rd):
        sys.exit(f"Falta {rd}. Lo genera el paso 3:\n"
                 "  python 03_estaciones_meteogalicia.py --desde 2010")
    print(f"Leyendo {os.path.getsize(rd)/1e6:.0f} MB de serie diaria...", flush=True)
    d = pd.read_csv(rd, parse_dates=["fecha"])
    est = pd.read_csv(os.path.join(BASE, "estaciones_lista.csv"))
    est = est[est.id.isin(d.estacion.unique())].reset_index(drop=True)
    print(f"{len(d):,} registros de {d.estacion.nunique()} estaciones")
    if "hr" not in d.columns:
        print("AVISO: la serie no trae humedad relativa. Sin ella no hay humidex\n"
              "       y este paso pierde su motivo. Revisa el paso 3.")

    print("\nAnomalias proyectadas por estacion...", flush=True)
    anom = anomalias_por_estacion(est)
    km = anom[("_km", "ssp245", "medium_future")]
    print(f"  celda de 5 km mas proxima: mediana {np.median(km):.1f} km, "
          f"maxima {km.max():.1f} km")

    filas, saltadas = [], 0
    for n, (_, e) in enumerate(est.iterrows(), 1):
        g = d[d.estacion == e.id].set_index("fecha").sort_index()
        g = g.dropna(subset=["tmax", "tmin"])
        n_anios = g.index.year.nunique()
        if n_anios < a.minimo_anios:
            saltadas += 1
            continue
        tmax = g.tmax.values.astype(float)
        tmin = g.tmin.values.astype(float)
        tmed = (g.tmean.values.astype(float) if "tmean" in g and g.tmean.notna().any()
                else (tmax + tmin) / 2.0)
        td = rocio_desde_hr(tmax, g.hr.values) if "hr" in g and g.hr.notna().any() else None
        hoy = indices(tmax, tmin, tmed, td, g.index, n_anios)
        base = {"id": int(e.id), "concello": e.get("concello", ""),
                "provincia": e.get("provincia", ""), "lat": e.lat, "lon": e.lon,
                "alt": e.get("alt", np.nan), "n_anios": n_anios}
        filas.append({**base, "escenario": "-", "periodo": "hoy",
                      "hipotesis": "medido", **hoy})

        if td is None:
            continue
        rh = humedad_relativa(tmax, td)          # la de hoy, dia a dia
        for esc in ESCENARIOS:
            for per in PERIODOS:
                if ("tasmaxp99", esc, per) not in anom:
                    continue
                dtx = float(anom[("tasmaxp99", esc, per)][n - 1])
                dtm = float(anom[("tmean", esc, per)][n - 1])
                tmax_f = tmax + dtx
                tmin_f = tmin + dtm            # el tmin no tiene anomalia propia
                tmed_f = tmed + dtm
                # A) el aire lleva la misma agua: el rocio no se mueve
                fa = indices(tmax_f, tmin_f, tmed_f, td, g.index, n_anios)
                # B) el aire mantiene el mismo % de saturacion: el rocio sube
                td_b = rocio_desde_hr(tmax_f, rh)
                fb = indices(tmax_f, tmin_f, tmed_f, td_b, g.index, n_anios)
                for et, f in (("rocio_fijo", fa), ("hr_fija", fb)):
                    filas.append({**base, "escenario": esc, "periodo": per,
                                  "hipotesis": et, "d_tx": round(dtx, 3),
                                  "d_tmean": round(dtm, 3), **f})
        if n % 25 == 0:
            print(f"  [{n}/{len(est)}] {e.get('concello','')}", flush=True)

    t = pd.DataFrame(filas)
    salida = os.path.join(BASE, "confort_estaciones.csv")
    t.round(3).to_csv(salida, index=False)
    print(f"\n{len(t):,} filas -> {os.path.basename(salida)} "
          f"({t.id.nunique()} estaciones, {saltadas} descartadas por serie corta)")

    # ------------------------------------------------------------------ informe
    L = [f"Confort de verano en las estaciones - {datetime.now():%Y-%m-%d %H:%M}", ""]
    h = t[t.periodo == "hoy"]
    L.append(f"{len(h)} estaciones con {a.minimo_anios}+ anios de serie diaria.")
    L.append("")
    L.append("=== HOY, medido ===")
    for c, et in (("tx_p99", "percentil 99 de la maxima"),
                  ("hx_p99", "percentil 99 del humidex"),
                  ("d_hx35", "dias con humidex > 35"),
                  ("cdd", "grados-dia de refrigeracion"),
                  ("ola_max", "ola de calor mas larga (dias)"),
                  ("noches_trop", "noches tropicales al anio")):
        if c in h:
            L.append(f"  {et:34s} {h[c].min():7.1f} a {h[c].max():7.1f}  "
                     f"(mediana {h[c].median():6.1f})")
    if "hx_p99" in h:
        L.append("")
        L.append("  los cinco mas llevaderos por humidex p99:")
        for _, r in h.nsmallest(5, "hx_p99").iterrows():
            L.append(f"    {str(r.concello)[:22]:22s} hx {r.hx_p99:5.1f}  "
                     f"dias>35 {r.d_hx35:6.1f}  cdd {r.cdd:6.0f}")
        L.append("  los cinco peores:")
        for _, r in h.nlargest(5, "hx_p99").iterrows():
            L.append(f"    {str(r.concello)[:22]:22s} hx {r.hx_p99:5.1f}  "
                     f"dias>35 {r.d_hx35:6.1f}  cdd {r.cdd:6.0f}")

    f = t[(t.escenario == "ssp245") & (t.periodo == "medium_future")]
    if not f.empty:
        L.append("")
        L.append("=== 2041-2070, SSP2-4.5: las dos hipotesis de humedad ===")
        L.append("La temperatura sube lo que dicen los modelos. La humedad no se")
        L.append("proyecta: se mantiene, y 'mantener' admite dos lecturas.")
        L.append("")
        for et, nom in (("rocio_fijo", "A) punto de rocio constante (cota inferior)"),
                        ("hr_fija", "B) humedad relativa constante (cota superior)")):
            z = f[f.hipotesis == et]
            if z.empty:
                continue
            j = h.set_index("id")
            sube_hx = (z.set_index("id").hx_p99 - j.hx_p99).dropna()
            sube_d = (z.set_index("id").d_hx35 - j.d_hx35).dropna()
            L.append(f"  {nom}")
            L.append(f"    humidex p99 sube  {sube_hx.min():+5.2f} a {sube_hx.max():+5.2f} "
                     f"(mediana {sube_hx.median():+5.2f})")
            L.append(f"    dias con humidex > 35 pasan de {j.d_hx35.median():.0f} a "
                     f"{z.d_hx35.median():.0f} al anio (mediana), {sube_d.median():+.0f}")
            L.append("")
        za, zb = f[f.hipotesis == "rocio_fijo"], f[f.hipotesis == "hr_fija"]
        if not za.empty and not zb.empty:
            dif = (zb.set_index("id").hx_p99 - za.set_index("id").hx_p99).median()
            L.append(f"  Entre las dos hipotesis hay {dif:.1f} C de humidex de diferencia.")
            L.append("  Esa horquilla NO es incertidumbre de los modelos: es lo que")
            L.append("  no sabemos sobre la humedad, y es mayor que la diferencia")
            L.append("  entre el escenario mas optimista y el mas pesimista.")

    texto = "\n".join(L)
    with open(os.path.join(BASE, "resumen_confort.txt"), "w", encoding="utf-8") as fh:
        fh.write(texto)
    print("\n" + texto)
    print("\nEscritos confort_estaciones.csv y resumen_confort.txt")


if __name__ == "__main__":
    main()
