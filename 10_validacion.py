"""PASO 10 - Contraste del campo fusionado contra las estaciones reales.

Hasta aqui todo sale de dos modelos: un reanalisis (ERA5-Land) y una prediccion
(WRF). Ninguno de los dos ha visto un termometro de Galicia. Este paso los
enfrenta a las 153 estaciones de MeteoGalicia, que son observaciones.

Responde a tres preguntas, en este orden:

  1. ¿Acierta en valor absoluto?  Si no, cuanto se desvia y hacia donde.
  2. ¿Ordena bien los sitios?     Que es lo unico que necesita esta decision.
  3. ¿Ha servido de algo el WRF?  Comparando la fusion de 1 km contra el
     ERA5-Land de 9 km sin corregir. Si no mejora, el paso 5 fue trabajo tirado.

La distincion importa: para elegir donde vivir da igual que todo el campo este
2 C bajo si esta 2 C bajo en todas partes por igual; lo que no da igual es que
se equivoque de sitio.

Uso:  python 10_validacion.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
MIN_ANIOS = 8       # anios de serie para que una estacion cuente
MAX_DIST_KM = 3.0   # distancia maxima al punto de malla mas cercano


def cerca(destino_lat, destino_lon, origen):
    """Indice del punto de `origen` mas proximo a cada destino, y la distancia."""
    from scipy.spatial import cKDTree

    arb = cKDTree(origen[["lon", "lat"]].values)
    dist, idx = arb.query(np.column_stack([destino_lon, destino_lat]))
    return idx, dist * 100.0   # grados -> km, aproximado


def main():
    ruta_alta = os.path.join(BASE, "alta_resolucion.csv.gz")
    ruta_est = os.path.join(BASE, "indices_estaciones.csv")
    ruta_era = os.path.join(BASE, "indices_galicia.csv")
    for r in (ruta_alta, ruta_est):
        if not os.path.exists(r):
            sys.exit(f"Falta {os.path.basename(r)}.")

    alta = pd.read_csv(ruta_alta)
    est = pd.read_csv(ruta_est)
    col = "tx_p99_1km" if "tx_p99_1km" in alta else "wrf_tx_p90"

    campo = alta[alta.get("tierra", 1) == 1]
    if "sospechoso" in campo:
        campo = campo[campo.sospechoso == 0]
    campo = campo.dropna(subset=[col])

    idx, dist = cerca(est.lat.values, est.lon.values, campo)
    est["fusion"] = campo[col].values[idx]
    est["alt_modelo"] = campo.altitud.values[idx] if "altitud" in campo else np.nan
    est["dist_km"] = dist

    e = est[(est.n_anios >= MIN_ANIOS) & (est.dist_km < MAX_DIST_KM)].copy()
    if len(e) < 20:
        sys.exit(f"Solo {len(e)} estaciones utilizables; no da para validar.")
    e["error"] = e.fusion - e.tx_p99

    lineas = []

    def p(*a):
        print(*a)
        lineas.append(" ".join(str(x) for x in a))

    p(f"Estaciones utilizables: {len(e)} de {len(est)} "
      f"(>= {MIN_ANIOS} anios y a menos de {MAX_DIST_KM:.0f} km de la malla)")
    p(f"Variable contrastada: {col} frente al tx_p99 observado")

    p("\n--- 1. valor absoluto ---")
    p(f"  sesgo medio      {e.error.mean():+6.2f} C")
    p(f"  error absoluto   {e.error.abs().mean():6.2f} C")
    p(f"  desviacion       {e.error.std():6.2f} C")
    if e.error.mean() < -0.5:
        p("  El campo va FRIO. Es lo esperable: una celda de reanalisis es una")
        p("  media de area y las medias de area no alcanzan los extremos de un")
        p("  punto. No invalida el ranking, pero estos numeros NO son lecturas")
        p("  de termometro.")

    # parte del error que es simple desajuste de altitud: la topografia del
    # modelo a 1 km no coincide exactamente con la de la garita
    if e.alt_modelo.notna().all():
        e["dif_alt"] = e.alt_modelo - e.alt
        b = np.polyfit(e.dif_alt, e.error, 1)
        resid = e.error - np.polyval(b, e.dif_alt)
        p(f"\n  del error, lo que explica el desajuste de altitud modelo-garita:")
        p(f"    pendiente {b[0] * 1000:+.2f} C / 1000 m "
          f"(el gradiente fisico es -6.5)")
        p(f"    sesgo del campo a igualdad de altitud: {b[1]:+.2f} C")
        p(f"    error absoluto tras corregirlo: {resid.abs().mean():.2f} C "
          f"(antes {e.error.abs().mean():.2f})")
        p(f"  -> correccion recomendada para leer el campo en grados reales: "
          f"{-b[1]:+.2f} C")

    p("\n--- 2. ¿ordena bien? (que es lo que importa) ---")
    rho = e.fusion.rank().corr(e.tx_p99.rank(), method="spearman")
    r = np.corrcoef(e.fusion, e.tx_p99)[0, 1]
    p(f"  correlacion de rangos (Spearman): {rho:.3f}")
    p(f"  correlacion de Pearson:           {r:.3f}")
    # la prueba practica: de las 15 estaciones realmente mas frescas, cuantas
    # estan entre las 15 que el campo senala como mas frescas
    n = 15
    reales = set(e.nsmallest(n, "tx_p99").id)
    dichas = set(e.nsmallest(n, "fusion").id)
    p(f"  de las {n} estaciones mas frescas de verdad, el campo acierta "
      f"{len(reales & dichas)}")
    reales_c = set(e.nlargest(n, "tx_p99").id)
    dichas_c = set(e.nlargest(n, "fusion").id)
    p(f"  de las {n} mas calurosas de verdad, acierta {len(reales_c & dichas_c)}")

    p("\n--- 3. ¿ha servido de algo bajar a 1 km? ---")
    if os.path.exists(ruta_era):
        from scipy.interpolate import griddata

        era = pd.read_csv(ruta_era)
        if "tx_p99" in era:
            e["era9"] = griddata(era[["lon", "lat"]].values, era.tx_p99.values,
                                 (e.lon.values, e.lat.values), method="linear")
            g = e.dropna(subset=["era9"])
            p(f"  sobre las {len(g)} estaciones donde ERA5-Land interpola de verdad:")
            for nom, c in (("ERA5-Land 9 km", "era9"), ("fusion 1 km", "fusion")):
                err = g[c] - g.tx_p99
                p(f"    {nom:16s} error abs {err.abs().mean():4.2f} C   "
                  f"corr {np.corrcoef(g[c], g.tx_p99)[0, 1]:.3f}   "
                  f"rangos {g[c].rank().corr(g.tx_p99.rank(), method='spearman'):.3f}")
            mejora = ((g.era9 - g.tx_p99).abs().mean()
                      - (g.fusion - g.tx_p99).abs().mean())
            p(f"  -> el detalle de 1 km {'mejora' if mejora > 0 else 'EMPEORA'} "
              f"el error en {abs(mejora):.2f} C")

            # donde ERA5-Land no tiene tierra alrededor, el paso 6 completo con
            # el vecino mas proximo: ahi el campo es mas debil, y son justo los
            # puntos de litoral que encabezan el ranking
            fuera = e[e.era9.isna()] if "era9" in e else e.iloc[:0]
            if len(fuera) >= 3:
                p(f"\n  ATENCION: {len(fuera)} estaciones caen fuera de la nube de")
                p(f"  ERA5-Land (litoral y cabos). Ahi el error absoluto es "
                  f"{(fuera.fusion - fuera.tx_p99).abs().mean():.2f} C frente a "
                  f"{(g.fusion - g.tx_p99).abs().mean():.2f} C dentro.")
                p("  Es la parte mas debil del metodo, y coincide con la cabeza")
                p("  del ranking: los cabos mas frescos son tambien los peor")
                p("  respaldados por observaciones.")

    p("\n--- las 12 estaciones donde mas se equivoca ---")
    cols = ["concello", "provincia", "alt", "alt_modelo", "tx_p99", "fusion", "error"]
    p(e.reindex(e.error.abs().sort_values(ascending=False).index)
      .head(12)[cols].round(1).to_string(index=False))

    e.to_csv(os.path.join(BASE, "validacion_estaciones.csv"), index=False,
             encoding="utf-8")
    with open(os.path.join(BASE, "resumen_validacion.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")
    print("\nEscritos validacion_estaciones.csv y resumen_validacion.txt")


if __name__ == "__main__":
    main()
