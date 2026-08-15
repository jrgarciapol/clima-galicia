"""PASO 2 - De horario a diario, y de diario a indices y ranking.

Dos fases, con cache intermedia:

  A) Agregacion.  Lee los NetCDF horarios de descargas/ anio a anio y calcula,
     para cada celda y cada dia (en hora local, UTC+1):
        tmax, tmin, tmean          temperatura seca
        tmin_noche                 minima entre las 21 y las 9, para noches tropicales
        td                         punto de rocio medio
        hx_max                     maximo diario del humidex calculado hora a hora
        at_max                     idem para la temperatura aparente (con viento)
        viento                     media diaria del viento a 10 m
     El resultado se guarda en diarios_galicia.nc (unos 150 MB). Si ese fichero
     ya existe, esta fase se salta.

  B) Indices.  Sobre los diarios, calcula los ~45 indices por celda, las
     tendencias y el ranking.

Uso:
    python 02_indices.py
    python 02_indices.py --rehacer     # fuerza recalcular la agregacion
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import (bulbo_humedo, humedad_relativa, humidex,  # noqa: E402
                   indices_punto, temp_aparente)

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "descargas")
CACHE = os.path.join(BASE, "diarios_galicia.nc")

# ERA5-Land se publica en UTC. Espania peninsular va en UTC+1 (hora estandar);
# se usa un desfase fijo para no complicar el calculo con el cambio de hora,
# que a efectos de maximas y minimas diarias es irrelevante.
DESFASE_H = 1

DIARIAS = ["tmax", "tmin", "tmean", "tmin_noche", "td", "hx_max", "at_max",
           "wb_max", "viento"]


# ---------------------------------------------------------------------------
# Fase A: horario -> diario
# ---------------------------------------------------------------------------

def nombre_var(ds, candidatos):
    for c in candidatos:
        if c in ds:
            return c
    for v in ds.data_vars:
        if v.lower() in candidatos:
            return v
    return None


def agrega_fichero(ruta):
    """Devuelve un dict {variable_diaria: DataArray(time, lat, lon)}."""
    import xarray as xr

    ds = xr.open_dataset(ruta)
    dt = next((d for d in ("valid_time", "time", "forecast_time") if d in ds.dims), None)
    if dt is None:
        raise SystemExit(f"{ruta}: no encuentro la dimension temporal ({list(ds.dims)})")
    if dt != "time":
        ds = ds.rename({dt: "time"})

    n_t2 = nombre_var(ds, ["t2m", "2t", "t2"])
    n_d2 = nombre_var(ds, ["d2m", "2d"])
    n_u = nombre_var(ds, ["u10", "10u"])
    n_v = nombre_var(ds, ["v10", "10v"])
    if n_t2 is None:
        raise SystemExit(f"{ruta}: no encuentro la temperatura ({list(ds.data_vars)})")

    t = ds[n_t2]
    if float(t.max()) > 150:
        t = t - 273.15
    td = ds[n_d2] if n_d2 else None
    if td is not None and float(td.max()) > 150:
        td = td - 273.15

    if n_u and n_v:
        ws = np.sqrt(ds[n_u] ** 2 + ds[n_v] ** 2)
    else:
        ws = xr.zeros_like(t)

    # a hora local
    t = t.assign_coords(time=t.time + np.timedelta64(DESFASE_H, "h"))
    if td is not None:
        td = td.assign_coords(time=t.time)
    ws = ws.assign_coords(time=t.time)

    horas = pd.DatetimeIndex(t.time.values).hour
    dia = t.time.dt.floor("D")

    fuera = {}
    fuera["tmax"] = t.groupby(dia).max()
    fuera["tmin"] = t.groupby(dia).min()
    fuera["tmean"] = t.groupby(dia).mean()
    fuera["viento"] = ws.groupby(dia).mean()

    # El desfase a hora local deja un dia incompleto al principio y otro al
    # final de cada fichero. Una maxima calculada sobre una sola hora no es una
    # maxima diaria, asi que esos dias se descartan mas abajo.
    # Se cuenta sobre el indice temporal, no sobre los datos: contar la malla
    # entera multiplica el uso de memoria por el numero de celdas sin aportar
    # nada, porque la rejilla horaria es regular.
    idx = pd.DatetimeIndex(t.time.values)
    horas_por_dia = idx.normalize().value_counts()

    # noche = 21:00 a 09:00 hora local; se asigna al dia en que amanece
    es_noche = (horas >= 21) | (horas <= 9)
    dia_noche = (t.time - np.timedelta64(12, "h")).dt.floor("D") + np.timedelta64(1, "D")
    fuera["tmin_noche"] = t.where(xr.DataArray(es_noche, dims="time")).groupby(
        dia_noche.rename("time")).min()

    if td is not None:
        fuera["td"] = td.groupby(dia).mean()
        hx = xr.apply_ufunc(humidex, t, td, dask="parallelized")
        fuera["hx_max"] = hx.groupby(dia).max()
        at = xr.apply_ufunc(temp_aparente, t, td, ws, dask="parallelized")
        fuera["at_max"] = at.groupby(dia).max()
        # Bulbo humedo hora a hora: es el limite fisico del enfriamiento
        # corporal, y en un clima humedo dice cosas que la temperatura seca no.
        rh = xr.apply_ufunc(humedad_relativa, t, td, dask="parallelized")
        wb = xr.apply_ufunc(bulbo_humedo, t, rh, dask="parallelized")
        fuera["wb_max"] = wb.groupby(dia).max()

    for k in fuera:
        if "floor" in fuera[k].dims:
            fuera[k] = fuera[k].rename({"floor": "time"})

    malos = set(horas_por_dia[horas_por_dia < 20].index)
    if malos:
        for k in fuera:
            fechas = pd.DatetimeIndex(fuera[k].time.values)
            mascara = xr.DataArray(~fechas.isin(list(malos)), dims="time",
                                   coords={"time": fuera[k].time})
            fuera[k] = fuera[k].where(mascara)
        print(f"({len(malos)} dias incompletos descartados)", end=" ")
    return fuera


def construye_cache():
    import xarray as xr

    ficheros = sorted(glob.glob(os.path.join(DIR, "era5land_*.nc")))
    if not ficheros:
        sys.exit("No hay descargas/era5land_*.nc. Ejecuta antes 01_descarga_cds.py")

    print(f"Agregando {len(ficheros)} ficheros horarios a diarios ...")
    partes = []
    for n, f in enumerate(ficheros, 1):
        tam = os.path.getsize(f) / 1e6
        print(f"  [{n}/{len(ficheros)}] {os.path.basename(f)} ({tam:.0f} MB)",
              end=" ", flush=True)
        try:
            d = agrega_fichero(f)
        except Exception as e:  # noqa: BLE001
            print(f"ILEGIBLE ({e})")
            continue
        ds = xr.Dataset({k: v for k, v in d.items()})
        partes.append(ds)
        print(f"-> {ds.sizes.get('time', 0)} dias")

    if not partes:
        sys.exit("Ningun fichero utilizable.")
    todo = xr.concat(partes, dim="time").sortby("time").drop_duplicates("time")
    codif = {v: {"zlib": True, "complevel": 4, "dtype": "float32"} for v in todo.data_vars}
    todo.to_netcdf(CACHE, encoding=codif)
    print(f"\nGuardado {CACHE} ({os.path.getsize(CACHE) / 1e6:.0f} MB, "
          f"{todo.sizes['time']} dias)")
    return todo


# ---------------------------------------------------------------------------
# Fase B: indices
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rehacer", action="store_true")
    args = ap.parse_args()

    import xarray as xr

    if args.rehacer or not os.path.exists(CACHE):
        diario = construye_cache()
    else:
        print(f"Usando la cache {CACHE} (borrala o usa --rehacer para recalcular)")
        diario = xr.open_dataset(CACHE)

    lats = diario["latitude"].values
    lons = diario["longitude"].values
    tiempo = pd.DatetimeIndex(diario["time"].values).normalize()
    print(f"{len(lats)}x{len(lons)} celdas, {len(tiempo)} dias "
          f"({tiempo.year.min()}-{tiempo.year.max()})")

    presentes = [v for v in DIARIAS if v in diario]
    print(f"variables diarias: {', '.join(presentes)}")
    datos = {v: diario[v].values for v in presentes}

    meta = None
    ruta_meta = os.path.join(BASE, "celdas_galicia.csv")
    if os.path.exists(ruta_meta):
        meta = pd.read_csv(ruta_meta)
        meta["clave"] = meta.lat.round(2).astype(str) + "_" + meta.lon.round(2).astype(str)
        meta = meta.set_index("clave")

    filas, filas_tend = [], []
    total, hecho = len(lats) * len(lons), 0
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            hecho += 1
            if hecho % 50 == 0:
                print(f"  {hecho}/{total} celdas", end="\r", flush=True)
            col = {v: datos[v][:, i, j] for v in presentes}
            if np.isnan(col["tmax"]).mean() > 0.2:
                continue  # mar
            df = pd.DataFrame(col, index=tiempo).dropna(subset=["tmax", "tmin"])

            ind = indices_punto(df)
            if not ind:
                continue
            ind["lat"] = round(float(la), 2)
            ind["lon"] = round(float(lo), 2)
            if meta is not None:
                k = f"{ind['lat']}_{ind['lon']}"
                if k not in meta.index:
                    continue  # fuera de Galicia
                ind["provincia"] = meta.loc[k, "provincia"]
                ind["dist_costa_km"] = meta.loc[k, "dist_costa_km"]
            filas.append(ind)

            # ---- tendencia ---------------------------------------------------
            por_anio = []
            for a, sub in df.groupby(df.index.year):
                if len(sub) < 300:
                    continue
                r = {"anio": a,
                     "d_tx30": float((sub.tmax >= 30).sum()),
                     "d_tx32": float((sub.tmax >= 32).sum()),
                     "tx_p99": float(np.nanpercentile(sub.tmax, 99)),
                     "tx_verano": float(sub.tmax[sub.index.month.isin([6, 7, 8])].mean())}
                if "tmin_noche" in sub:
                    r["noches_trop"] = float((sub.tmin_noche >= 20).sum())
                if "at_max" in sub:
                    r["at_p99"] = float(np.nanpercentile(sub.at_max.dropna(), 99))
                por_anio.append(r)
            pa = pd.DataFrame(por_anio)
            if len(pa) >= 15:
                t = {"lat": ind["lat"], "lon": ind["lon"]}
                rec = pa.anio >= 2021
                pre = (pa.anio >= 1996) & (pa.anio <= 2020)
                for m in [c for c in pa.columns if c != "anio"]:
                    t[f"{m}_pend_decada"] = float(np.polyfit(pa.anio, pa[m], 1)[0] * 10)
                    if rec.sum() >= 3 and pre.sum() >= 10:
                        t[f"{m}_salto_21_25"] = float(pa[m][rec].mean() - pa[m][pre].mean())
                filas_tend.append(t)

    print()
    res = pd.DataFrame(filas)
    if res.empty:
        sys.exit("No se calculo ninguna celda. Revisa las descargas.")

    # ---- indice compuesto ---------------------------------------------------
    # 60 % picos de calor extremo, 40 % confort real (temperatura + humedad + viento)
    penal_calor = {"d_tx32": 0.30, "d_tx35": 0.25, "tx_p99": 0.20,
                   "olas_dias": 0.15, "noches_trop": 0.10}
    penal_confort = {"at_p99": 0.30, "d_at30": 0.25, "hx_p99": 0.20,
                     "d_hx35": 0.15, "noches_bochorno": 0.10}

    def escala(col):
        return (res[col].astype(float).rank(pct=True) * 100).fillna(50)

    def compuesto(pesos):
        disp = {c: p for c, p in pesos.items() if c in res}
        if not disp:
            return None
        norma = sum(disp.values())
        return sum(escala(c) * p / norma for c, p in disp.items())

    res["score_calor"] = compuesto(penal_calor)
    res["score_confort"] = compuesto(penal_confort)
    if res["score_confort"] is None:
        res["score_confort"] = res["score_calor"]
    # 0 = el punto mas fresco y llevadero de Galicia, 100 = el mas castigado
    res["indice_calor"] = (0.6 * res.score_calor + 0.4 * res.score_confort).round(1)
    res["ranking"] = res.indice_calor.rank(method="min").astype(int)

    orden = [c for c in ("ranking", "lat", "lon", "provincia", "dist_costa_km",
                         "indice_calor", "score_calor", "score_confort") if c in res]
    res = res[orden + [c for c in res.columns if c not in orden]].sort_values("ranking")
    res.to_csv(os.path.join(BASE, "indices_galicia.csv"), index=False, encoding="utf-8")
    if filas_tend:
        pd.DataFrame(filas_tend).to_csv(
            os.path.join(BASE, "tendencias_galicia.csv"), index=False)

    # ---- resumen ------------------------------------------------------------
    with open(os.path.join(BASE, "resumen.txt"), "w", encoding="utf-8") as fh:
        def p(*a):
            print(*a)
            print(*a, file=fh)

        p(f"Celdas analizadas: {len(res)}")
        p(f"Periodo: {tiempo.year.min()}-{tiempo.year.max()} "
          f"({res.n_anios.median():.0f} anios por celda)")
        cols = [c for c in ("lat", "lon", "provincia", "dist_costa_km", "indice_calor",
                            "d_tx32", "d_tx35", "tx_p99", "noches_trop",
                            "at_p99", "hx_p99", "viento_dias_calidos") if c in res]
        p("\n--- 15 celdas mas frescas ---")
        p(res.head(15)[cols].to_string(index=False))
        p("\n--- 10 celdas mas calurosas ---")
        p(res.tail(10)[cols].to_string(index=False))
        if filas_tend:
            td = pd.DataFrame(filas_tend)
            p("\n--- tendencia media en Galicia ---")
            for c in td.columns:
                if c.endswith(("_pend_decada", "_salto_21_25")):
                    p(f"  {c:30s} {td[c].mean():+.2f}  "
                      f"(rango {td[c].min():+.2f} a {td[c].max():+.2f})")

    print("\nGenerado: indices_galicia.csv, tendencias_galicia.csv, resumen.txt")
    print("Subelos al repositorio y avisame.")


if __name__ == "__main__":
    main()
