"""PASO 6 - Fusion de escalas: 30 anios de ERA5-Land + detalle de 1-4 km del WRF.

Ninguna de las dos fuentes sirve sola:

  ERA5-Land  30 anios homogeneos, pero a 9 km no ve el fondo de valle, la
             penetracion de la brisa ni el foehn de la costa norte.
  WRF        1-4 km, ve todo eso, pero es un archivo operativo: la version del
             modelo ha cambiado varias veces, asi que su serie temporal no es
             homogenea y no se puede usar para climatologia ni para tendencias.

La fusion usa cada una para lo que vale. Del WRF se extrae solo el *patron
espacial fino* -- la diferencia entre cada punto de 1 km y su entorno de 9 km --
y ese patron, que es robusto frente al sesgo del modelo porque es una diferencia
interna, se suma a la climatologia de 30 anios de ERA5-Land.

Es el metodo clasico de "delta downscaling". Lo que no arregla: si el WRF tiene
un sesgo espacialmente uniforme, desaparece en la resta (bien); si lo tiene
espacialmente estructurado, se cuela (limitacion real, anotada en el README).

Uso:  python 06_alta_resolucion.py
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import humedad_relativa, humidex, rh_a_porcentaje  # noqa: E402

# GAL_BASE permite redirigir entradas y salidas a otro directorio.
# Lo usan las pruebas para no tocar jamas tus descargas reales.
BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR_WRF = os.path.join(BASE, "wrf")

# Grados que puede desviarse la anomalia termica de lo que explica el relieve
# antes de considerarla un fallo del modelo. 4 C es muy holgado: el ajuste real
# tiene una desviacion tipica de 0.68 C, asi que esto son casi 6 sigmas. Se deja
# holgado a proposito, para no descartar efectos reales de brisa o de valle.
UMBRAL_RESIDUO = 4.0

# Por encima de esta altura los sitios salen frescos por estar en la sierra.
# Es cierto y no sirve: Trevinca a 1.900 m gana todos los rankings y no es un
# sitio donde vivir. El ranking util se limita a donde hay pueblos.
LIMITE_ALTITUD = 400


def nombre_temporal(da):
    for c in ("time", "valid_time", "time1", "reftime"):
        if c in da.dims:
            return c
    return [d for d in da.dims if "time" in d.lower()][0]


def a_dos_metros(da):
    """Se queda con el nivel de 2 m si la variable trae dimension vertical.

    Los ficheros de MeteoGalicia publican `temp` y `rh` con un eje de altura que
    a veces tiene un solo nivel y a veces varios. Coger el primero a ciegas
    daria la temperatura a 10 m o a 100 m sin avisar.
    """
    for d in da.dims:
        if d.lower() in ("height", "height_above_ground", "z", "level", "lev",
                         "altitude", "vertical"):
            if da.sizes[d] == 1:
                return da.isel({d: 0}, drop=True)
            if d in da.coords:
                niveles = np.asarray(da[d].values, dtype=float)
                i = int(np.argmin(np.abs(niveles - 2.0)))
                print(f"    niveles {niveles} -> uso {niveles[i]}")
                return da.isel({d: i}, drop=True)
            return da.isel({d: 0}, drop=True)
    return da


def coords_2d(ds, var):
    """Devuelve (lat2d, lon2d) tanto si la rejilla es regular como proyectada."""
    import xarray as xr  # noqa: F401

    for la, lo in (("lat", "lon"), ("latitude", "longitude")):
        if la in ds and lo in ds:
            a, o = ds[la].values, ds[lo].values
            if a.ndim == 2:
                return a, o
            if a.ndim == 1 and o.ndim == 1:
                return np.meshgrid(o, a)[1], np.meshgrid(o, a)[0]
    raise SystemExit(f"No encuentro coordenadas lat/lon en el fichero ({list(ds.coords)})")


def carga_wrf():
    """Maxima diaria (y humidex diario si hay humedad) para cada dia descargado."""
    import xarray as xr

    man_path = os.path.join(BASE, "wrf_manifiesto.json")
    man = json.load(open(man_path)) if os.path.exists(man_path) else {}
    ficheros = sorted(glob.glob(os.path.join(DIR_WRF, "wrf_*.nc")))
    if not ficheros:
        sys.exit("No hay ficheros en wrf/. Ejecuta antes 05_wrf_dias_calidos.py")

    txs, hxs, fechas, lat2d, lon2d = [], [], [], None, None
    primera_rh = True
    desajustes = []
    for f in ficheros:
        try:
            ds = xr.open_dataset(f)
        except Exception as e:  # noqa: BLE001
            print(f"  {os.path.basename(f)}: ilegible ({e})")
            continue
        cand_t = [v for v in ds.data_vars
                  if v.lower() in ("temp", "t2", "t2m", "temperature")]
        if not cand_t:
            cand_t = [v for v in ds.data_vars if ds[v].ndim >= 3]
        if not cand_t:
            continue
        t = a_dos_metros(ds[cand_t[0]])
        dt = nombre_temporal(t)
        t = t.squeeze(drop=True)
        if float(np.nanmax(t)) > 150:
            t = t - 273.15
        if lat2d is None:
            lat2d, lon2d = coords_2d(ds, cand_t[0])
        else:
            # El archivo es operativo: la version del modelo ha cambiado varias
            # veces en cinco anios y el dominio pudo moverse. Apilar por indice
            # dos rejillas distintas mezcla sitios distintos en el mismo punto,
            # y el resultado es una climatologia de ningun lugar. Es un error
            # que no da ningun aviso: las formas coinciden igual.
            la, lo = coords_2d(ds, cand_t[0])
            if la.shape != lat2d.shape or lo.shape != lon2d.shape:
                desajustes.append((os.path.basename(f),
                                   f"forma {la.shape} vs {lat2d.shape}"))
                ds.close()
                continue
            dmax = max(float(np.nanmax(np.abs(la - lat2d))),
                       float(np.nanmax(np.abs(lo - lon2d))))
            if dmax > 1e-4:      # ~10 m; por encima de eso no es redondeo
                desajustes.append((os.path.basename(f),
                                   f"rejilla desplazada {dmax * 111:.2f} km"))
                ds.close()
                continue

        tmax = t.max(dim=dt).values
        txs.append(tmax)
        fechas.append(pd.Timestamp(os.path.basename(f)[4:12]))

        cand_h = [v for v in ds.data_vars if v.lower() in ("rh", "rh2", "hr")]
        if cand_h:
            rh = a_dos_metros(ds[cand_h[0]]).squeeze(drop=True)
            # humedad en el momento de la maxima, aproximada por la del paso de
            # tiempo en que se alcanza esa maxima
            idx = t.argmax(dim=dt)
            # OJO: el WRF de MeteoGalicia publica rh con units="1" (fraccion),
            # no en porcentaje. Sin convertir, el humidex se queda igual que la
            # temperatura seca y el bochorno desaparece sin dar ningun error.
            rh_tmax = rh_a_porcentaje(rh.isel({dt: idx}).values,
                                      rh.attrs.get("units"))
            if primera_rh:
                print(f"    rh: units={rh.attrs.get('units', '?')!r} -> "
                      f"{np.nanmin(rh_tmax):.0f}-{np.nanmax(rh_tmax):.0f} %")
                primera_rh = False
            e = np.clip(rh_tmax, 1, 100) / 100.0 * 6.112 * np.exp(
                17.67 * tmax / (tmax + 243.5))
            hxs.append(np.maximum(tmax + 0.5555 * (e - 10.0), tmax))
        print(f"  {os.path.basename(f)}: tmax {np.nanmin(tmax):.1f}..{np.nanmax(tmax):.1f} C")

    if not txs:
        sys.exit("Ningun fichero WRF utilizable.")
    if desajustes:
        print(f"\n  ATENCION: {len(desajustes)} ficheros descartados por no "
              f"compartir rejilla con el primero:")
        for n, por in desajustes[:8]:
            print(f"    {n}: {por}")
        if len(desajustes) > 8:
            print(f"    ... y {len(desajustes) - 8} mas")
        print("  (apilarlos habria mezclado sitios distintos en el mismo punto)")
        with open(os.path.join(BASE, "wrf_rejillas_distintas.txt"), "w",
                  encoding="utf-8") as fh:
            for n, por in desajustes:
                fh.write(f"{n}\t{por}\n")
    else:
        print(f"\n  rejilla identica en los {len(txs)} ficheros: se pueden apilar")
    return (np.stack(txs), np.stack(hxs) if len(hxs) == len(txs) else None,
            pd.DatetimeIndex(fechas), lat2d, lon2d, man)


def carga_estaticos(forma, lat2d=None, lon2d=None):
    """(mascara_tierra, topografia) a partir de wrf/estaticos.nc, si existe.

    Por que hace falta: la rejilla del WRF cubre el oceano y los embalses, y el
    agua en verano esta mucho mas fria que la tierra. Sin separarla pasan dos
    cosas, las dos malas:

      1. El ranking de "sitios frescos" lo copan el Atlantico y los embalses.
      2. Peor y menos visible: al calcular el entorno de 9 km de un punto de
         costa, la media incluye mar frio, asi que toda la franja costera sale
         con una anomalia positiva que es un artefacto, no un rasgo del terreno.

    Devuelve (None, None) si no esta el fichero: el paso sigue funcionando, pero
    avisa.
    """
    import xarray as xr

    ruta = os.path.join(DIR_WRF, "estaticos.nc")
    if not os.path.exists(ruta):
        return None, None
    ds = xr.open_dataset(ruta)
    topo = usos = None
    for v in ds.data_vars:
        arr = np.asarray(ds[v].squeeze(drop=True).values, dtype=float)
        if arr.shape != forma:
            continue
        if v.lower() in ("topo", "hgt", "orog", "altitud"):
            topo = arr
        elif v.lower() in ("land_use", "lu_index", "landmask", "lsmask"):
            usos = arr
    ds.close()

    tierra = None
    if usos is not None:
        vals = np.unique(usos[np.isfinite(usos)])
        # Solo es una mascara si los valores son 0 y 1. "Dos categorias
        # distintas" no basta: land_use = {5, 17} son matorral y agua, y
        # tratarlo como mascara marca los dos como tierra.
        if set(vals.tolist()) <= {0.0, 1.0}:
            tierra = usos > 0.5
            print(f"  mascara binaria de tierra ({vals})")
        elif topo is not None:
            # La categoria de agua es la que domina donde la altitud es cero.
            # Deducirla asi evita depender de si la tabla es USGS (16) o
            # MODIS (17), que no viene indicado en el fichero.
            bajo = np.isfinite(topo) & (topo <= 0.5) & np.isfinite(usos)
            if bajo.sum() > 50:
                cats, cuenta = np.unique(usos[bajo], return_counts=True)
                agua = cats[np.argmax(cuenta)]
                tierra = usos != agua
                print(f"  categoria de agua deducida: land_use == {agua:.0f}")
    if tierra is None and topo is not None:
        tierra = topo > 0.5
        print("  sin usos del suelo: se usa topografia > 0.5 m")
    if tierra is not None:
        print(f"  tierra: {tierra.mean():.1%} de la rejilla "
              f"({tierra.sum():,} de {tierra.size:,} puntos)")
        if lat2d is not None:
            agua_interior(tierra, lat2d, lon2d)
    return tierra, topo


def agua_interior(tierra, lat2d, lon2d):
    """Lista las manchas de agua que NO estan conectadas con el oceano.

    Sirve para poder contrastarlas con un mapa. Algunas seran embalses reales;
    otras, pixeles que el modelo clasifica como agua sin que la haya. La
    distincion no cambia lo que hay que hacer -- si el modelo los trata como
    agua, su temperatura se comporta como agua y hay que excluirlos igual --
    pero conviene saber cuales son en vez de suponerlo.
    """
    from scipy import ndimage

    agua = ~tierra
    etiquetas, n = ndimage.label(agua)
    if n == 0:
        return
    # el oceano es la mancha que toca el borde oeste
    borde = set(np.unique(etiquetas[:, 0])) | set(np.unique(etiquetas[0, :])) \
        | set(np.unique(etiquetas[-1, :]))
    borde.discard(0)
    dentro = [i for i in range(1, n + 1) if i not in borde]
    if not dentro:
        print("  no hay agua interior separada del oceano")
        return
    tam = [(int((etiquetas == i).sum()), i) for i in dentro]
    tam.sort(reverse=True)
    print(f"  agua interior: {len(dentro)} manchas, "
          f"{sum(t for t, _ in tam):,} puntos. Las mayores:")
    for t, i in tam[:8]:
        m = etiquetas == i
        print(f"    {t:4d} km2 en {np.mean(lat2d[m]):.3f} / {np.mean(lon2d[m]):.3f}")


def suaviza_a_9km(campo, lat2d, lon2d, tierra=None, avisa=True):
    """Media movil con la ventana equivalente a una celda de ERA5-Land (9 km).

    Si se pasa `tierra`, la media se hace SOLO sobre puntos de tierra y se
    normaliza por cuantos habia en cada ventana. Es lo correcto porque el
    termino de comparacion es ERA5-Land, que tambien es solo tierra.
    """
    from scipy.ndimage import uniform_filter

    dlat = np.nanmedian(np.abs(np.diff(lat2d, axis=0)))
    dlon = np.nanmedian(np.abs(np.diff(lon2d, axis=1)))
    paso_km = np.hypot(dlat * 110.6, dlon * 82.0)
    v = max(3, int(round(9.0 / max(paso_km, 0.2))))
    if v % 2 == 0:
        v += 1
    if avisa:
        print(f"  paso de rejilla ~{paso_km:.2f} km -> ventana de suavizado {v}x{v}")

    valido = np.isfinite(campo)
    if tierra is not None:
        valido &= tierra
    if valido.all():
        return uniform_filter(campo, size=v, mode="nearest"), paso_km, v

    num = uniform_filter(np.where(valido, campo, 0.0), size=v, mode="nearest")
    den = uniform_filter(valido.astype(float), size=v, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        # menos de un 10% de vecinos validos: no hay entorno que promediar
        suave = np.where(den > 0.10, num / np.where(den > 0, den, 1.0), np.nan)
    return suave, paso_km, v


def main():
    print("Leyendo WRF ...")
    tx, hx, fechas, lat2d, lon2d, man = carga_wrf()
    print(f"\n{len(fechas)} dias, rejilla {lat2d.shape}")

    # --- estadisticos del WRF sobre los dias calidos -------------------------
    est = {
        "wrf_tx_medio": np.nanmean(tx, axis=0),
        "wrf_tx_p90": np.nanpercentile(tx, 90, axis=0),
        "wrf_tx_max": np.nanmax(tx, axis=0),
        "wrf_n_ge32": np.nansum(tx >= 32, axis=0),
        "wrf_n_ge35": np.nansum(tx >= 35, axis=0),
        "wrf_n_ge38": np.nansum(tx >= 38, axis=0),
    }
    if hx is not None:
        est["wrf_hx_medio"] = np.nanmean(hx, axis=0)
        est["wrf_hx_p90"] = np.nanpercentile(hx, 90, axis=0)
        est["wrf_n_hx35"] = np.nansum(hx >= 35, axis=0)

    # --- tierra, mar y embalses ----------------------------------------------
    print("\nSeparando tierra de agua ...")
    tierra, topo = carga_estaticos(lat2d.shape, lat2d, lon2d)
    if tierra is None:
        print("  AVISO: no hay wrf/estaticos.nc. El oceano y los embalses entran")
        print("  en el analisis como si fueran sitios donde vivir, y ademas")
        print("  contaminan el entorno de 9 km de toda la costa.")
        print("  Solucion: python 05_wrf_dias_calidos.py --estaticos")

    # --- anomalia sub-rejilla -------------------------------------------------
    print("\nExtrayendo el patron espacial fino ...")
    anomalias = {}
    primera = True
    for k in ("wrf_tx_medio", "wrf_tx_p90", "wrf_hx_p90"):
        if k not in est:
            continue
        suave, paso_km, vent = suaviza_a_9km(est[k], lat2d, lon2d, tierra,
                                             avisa=primera)
        primera = False
        an = est[k] - suave
        if tierra is not None:
            an = np.where(tierra, an, np.nan)
        anomalias[k.replace("wrf_", "anom_")] = an
    a = anomalias["anom_tx_medio"]
    print(f"  anomalia de Tmax en dias calidos: {np.nanmin(a):+.1f} a {np.nanmax(a):+.1f} C")
    print(f"  desviacion tipica: {np.nanstd(a):.2f} C  "
          f"(esto es exactamente lo que ERA5-Land no puede ver)")
    if tierra is not None:
        # el mismo calculo sin enmascarar, para ver cuanto cambiaba el agua
        sin_m, _, _ = suaviza_a_9km(est["wrf_tx_medio"], lat2d, lon2d, avisa=False)
        print(f"  (sin separar el agua saldria {np.nanstd(est['wrf_tx_medio'] - sin_m):.2f} C)")

    # --- ¿es relieve o es un fallo del modelo? -------------------------------
    # La prueba fisica: una anomalia termica sostenida tiene que ir acompaniada
    # de una anomalia topografica. El aire a 2 m no puede estar 8 C mas frio que
    # el de 1 km al lado si el terreno esta a la misma altura. Ajustando la
    # anomalia termica contra la topografica sale el gradiente vertical, que es
    # una constante fisica conocida (-6.5 C/km): si el ajuste lo reproduce, el
    # patron fino es real; y los puntos que se salen del ajuste son fallos del
    # modelo, no sitios frescos.
    anom_topo = residuo = sospechoso = None
    if topo is not None and tierra is not None:
        topo_s, _, _ = suaviza_a_9km(topo, lat2d, lon2d, tierra, avisa=False)
        anom_topo = np.where(tierra, topo - topo_s, np.nan)
        ok = np.isfinite(anom_topo) & np.isfinite(a)
        if ok.sum() > 1000:
            b = np.polyfit(anom_topo[ok], a[ok], 1)
            r = np.corrcoef(anom_topo[ok], a[ok])[0, 1]
            residuo = np.where(ok, a - np.polyval(b, anom_topo), np.nan)
            print(f"\n  gradiente ajustado: {b[0] * 1000:+.2f} C por cada 1000 m de "
                  f"altitud relativa   (valor fisico esperado: -5 a -10)")
            print(f"  correlacion con la topografia: {r:+.3f}  "
                  f"-> el relieve explica el {r ** 2:.0%} de la variacion fina")
            print(f"  lo que NO es relieve (brisa, valle, costa): "
                  f"{np.nanstd(residuo):.2f} C de desviacion tipica")
            sospechoso = np.isfinite(residuo) & (np.abs(residuo) > UMBRAL_RESIDUO)
            print(f"  puntos incompatibles con su topografia: {sospechoso.sum():,} "
                  f"({sospechoso.mean():.2%}) -> marcados, fuera de los rankings")

    # --- fusion con la climatologia de 30 anios ------------------------------
    ruta_ind = os.path.join(BASE, "indices_galicia.csv")
    fila = lat2d.ravel()
    col = lon2d.ravel()
    salida = pd.DataFrame({"lat": np.round(fila, 4), "lon": np.round(col, 4)})
    if topo is not None:
        salida["altitud"] = np.round(topo.ravel(), 1)
    if tierra is not None:
        salida["tierra"] = tierra.ravel().astype(int)
    if anom_topo is not None:
        salida["anom_altitud"] = np.round(anom_topo.ravel(), 1)
    if residuo is not None:
        salida["residuo"] = np.round(residuo.ravel(), 2)
        salida["sospechoso"] = sospechoso.ravel().astype(int)
    for k, v in est.items():
        salida[k] = np.round(v.ravel(), 2)
    for k, v in anomalias.items():
        salida[k] = np.round(v.ravel(), 2)

    if os.path.exists(ruta_ind):
        from scipy.interpolate import griddata

        ind = pd.read_csv(ruta_ind)
        print("\nFusionando con la climatologia de 30 anios de ERA5-Land ...")
        pares = ind[["lon", "lat"]].values
        for col_era, col_anom, nombre in [
            ("tx_p99", "anom_tx_p90", "tx_p99_1km"),
            ("tx_verano", "anom_tx_medio", "tx_verano_1km"),
            ("hx_p99", "anom_hx_p90", "hx_p99_1km"),
        ]:
            if col_era not in ind or col_anom not in salida:
                continue
            base = griddata(pares, ind[col_era].values,
                            (salida.lon.values, salida.lat.values), method="linear")
            faltan = ~np.isfinite(base)
            if faltan.any():  # bordes: completa con el vecino mas proximo
                base[faltan] = griddata(
                    pares, ind[col_era].values,
                    (salida.lon.values[faltan], salida.lat.values[faltan]),
                    method="nearest")
            salida[nombre] = np.round(base + salida[col_anom].values, 2)
            print(f"  {nombre}: {salida[nombre].min():.1f} a {salida[nombre].max():.1f} C")
    else:
        print("\n(sin indices_galicia.csv: no se fusiona, solo se guarda el WRF)")

    salida = salida.dropna(subset=["wrf_tx_medio"])
    destino = os.path.join(BASE, "alta_resolucion.csv.gz")
    salida.to_csv(destino, index=False, compression="gzip")
    mb = os.path.getsize(destino) / 1e6
    print(f"\nalta_resolucion.csv.gz: {len(salida):,} puntos, {mb:.1f} MB")

    # --- resumen legible ------------------------------------------------------
    with open(os.path.join(BASE, "resumen_alta_resolucion.txt"), "w", encoding="utf-8") as fh:
        def p(*x):
            print(*x)
            print(*x, file=fh)

        p(f"Dias calidos usados: {len(fechas)} "
          f"({fechas.year.min()}-{fechas.year.max()})")
        p(f"Conjunto WRF: {man.get('conjunto', 'desconocido')}")
        p(f"Puntos de rejilla: {len(salida):,}")
        col = "tx_p99_1km" if "tx_p99_1km" in salida else "wrf_tx_p90"

        # Los rankings, SOLO sobre tierra. Sin esto los veinte sitios mas
        # frescos de Galicia son el Atlantico y el embalse de Belesar.
        if "tierra" in salida:
            firme = salida[salida.tierra == 1]
            p(f"Puntos en tierra: {len(firme):,} ({len(firme) / len(salida):.0%})")
            if "sospechoso" in firme:
                n_s = int(firme.sospechoso.sum())
                firme = firme[firme.sospechoso == 0]
                p(f"Descartados por ser incompatibles con su topografia: {n_s:,} "
                  f"(fallo del modelo, no sitios frescos)")
        else:
            firme = salida
            p("SIN mascara de tierra: el ranking incluye mar y embalses "
              "(ejecuta 05_wrf_dias_calidos.py --estaticos)")
        cols = ["lat", "lon", col, "anom_tx_medio"]
        if "altitud" in firme:
            cols.insert(2, "altitud")

        p(f"\n--- 20 puntos mas frescos por {col} ---")
        p(firme.nsmallest(20, col)[cols].to_string(index=False))
        p(f"\n--- 10 puntos mas calurosos ---")
        p(firme.nlargest(10, col)[cols].to_string(index=False))

        # Diez puntos de costa no tienen suficientes vecinos de tierra en la
        # ventana de 9 km para calcular su anomalia, asi que su columna
        # fusionada es NaN. Son islotes y puntas; arrastran a NaN cualquier
        # correlacion que los incluya.
        firme = firme.dropna(subset=[col])

        if "altitud" in firme:
            p("\n--- cuanto de esto es solo altitud? ---")
            r = np.corrcoef(firme.altitud.values, firme[col].values)[0, 1]
            p(f"  correlacion altitud vs {col}: {r:+.3f}")
            if "residuo" in firme:
                p(f"  variacion fina total: {firme.anom_tx_medio.std():.2f} C")
                p(f"  de la que NO explica el relieve: {firme.residuo.std():.2f} C")
                p("  (esa segunda es la que aporta informacion nueva: brisa,")
                p("   inversion de valle, cercania al mar a igualdad de altura)")
                p("\n  los 10 sitios mas frescos DE MAS que por su altura:")
                fr = firme[firme.altitud < 400].nsmallest(10, "residuo")
                p(fr[["lat", "lon", "altitud", "wrf_tx_p90", "anom_altitud",
                      "residuo"]].to_string(index=False))

        # --- temperatura o sensacion? no ordenan igual --------------------
        if "wrf_hx_p90" in firme and "altitud" in firme:
            p("\n--- temperatura seca o sensacion real? ---")
            rho = firme.wrf_tx_p90.rank().corr(firme.wrf_hx_p90.rank(),
                                               method="spearman")
            p(f"  correlacion de rangos entre tx_p90 y hx_p90: {rho:.3f}")
            p("  (si fuera ~1 daria igual cual mirar; no lo es)")
            p("\n  cuanto anade la humedad, por franja de altitud:")
            p(f"  {'franja':>14s} {'puntos':>8s} {'tx_p90':>7s} {'hx_p90':>7s} {'anade':>7s}")
            for lo, hi in [(0, 50), (50, 150), (150, 300), (300, 600),
                           (600, 1000), (1000, 3000)]:
                s = firme[(firme.altitud >= lo) & (firme.altitud < hi)]
                if len(s) < 50:
                    continue
                p(f"  {f'{lo}-{hi} m':>14s} {len(s):8,} {s.wrf_tx_p90.mean():7.1f} "
                  f"{s.wrf_hx_p90.mean():7.1f} {(s.wrf_hx_p90 - s.wrf_tx_p90).mean():+7.1f}")
            p("  La costa gana en temperatura y pierde en humedad; la montania")
            p("  al reves. Por eso el criterio pesa las dos cosas.")

            # --- puntuacion acordada: 60% picos extremos, 40% confort -----
            # Se usan las columnas fusionadas si existen: son la climatologia
            # completa corregida a 1 km, no los 251 dias del WRF. Si todavia no
            # se ha hecho la fusion, se cae a las del WRF y se avisa.
            fusion = "tx_p99_1km" in firme and "hx_p99_1km" in firme
            c_ext = "tx_p99_1km" if fusion else "wrf_tx_p90"
            c_con = "hx_p99_1km" if fusion else "wrf_hx_p90"
            b = firme[firme.altitud < LIMITE_ALTITUD].dropna(
                subset=[c_ext, c_con]).copy()
            if len(b) > 200:
                def z(c):
                    return (b[c] - b[c].mean()) / b[c].std()
                b["nota"] = 0.6 * z(c_ext) + 0.4 * z(c_con)
                cs = ["lat", "lon", "altitud", c_ext, c_con,
                      "wrf_n_ge32", "wrf_n_hx35", "nota"]
                p(f"\n--- criterio 60/40 (picos 60%, confort 40%), "
                  f"por debajo de {LIMITE_ALTITUD} m ---")
                if fusion:
                    p(f"  Sobre la climatologia completa de ERA5-Land corregida a")
                    p(f"  1 km: {c_ext} pesa el 60%, {c_con} el 40%.")
                    p(f"  Las dos ultimas columnas son del WRF (251 dias), como contexto.")
                else:
                    p("  PROVISIONAL: solo con los dias del WRF, sin fusionar.")
                p("\n  los 15 mejores:")
                p(b.nsmallest(15, "nota")[cs].round(2).to_string(index=False))
                p("\n  los 8 peores:")
                p(b.nlargest(8, "nota")[cs].round(2).to_string(index=False))
                b.nsmallest(400, "nota").to_csv(
                    os.path.join(BASE, "ranking_60_40.csv"), index=False,
                    encoding="utf-8")
                p(f"\n  (los 400 mejores, en ranking_60_40.csv)")
            p("  20 mas frescos POR DEBAJO de 400 m (donde se vive):")
            bajo = firme[firme.altitud < 400]
            if len(bajo) > 20:
                p(bajo.nsmallest(20, col)[cols].to_string(index=False))

    print("\nSube alta_resolucion.csv.gz y resumen_alta_resolucion.txt al repositorio.")


if __name__ == "__main__":
    main()
