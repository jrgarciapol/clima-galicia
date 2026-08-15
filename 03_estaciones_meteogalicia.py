"""PASO 3 - Red de estaciones de MeteoGalicia (observacion real, sin clave de API).

ERA5-Land da una malla homogenea de 9 km, pero es un modelo. Las ~150 estaciones
automaticas de MeteoGalicia son medidas reales y estan justo donde vive la gente,
asi que sirven para (a) validar la malla y (b) detectar microclimas que 9 km no ve.

Uso:
    python 03_estaciones_meteogalicia.py                 # desde 2005
    python 03_estaciones_meteogalicia.py --desde 2015    # mas rapido

Salidas:
    estaciones_lista.csv     inventario con coordenadas y altitud
    estaciones_diario.csv    serie diaria bruta
    indices_estaciones.csv   los mismos indices que la malla, por estacion
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import indices_punto  # noqa: E402

# GAL_BASE permite redirigir entradas y salidas a otro directorio.
# Lo usan las pruebas para no tocar jamas tus descargas reales.
BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
RAIZ = "https://servizos.meteogalicia.gal/mgrss/observacion"
LISTA = f"{RAIZ}/listaEstacionsMeteo.action"
DIARIO = f"{RAIZ}/datosDiariosEstacionsMeteo.action"

# Codigos de MeteoGalicia -> nombre interno
PARAMS = {
    "TA_MAX_1.5m": "tmax",
    "TA_MIN_1.5m": "tmin",
    "TA_AVG_1.5m": "tmean",
    "HR_AVG_1.5m": "hr",
    "HR_MAX_1.5m": "hrmax",
    "HR_MIN_1.5m": "hrmin",
}

SESION = requests.Session()
SESION.headers["User-Agent"] = "analisis-climatico-galicia/1.0"


def pide(url, params=None, intentos=4):
    for k in range(intentos):
        try:
            r = SESION.get(url, params=params, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            if k == intentos - 1:
                print(f"    fallo definitivo: {e}")
                return None
            time.sleep(4 * (k + 1))
    return None


def aplana(obj, salida, clave_padre=""):
    """Recorre el JSON de MeteoGalicia, que anida listas de estaciones y medidas."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            aplana(v, salida, k)
    elif isinstance(obj, list):
        for v in obj:
            aplana(v, salida, clave_padre)
    return salida


def descarga_lista():
    j = pide(LISTA)
    if not j:
        sys.exit("No se pudo obtener la lista de estaciones.")
    filas = []

    def rec(o):
        if isinstance(o, dict):
            if "idEstacion" in o or "idEst" in o:
                filas.append(o)
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(j)
    df = pd.json_normalize(filas)
    ren = {}
    for c in df.columns:
        cl = c.lower()
        if cl.endswith("idestacion") or cl.endswith("idest"):
            ren[c] = "id"
        elif "nome" in cl or "nombre" in cl:
            ren.setdefault(c, "nombre")
        elif cl.endswith("lat") or "latitud" in cl:
            ren[c] = "lat"
        elif cl.endswith("lon") or "lonxitud" in cl or "longitud" in cl:
            ren[c] = "lon"
        elif "altitude" in cl or "altitud" in cl:
            ren[c] = "alt"
        elif "concello" in cl:
            ren[c] = "concello"
        elif "provincia" in cl:
            ren[c] = "provincia"
    df = df.rename(columns=ren)
    cols = [c for c in ("id", "nombre", "concello", "provincia", "lat", "lon", "alt") if c in df]
    df = df[cols].drop_duplicates(subset="id")
    for c in ("lat", "lon", "alt"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def descarga_estacion(idest, anio_ini, anio_fin):
    trozos = []
    for a in range(anio_ini, anio_fin + 1):
        fin = min(date(a, 12, 31), date.today())
        if date(a, 1, 1) > date.today():
            break
        j = pide(DIARIO, {
            "idEst": str(idest),
            "idParam": ",".join(PARAMS),
            "dataIni": f"01/01/{a}",
            "dataFin": fin.strftime("%d/%m/%Y"),
        })
        if not j:
            continue
        regs = []

        def rec(o, fecha=None):
            if isinstance(o, dict):
                f = o.get("data") or o.get("dataInstante") or o.get("fecha") or fecha
                if "codigoParametro" in o or "codeParameter" in o:
                    cod = o.get("codigoParametro") or o.get("codeParameter")
                    val = o.get("valor") if "valor" in o else o.get("value")
                    regs.append((f, cod, val))
                for v in o.values():
                    rec(v, f)
            elif isinstance(o, list):
                for v in o:
                    rec(v, fecha)

        rec(j)
        if regs:
            trozos.append(pd.DataFrame(regs, columns=["fecha", "cod", "valor"]))
        time.sleep(0.25)

    if not trozos:
        return None
    d = pd.concat(trozos, ignore_index=True)
    d["fecha"] = pd.to_datetime(d.fecha.astype(str).str[:10], errors="coerce")
    d["valor"] = pd.to_numeric(d.valor, errors="coerce")
    d = d.dropna(subset=["fecha"])
    d["var"] = d.cod.map(PARAMS)
    d = d.dropna(subset=["var"])
    piv = d.pivot_table(index="fecha", columns="var", values="valor", aggfunc="mean")
    # MeteoGalicia marca los ausentes con valores centinela muy negativos
    return piv.where(piv > -50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2005)
    ap.add_argument("--hasta", type=int, default=date.today().year)
    args = ap.parse_args()

    est = descarga_lista()
    est.to_csv(os.path.join(BASE, "estaciones_lista.csv"), index=False)
    print(f"{len(est)} estaciones en el inventario")

    todo, indices = [], []
    for n, (_, e) in enumerate(est.iterrows(), 1):
        print(f"[{n}/{len(est)}] {e.get('nombre', e['id'])} ...", flush=True)
        piv = descarga_estacion(e["id"], args.desde, args.hasta)
        if piv is None or "tmax" not in piv or piv["tmax"].notna().sum() < 700:
            print("    sin serie util")
            continue
        piv = piv.copy()
        piv["estacion"] = e["id"]
        todo.append(piv.reset_index())

        df = piv[["tmax", "tmin"]].copy()
        if "tmean" in piv:
            df["tmean"] = piv["tmean"]
        if "hr" in piv:
            # punto de rocio a partir de T y HR (inversa de Magnus)
            import numpy as np
            hr = piv["hr"].clip(1, 100) / 100.0
            g = np.log(hr) + 17.67 * piv["tmax"] / (piv["tmax"] + 243.5)
            df["td"] = 243.5 * g / (17.67 - g)
        df = df.dropna(subset=["tmax", "tmin"])
        ind = indices_punto(df)
        if ind:
            ind.update({k: e.get(k) for k in ("id", "nombre", "concello", "provincia",
                                              "lat", "lon", "alt") if k in e})
            indices.append(ind)
            print(f"    ok  {ind['n_anios']} anios,  d_tx32={ind['d_tx32']:.1f}/anio")

    if todo:
        pd.concat(todo, ignore_index=True).to_csv(
            os.path.join(BASE, "estaciones_diario.csv"), index=False)
    if indices:
        di = pd.DataFrame(indices)
        primeras = [c for c in ("id", "nombre", "concello", "provincia", "lat", "lon", "alt")
                    if c in di]
        di = di[primeras + [c for c in di.columns if c not in primeras]]
        di.sort_values("d_tx32").to_csv(os.path.join(BASE, "indices_estaciones.csv"), index=False)
        print(f"\nindices_estaciones.csv: {len(di)} estaciones")


if __name__ == "__main__":
    main()
