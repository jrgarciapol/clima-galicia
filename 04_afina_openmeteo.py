"""PASO 4 (opcional) - Afinado de alta resolucion sobre la lista corta.

Hace dos cosas:

  A) Altitud real (modelo digital de 90 m) para las 366 celdas de la malla.
     Barato y rapido; permite interpretar por que una celda es mas fresca.

  B) Para las N celdas mejor clasificadas, vuelve a calcular los indices con la
     API de Open-Meteo, que aplica descenso de escala por altitud con un MDT de
     90 m sobre ERA5-Land. Es la unica forma barata de bajar de los 9 km a la
     escala de ladera / fondo de valle, que en Galicia es donde se juega todo.

Sin claves de API. Respeta el limite gratuito de Open-Meteo (10.000 llamadas/dia):
el script estima el coste y pide confirmacion antes de empezar.

Uso:
    python 04_afina_openmeteo.py --top 20
    python 04_afina_openmeteo.py --top 20 --desde 2006     # mas barato
    python 04_afina_openmeteo.py --solo-altitud
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import indices_punto  # noqa: E402

# GAL_BASE permite redirigir entradas y salidas a otro directorio.
# Lo usan las pruebas para no tocar jamas tus descargas reales.
BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
ELEV = "https://api.open-meteo.com/v1/elevation"
ARCHIVO = "https://archive-api.open-meteo.com/v1/archive"
VARS = ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
        "dew_point_2m_mean"]

S = requests.Session()
S.headers["User-Agent"] = "analisis-climatico-galicia/1.0"


def pide(url, params, intentos=5):
    for k in range(intentos):
        r = S.get(url, params=params, timeout=180)
        if r.status_code == 429:
            espera = 60 * (k + 1)
            print(f"    limite de peticiones alcanzado, espero {espera}s")
            time.sleep(espera)
            continue
        try:
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if k == intentos - 1:
                print(f"    fallo: {e}")
                return None
            time.sleep(5 * (k + 1))
    return None


def altitudes(df):
    out = []
    for i in range(0, len(df), 100):
        t = df.iloc[i:i + 100]
        j = pide(ELEV, {"latitude": ",".join(f"{v:.4f}" for v in t.lat),
                        "longitude": ",".join(f"{v:.4f}" for v in t.lon)})
        out.extend(j["elevation"] if j and "elevation" in j else [np.nan] * len(t))
        time.sleep(0.4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--desde", type=int, default=1996)
    ap.add_argument("--hasta", type=int, default=2025)
    ap.add_argument("--solo-altitud", action="store_true")
    ap.add_argument("--si", action="store_true", help="no preguntar")
    args = ap.parse_args()

    ruta = os.path.join(BASE, "indices_galicia.csv")
    if not os.path.exists(ruta):
        sys.exit("Falta indices_galicia.csv. Ejecuta antes 02_indices.py")
    res = pd.read_csv(ruta)

    # --- A) altitud de toda la malla ---------------------------------------
    print(f"Altitud (MDT 90 m) para {len(res)} celdas ...")
    res["altitud_m"] = np.round(altitudes(res), 0)
    res.to_csv(ruta, index=False)
    print(f"  hecho: {res.altitud_m.min():.0f} a {res.altitud_m.max():.0f} m")
    if args.solo_altitud:
        return

    # --- B) lista corta -----------------------------------------------------
    corta = res.nsmallest(args.top, "indice_calor").reset_index(drop=True)
    dias = (pd.Timestamp(f"{args.hasta}-12-31") - pd.Timestamp(f"{args.desde}-01-01")).days
    coste = args.top * (dias / 14) * (len(VARS) / 10)
    print(f"\nLista corta: {args.top} celdas, {args.desde}-{args.hasta}")
    print(f"Coste estimado: ~{coste:,.0f} llamadas del cupo gratuito (limite 10.000/dia)")
    if coste > 9000 and not args.si:
        print("Supera el cupo diario. Reduce --top o acorta --desde.")
        if input("Continuar de todas formas? [s/N] ").strip().lower() != "s":
            return

    filas = []
    for n, (_, c) in enumerate(corta.iterrows(), 1):
        print(f"[{n}/{len(corta)}] {c.lat},{c.lon} ({c.provincia}, {c.altitud_m:.0f} m) ...",
              flush=True)
        j = pide(ARCHIVO, {
            "latitude": c.lat, "longitude": c.lon,
            "start_date": f"{args.desde}-01-01", "end_date": f"{args.hasta}-12-31",
            "daily": ",".join(VARS), "timezone": "Europe/Madrid", "models": "era5_land",
        })
        if not j or "daily" not in j:
            continue
        d = j["daily"]
        df = pd.DataFrame({
            "tmax": d["temperature_2m_max"],
            "tmin": d["temperature_2m_min"],
            "tmean": d["temperature_2m_mean"],
            "td": d["dew_point_2m_mean"],
        }, index=pd.to_datetime(d["time"])).dropna(subset=["tmax", "tmin"])
        ind = indices_punto(df)
        if not ind:
            continue
        ind.update({"lat": c.lat, "lon": c.lon, "provincia": c.provincia,
                    "dist_costa_km": c.dist_costa_km,
                    "altitud_mdt": c.altitud_m,
                    "altitud_modelo": j.get("elevation")})
        filas.append(ind)
        time.sleep(1.0)

    if filas:
        d = pd.DataFrame(filas)
        pri = ["lat", "lon", "provincia", "altitud_mdt", "altitud_modelo", "dist_costa_km"]
        d = d[pri + [c for c in d.columns if c not in pri]]
        d.sort_values("d_tx32").to_csv(os.path.join(BASE, "lista_corta_afinada.csv"), index=False)
        print(f"\nlista_corta_afinada.csv: {len(d)} emplazamientos")


if __name__ == "__main__":
    main()
