"""PASO 13 - ROCIO_IBEB: setenta anios de observacion en rejilla de 5 km.

Es la mejor fuente que hemos encontrado para la pregunta de la tendencia, y por
un margen amplio:

    ERA5-Land (paso 1)    2011-2025, 9 km,  reanalisis (modelo)
    AEMET estaciones (12) 1940-2025, puntual, 16 series largas
    ROCIO_IBEB (este)     1951-2022, 5 km,  OBSERVACION, Galicia entera

Rejilla de 0,05 grados en polo rotado sobre la Espania peninsular y Baleares,
generada por interpolacion optima. Se descarga por decadas en NetCDF, por HTTP
normal: sin clave, sin cola y sin limite de peticiones.

Lo que este paso NO hace: sustituir a ERA5-Land. ROCIO solo trae temperatura
maxima y minima, sin humedad, asi que no da humidex -- que es el 40 % del
criterio. Y termina antes que ERA5-Land. Sirve para la tendencia y para
contrastar la climatologia, no para el ranking de confort.

Aviso importante sobre la homogeneidad
--------------------------------------
El README del propio conjunto dice, literalmente, que la rejilla de temperatura
se genero "using all available observations at AEMET Banco Nacional de Datos,
**not only a selected group as in precipitation version 1**". Es decir: en
precipitacion hubo un cribado por homogeneidad y completitud; en temperatura NO.
Eso significa que la red que alimenta la interpolacion cambia con los anios, y
un cambio en la densidad de observacion puede meter una tendencia que no es
clima. El paso lo mide en vez de suponerlo (ver --analizar).

Uso
---
    python 13_rocio.py --explorar
        Comprueba que URL existen de verdad y cuanto pesan. Sin descargar.

    python 13_rocio.py --descargar
        Baja decada a decada, recorta a Galicia y borra el fichero grande.
        De ~15 GB de rejilla nacional quedan unos 300 MB de Galicia.

    python 13_rocio.py --analizar
        Indices anuales por celda, pendiente sobre los 70 anios y contraste
        contra todas las ventanas de 15 anios.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
import time

import requests

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "rocio")
TMPD = os.path.join(DIR, "_tmp")

RAIZ = ("https://www.aemet.es/documentos/es/serviciosclimaticos/cambio_climat/"
        "datos_diarios/dato_observacional/rejilla_5km/temperatura/v1")

# Caja de Galicia con margen. La rejilla nacional son 280x240 celdas; recortada
# a esto quedan unas 2.500, que es lo unico que nos interesa.
BBOX = (41.70, -9.50, 43.95, -6.55)   # sur, oeste, norte, este

# Nombre de la variable dentro del fichero segun el README. Se comprueba SIEMPRE
# contra el contenido: los ficheros de tmax y de tmin se llaman igual
# (sfcanYYYY0101aYYYY1231_rot_mask.nc) y solo se distinguen por la carpeta de
# la que cuelgan. Si se extraen los dos al mismo sitio, uno pisa al otro y te
# quedas con minimas etiquetadas como maximas, sin ningun aviso.
VARIABLES = {"tmax": ("maxtemp", "temperature"), "tmin": ("mintemp", "temperature")}

# Tramos publicados. Se comprueban uno a uno: la nota tecnica y la web no
# coinciden en donde acaba la serie de temperatura (el README de la v1 menciona
# 2020-06-30 y la web anuncia 2022).
TRAMOS = [(1951, 1959), (1960, 1969), (1970, 1979), (1980, 1989),
          (1990, 1999), (2000, 2009), (2010, 2019),
          (2020, 2020), (2021, 2021), (2022, 2022)]

S = requests.Session()
S.headers["User-Agent"] = "analisis-climatico-galicia/1.0 (+python-requests)"


def url_de(var, a, b):
    tramo = f"{a}a{b}" if a != b else f"{a}"
    return f"{RAIZ}/{var}/Serie_AEMET_v1_{var}_{tramo}_netcdf.tar.gz"


def existe(url):
    """(hay, bytes o motivo). HEAD primero; si el servidor no lo admite, GET
    parcial: algunos servidores de la Administracion no responden a HEAD."""
    try:
        r = S.head(url, timeout=45, allow_redirects=True)
        if r.status_code == 200:
            return True, int(r.headers.get("content-length", 0))
        if r.status_code in (403, 405):      # HEAD no permitido
            r = S.get(url, timeout=45, stream=True,
                      headers={"Range": "bytes=0-1023"})
            if r.status_code in (200, 206):
                n = r.headers.get("content-range", "").split("/")[-1]
                r.close()
                return True, int(n) if n.isdigit() else 0
        return False, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, f"{e.__class__.__name__}"


def explorar():
    print(f"Comprobando que hay publicado de verdad en\n  {RAIZ}\n")
    hay = {}
    for var in VARIABLES:
        print(f"--- {var} ---")
        for a, b in TRAMOS:
            u = url_de(var, a, b)
            ok, info = existe(u)
            if ok:
                hay.setdefault(var, []).append((a, b, info))
                print(f"  OK    {a}-{b}  {info / 1e6:7.1f} MB")
            else:
                print(f"  no    {a}-{b}  ({info})")
            time.sleep(0.5)
    print()
    for var, tramos in hay.items():
        anios = sum(b - a + 1 for a, b, _ in tramos)
        mb = sum(t[2] for t in tramos) / 1e6
        print(f"{var}: {len(tramos)} ficheros, {anios} anios, {mb:,.0f} MB comprimidos")
    if not hay:
        print("No hay nada accesible. ¿Ha cambiado la ruta en la web de AEMET?")
    return hay


def descarga(url, destino):
    if os.path.exists(destino) and os.path.getsize(destino) > 1_000_000:
        return "cache"
    tmp = destino + ".parcial"
    with S.get(url, stream=True, timeout=600) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        total = int(r.headers.get("content-length", 0))
        n = 0
        with open(tmp, "wb") as fh:
            for trozo in r.iter_content(1 << 20):
                fh.write(trozo)
                n += len(trozo)
                if total:
                    print(f"\r    {n / 1e6:6.1f} / {total / 1e6:.1f} MB "
                          f"({n / total:.0%})", end="", flush=True)
    print()
    os.replace(tmp, destino)
    return "ok"


def recorta(ruta_nc, var, destino):
    """Se queda con la ventana de Galicia y verifica que la variable es la que
    toca. Devuelve el numero de dias, o None si el fichero no sirve."""
    import numpy as np
    import xarray as xr

    ds = xr.open_dataset(ruta_nc, decode_times=True)
    try:
        candidatas = [v for v in ds.data_vars if v in VARIABLES[var][0:1]]
        if not candidatas:
            # el README puede quedarse viejo: se acepta cualquier variable 4D
            candidatas = [v for v in ds.data_vars if ds[v].ndim >= 3]
        if not candidatas:
            return None
        nombre = candidatas[0]
        esperada = VARIABLES[var][0]
        if nombre != esperada:
            print(f"    AVISO: esperaba '{esperada}' y hay '{nombre}'. "
                  f"Comprueba que no se han mezclado tmax y tmin.")
        da = ds[nombre].squeeze(drop=True)

        lat, lon = ds["lat"].values, ds["lon"].values
        s, o, n, e = BBOX
        dentro = (lat >= s) & (lat <= n) & (lon >= o) & (lon <= e)
        if not dentro.any():
            return None
        f, c = np.where(dentro)
        dy, dx = ds["lat"].dims
        rec = da.isel({dy: slice(f.min(), f.max() + 1),
                       dx: slice(c.min(), c.max() + 1)})
        sub = xr.Dataset(
            {var: rec.astype("float32")},
            coords={"lat": ((dy, dx), lat[f.min():f.max() + 1, c.min():c.max() + 1]),
                    "lon": ((dy, dx), lon[f.min():f.max() + 1, c.min():c.max() + 1])})
        # -9999 es el valor de ausencia declarado en el README
        sub[var] = sub[var].where(sub[var] > -900)
        sub.attrs["fuente"] = "AEMET ROCIO_IBEB v1 (Peral et al., 2017)"
        comp = {var: {"zlib": True, "complevel": 4}}
        sub.to_netcdf(destino, encoding=comp)
        return int(rec.sizes.get("time", 0))
    finally:
        ds.close()


def descargar(solo_var=None):
    os.makedirs(DIR, exist_ok=True)
    for var in VARIABLES:
        if solo_var and var != solo_var:
            continue
        for a, b in TRAMOS:
            marca = os.path.join(DIR, f".{var}_{a}_{b}.hecho")
            if os.path.exists(marca):
                continue
            u = url_de(var, a, b)
            tgz = os.path.join(DIR, os.path.basename(u))
            print(f"{var} {a}-{b}")
            try:
                descarga(u, tgz)
            except (RuntimeError, requests.RequestException) as e:
                print(f"    no disponible ({e})")
                open(marca, "w").close()
                continue

            shutil.rmtree(TMPD, ignore_errors=True)
            os.makedirs(TMPD)
            with tarfile.open(tgz) as t:
                t.extractall(TMPD)
            hechos = 0
            for raiz, _, ficheros in os.walk(TMPD):
                for f in sorted(ficheros):
                    if not f.endswith(".nc"):
                        continue
                    anio = "".join(ch for ch in f if ch.isdigit())[:4]
                    dest = os.path.join(DIR, f"{var}_{anio}.nc")
                    dias = recorta(os.path.join(raiz, f), var, dest)
                    if dias:
                        hechos += 1
                        print(f"    {anio}: {dias} dias -> "
                              f"{os.path.getsize(dest) / 1e6:.1f} MB")
            # el fichero nacional pesa 100 MB por anio y no se vuelve a usar
            shutil.rmtree(TMPD, ignore_errors=True)
            os.remove(tgz)
            open(marca, "w").close()
            print(f"    {hechos} anios recortados, fichero nacional borrado\n")
    print("Siguiente:  python 13_rocio.py --analizar")


# ---------------------------------------------------------------------------

def sen(x, y):
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 5:
        return np.nan
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx != 0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def reduce_valido(cubo, fn):
    """Aplica `fn` sobre el eje temporal solo donde hay datos.

    Un tercio largo de la caja de Galicia es mar, y esas celdas son NaN de
    arriba abajo. Reducirlas con np.nanpercentile o np.nanmean da el resultado
    correcto (NaN) pero emitiendo un aviso por celda vacia. Sacandolas antes,
    el aviso no llega a producirse y ademas se calcula sobre menos datos.
    """
    import numpy as np
    T = cubo.shape[0]
    plano = cubo.reshape(T, -1)
    ok = np.isfinite(plano).all(axis=0)
    fuera = np.full(plano.shape[1], np.nan, dtype="float32")
    if ok.any():
        fuera[ok] = fn(plano[:, ok])
    return fuera.reshape(cubo.shape[1:])


def sen_malla(anios, cubo):
    """Pendiente de Sen de TODAS las celdas a la vez.

    Celda a celda son unos 3 minutos con las 58 ventanas moviles; asi son
    segundos. La mediana de las pendientes entre todos los pares de anios se
    calcula sobre el eje temporal para la rejilla entera de una vez.
    """
    import numpy as np
    n = len(anios)
    i, j = np.triu_indices(n, 1)
    dx = (anios[j] - anios[i]).astype("float32")
    with np.errstate(invalid="ignore", divide="ignore"):
        pend = (cubo[j] - cubo[i]) / dx[:, None, None]
    return np.nanmedian(pend, axis=0)


def analizar(ventana=15):
    import glob
    import warnings
    import numpy as np
    import pandas as pd
    import xarray as xr

    # Silenciar el aviso es el segundo cinturon; el primero es no provocarlo
    # (ver `reduce_valido`). Hace falta el segundo porque abrir un fichero con
    # xarray reinicia el registro de avisos de Python: el MISMO aviso, que
    # deberia salir una vez, se reimprime una vez por fichero. Con 72 ficheros
    # son 144 lineas que aparecen de golpe y parecen un bucle infinito.
    warnings.filterwarnings("ignore", category=RuntimeWarning)

    ficheros = sorted(glob.glob(os.path.join(DIR, "tmax_*.nc")))
    if not ficheros:
        sys.exit("No hay nada en rocio/. Ejecuta antes --descargar")
    print(f"Leyendo {len(ficheros)} anios de tmax ...", flush=True)

    filas, lat, lon = [], None, None
    t0 = time.time()
    for k, f in enumerate(ficheros, 1):
        anio = int(os.path.basename(f)[5:9])
        with xr.open_dataset(f) as ds:
            v = ds["tmax"]
            if v.sizes["time"] < 330:
                continue
            a = v.values
            t = pd.DatetimeIndex(v.time.values)
            verano = np.isin(t.month, [6, 7, 8])
            filas.append({
                "anio": anio,
                "tx_p99": reduce_valido(a, lambda z: np.percentile(z, 99, axis=0)),
                "tx_verano": reduce_valido(a[verano], lambda z: z.mean(axis=0)),
                "d_tx30": np.nansum(a >= 30, axis=0).astype("float32"),
                "d_tx32": np.nansum(a >= 32, axis=0).astype("float32"),
            })
            if lat is None:
                lat, lon = ds["lat"].values, ds["lon"].values
        if k % 10 == 0 or k == len(ficheros):
            print(f"  {k}/{len(ficheros)} anios  ({time.time() - t0:.0f} s)",
                  flush=True)
    if len(filas) < 30:
        sys.exit(f"Solo {len(filas)} anios completos; no da para la tendencia")

    anios = np.array([f["anio"] for f in filas])
    # celdas con dato en todos los anios: el resto es mar o borde de la mascara
    tierra = np.all([np.isfinite(f["tx_p99"]) for f in filas], axis=0)
    L = []

    def p(*a):
        print(*a, flush=True)
        L.append(" ".join(str(x) for x in a))

    p(f"ROCIO_IBEB: {len(anios)} anios completos, {anios.min()}-{anios.max()}")
    p(f"Rejilla de Galicia: {lat.shape[0]}x{lat.shape[1]} celdas, "
      f"{tierra.sum()} con serie completa")
    p(f"Extension: {lat[tierra].min():.2f}-{lat[tierra].max():.2f} N, "
      f"{lon[tierra].min():.2f}-{lon[tierra].max():.2f} E")

    for metrica, unidad in (("tx_verano", "C"), ("tx_p99", "C"),
                            ("d_tx30", "dias"), ("d_tx32", "dias")):
        cubo = np.stack([f[metrica] for f in filas]).astype("float32")
        larga_malla = sen_malla(anios, cubo) * 10
        val = larga_malla[tierra]
        val = val[np.isfinite(val)]
        larga = float(np.median(val))
        p(f"\n--- {metrica} ---")
        p(f"  tendencia {anios.min()}-{anios.max()}: mediana {larga:+.3f} "
          f"{unidad}/decada   (p10 {np.percentile(val, 10):+.3f}, "
          f"p90 {np.percentile(val, 90):+.3f})")

        cortas = []
        for i in range(len(anios) - ventana + 1):
            sl = slice(i, i + ventana)
            pc = sen_malla(anios[sl], cubo[sl]) * 10
            v = pc[tierra]
            cortas.append((anios[i], anios[i + ventana - 1],
                           float(np.nanmedian(v))))
        c = np.array([x[2] for x in cortas])
        p(f"  {len(cortas)} ventanas de {ventana} anios: mediana {np.median(c):+.3f}, "
          f"de {c.min():+.3f} a {c.max():+.3f}")
        p(f"  el {(c > larga).mean():.0%} de las ventanas exagera respecto a la serie completa")
        p(f"  exageracion mediana: {np.median(c) - larga:+.3f} {unidad}/decada")
        cerca = [x for x in cortas if x[1] >= anios.max() - 6]
        if cerca:
            p("  las ventanas recientes, comparables a nuestro 2011-2025:")
            for a0, a1, v in cerca:
                p(f"    {a0}-{a1}: {v:+.3f}   ({v - larga:+.3f} respecto a la larga)")

    # --- ¿se calientan mas deprisa los sitios que ya son calurosos? ---------
    # Es la pregunta que decide si la brecha entre la costa y el interior se
    # esta abriendo. Si se abre, la diferencia de hoy subestima la de dentro de
    # treinta anios, y elegir por la de hoy es quedarse corto.
    import pandas as pd
    cubo = np.stack([f["tx_verano"] for f in filas]).astype("float32")
    clim = np.nanmean(cubo, axis=0)
    tend = sen_malla(anios, cubo) * 10
    cubo99 = np.stack([f["tx_p99"] for f in filas]).astype("float32")
    tend99 = sen_malla(anios, cubo99) * 10
    m = tierra & np.isfinite(clim) & np.isfinite(tend)
    tabla = pd.DataFrame({
        "lat": np.round(lat[m], 4), "lon": np.round(lon[m], 4),
        "tx_verano_clim": np.round(clim[m], 2),
        "tx_verano_tend": np.round(tend[m], 3),
        "tx_p99_clim": np.round(np.nanmean(cubo99, axis=0)[m], 2),
        "tx_p99_tend": np.round(tend99[m], 3)})
    tabla.to_csv(os.path.join(BASE, "rocio_tendencias.csv"), index=False,
                 encoding="utf-8")

    p("\n--- ¿se abre la brecha entre los sitios frescos y los calurosos? ---")
    r = float(np.corrcoef(tabla.tx_verano_clim, tabla.tx_verano_tend)[0, 1])
    p(f"  correlacion entre lo caluroso que es un sitio y lo deprisa que se")
    p(f"  calienta: {r:+.3f}")
    q1, q4 = tabla.tx_verano_clim.quantile([0.25, 0.75])
    frescos = tabla[tabla.tx_verano_clim <= q1]
    calidos = tabla[tabla.tx_verano_clim >= q4]
    p(f"  el cuarto mas fresco  (clim {frescos.tx_verano_clim.mean():.1f} C): "
      f"{frescos.tx_verano_tend.median():+.3f} C/decada")
    p(f"  el cuarto mas caluroso (clim {calidos.tx_verano_clim.mean():.1f} C): "
      f"{calidos.tx_verano_tend.median():+.3f} C/decada")
    dif = calidos.tx_verano_tend.median() - frescos.tx_verano_tend.median()
    p(f"  diferencia: {dif:+.3f} C/decada")
    if abs(dif) < 0.05:
        p("  -> practicamente igual: la brecha NO se esta abriendo, y el orden")
        p("     entre sitios que hemos calculado deberia aguantar.")
    elif dif > 0:
        p(f"  -> los sitios calurosos se calientan mas deprisa. En 40 anios eso")
        p(f"     son {dif * 4:.1f} C mas de brecha, asi que la diferencia de hoy")
        p("     SUBESTIMA la de cuando vivas alli.")
    else:
        p("  -> los sitios frescos se calientan mas deprisa: la brecha se cierra.")
    # --- ¿o es solo altitud? -----------------------------------------------
    # "Fresco" y "alto" van juntos en Galicia, asi que la correlacion anterior
    # podria ser un efecto de la altitud disfrazado. Y en la montania hay otro
    # problema: alli habia muy pocas estaciones en los anios cincuenta, asi que
    # la interpolacion pudo cambiar de comportamiento al densificarse la red.
    # La prueba limpia es comparar costa e interior A IGUALDAD DE ALTURA.
    ruta_alta = os.path.join(BASE, "alta_resolucion.csv.gz")
    if os.path.exists(ruta_alta):
        from scipy.spatial import cKDTree
        a = pd.read_csv(ruta_alta, usecols=["lat", "lon", "altitud", "tierra"])
        a = a[a.tierra == 1]
        arb = cKDTree(a[["lon", "lat"]].values)
        _, idx = arb.query(tabla[["lon", "lat"]].values)
        tabla["altitud"] = a.altitud.values[idx]
        r_alt = float(np.corrcoef(tabla.altitud, tabla.tx_verano_tend)[0, 1])
        p(f"\n  ¿es solo altitud? correlacion tendencia-altitud: {r_alt:+.3f}")
        bajo = tabla[tabla.altitud < 400]
        if len(bajo) > 100:
            rb = float(np.corrcoef(bajo.tx_verano_clim, bajo.tx_verano_tend)[0, 1])
            b1, b4 = bajo.tx_verano_clim.quantile([0.25, 0.75])
            p(f"  solo por debajo de 400 m ({len(bajo)} celdas): "
              f"correlacion {rb:+.3f}")
            p(f"    cuarto fresco {bajo[bajo.tx_verano_clim <= b1].tx_verano_tend.median():+.3f}"
              f"   cuarto calido {bajo[bajo.tx_verano_clim >= b4].tx_verano_tend.median():+.3f}")
            p("  -> si la correlacion se mantiene o sube al quitar la montania,")
            p("     el efecto es de la cercania al mar, no de la altura.")
        tabla.to_csv(os.path.join(BASE, "rocio_tendencias.csv"), index=False,
                     encoding="utf-8")
    p("  (detalle celda a celda en rocio_tendencias.csv)")

    with open(os.path.join(BASE, "resumen_rocio.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\nDatos: AEMET, rejilla ROCIO_IBEB\n")
    print("\nEscrito resumen_rocio.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--descargar", action="store_true")
    ap.add_argument("--analizar", action="store_true")
    ap.add_argument("--var", choices=list(VARIABLES), default=None)
    ap.add_argument("--ventana", type=int, default=15)
    a = ap.parse_args()
    if a.explorar:
        explorar()
    elif a.descargar:
        descargar(a.var)
    elif a.analizar:
        analizar(a.ventana)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
