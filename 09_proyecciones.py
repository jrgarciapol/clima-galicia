"""PASO 9 - Proyecciones climaticas regionalizadas para Galicia (AdapteCCa).

Por que hace falta
------------------
El paso 8 ajusta una tendencia a las maximas observadas y la extrapola. Eso es
mejor que suponer clima quieto, pero sigue siendo una extrapolacion: supone que
lo que ha pasado en 30 anios continua igual otros 30. Y sus propias pruebas
demuestran que la tendencia por punto apenas se distingue del ruido.

Lo unico que sustituye de verdad a esa extrapolacion son las **proyecciones
climaticas**: modelos fisicos corridos bajo escenarios de emisiones, con su
horquilla de incertidumbre explicita.

La fuente
---------
El Visor de Escenarios de Cambio Climatico (AdapteCCa, de AEMET y el Ministerio)
publica proyecciones **regionalizadas para Espania a 5 km** -- mas finas que los
9 km de ERA5-Land -- via servidor THREDDS:

    https://escenarios.adaptecca.es/thredds/catalog/catalog.html

Incluye EURO-CORDEX (CMIP5, escenarios RCP4.5 y RCP8.5) y regionalizacion
estadistica de CMIP6 (SSP1-2.6, SSP2-4.5, SSP3-7.0, SSP5-8.5), con indices de
temperatura ya calculados: dias calidos, noches tropicales, olas de calor,
extremos. Al venir los indices hechos no hace falta bajar datos diarios.

Como se descarga
----------------
Este servidor ofrece OPeNDAP, no NetcdfSubset. La diferencia importa: con
OPeNDAP se abre el fichero remoto, se recorta a Galicia y **solo viajan por la
red los datos del recorte**. Un fichero de varios GB para toda Espania se queda
en unos pocos MB para Galicia. Por eso aqui se usa xarray contra la URL dodsC en
vez de descargar el fichero entero por HTTP.

Uso:
    python 09_proyecciones.py --explorar
        Reconocimiento. No descarga datos. Recorre el catalogo, lista los
        conjuntos, escenarios y variables que hay de verdad, y comprueba que
        OPeNDAP responde. EJECUTA ESTO PRIMERO y comparte el fichero.

    python 09_proyecciones.py --escenarios ssp245,ssp585
        Descarga de verdad, una vez sepamos que hay.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thredds  # noqa: E402

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
RAIZ = "https://escenarios.adaptecca.es/thredds"
CATALOGO = f"{RAIZ}/catalog/catalog.xml"

# Galicia, con margen. En estas rejillas lat/lon son regulares.
NORTE, SUR, OESTE, ESTE = 43.95, 41.70, -9.45, -6.60

# Que buscamos en los nombres. El modo --explorar imprime lo que hay de verdad.
INTERES = ("tasmax", "tasmin", "tas", "tx", "tn", "txx", "tnn", "su", "tr",
           "wsdi", "hwd", "hwn", "cdd", "hdd", "temperatura")

# Ramas que no pintan nada aqui. El catalogo cuelga Canarias y Andorra del mismo
# nivel que la Peninsula, y recorrerlas se come el presupuesto de peticiones.
FUERA = ("canarias", "andorra")


def prioridad(titulo, url):
    """Orden en que se visita cada rama. Menor numero, antes.

    El primer reconocimiento se hizo por anchura y a profundidad 5, y agoto las
    250 peticiones dentro de las ramas de observaciones sin llegar a tocar una
    sola de proyecciones: los 117 ficheros del inventario son TODOS
    observacionales. El catalogo es demasiado ancho para recorrerlo entero, asi
    que hay que decirle por donde empezar.
    """
    t = (titulo + " " + url).lower()
    if any(x in t for x in FUERA):
        return None                       # ni se encola
    p = 0
    if "proyecc" in t:
        p -= 40                           # es lo unico que falta por inventariar
    if "observaciones" in t:
        p += 20                           # ya lo tenemos del primer sondeo
    if "rejilla" in t:
        p -= 8                            # rejilla > estaciones: queremos el mapa
    if "cmip6" in t:
        p -= 4                            # mas moderno que CMIP5
    if "dato_diario" in t:
        p += 6                            # pesado; los indices anuales bastan
    if any(k in t for k in INTERES):
        p -= 3
    return p


def url_dods(url_path):
    return f"{RAIZ}/dodsC/{url_path}"


def url_http(url_path):
    return f"{RAIZ}/fileServer/{url_path}"


def explorar(destino, prof=5, max_peticiones=250):
    L = [f"Exploracion de AdapteCCa - {datetime.now():%Y-%m-%d %H:%M}",
         f"raiz: {CATALOGO}", ""]

    L.append("--- alcanzabilidad ---")
    for u in (CATALOGO, f"{RAIZ}/catalog/catalog.html"):
        try:
            r = thredds._get(u, intentos=1, timeout=90)
            L.append(f"  OK    {len(r.content):>9,} bytes  {u}")
        except thredds.ErrorThredds as e:
            L.append(f"  FALLA {str(e):>15s}  {u}")
    L.append("")

    # Se reutiliza el rastreador del paso 5, que ya sabe que la jerarquia de URL
    # no tiene por que coincidir con la del catalogo. Lo que cambia respecto al
    # primer sondeo es el ORDEN: por prioridad, no por anchura (ver prioridad()).
    L.append(f"--- recorrido del catalogo (profundidad {prof}, tope {max_peticiones}) ---")
    print(f"Recorriendo el catalogo. Hasta {max_peticiones} peticiones, "
          f"unos {max_peticiones * 1.5 / 60:.0f} min como mucho.", flush=True)
    traza, encontrados, vistos = [], [], set()
    monton = [(0, 0, CATALOGO, "raiz", 0)]
    orden, peticiones, saltadas = 0, 0, 0
    ficheros_por_rama = {}
    while monton and peticiones < max_peticiones:
        monton.sort()
        _, _, url, titulo, p = monton.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        peticiones += 1
        try:
            subs, fich = thredds.catalogo(url)
        except thredds.ErrorThredds as e:
            traza.append(f"  [{p}] {titulo}: ERROR {e}")
            continue
        traza.append(f"  [{p}] {titulo}: {len(subs)} subcatalogos, {len(fich)} ficheros")
        if fich:
            ficheros_por_rama[titulo] = fich[:8]
            encontrados.extend(fich)
        # Sin esto el recorrido parece colgado: son cientos de peticiones y
        # antes solo se veia la salida al final.
        print(f"  [{peticiones:3d}/{max_peticiones}] n{p} {titulo[:48]:48s} "
              f"{len(subs):3d} sub {len(fich):4d} fich  (total {len(encontrados)})",
              flush=True)
        for tit, sub in subs:
            if p >= prof:
                continue
            pr = prioridad(tit, sub)
            if pr is None:
                saltadas += 1
                continue
            orden += 1
            monton.append((pr, orden, sub, tit, p + 1))
    L.extend(traza)
    if saltadas:
        L.append(f"  ({saltadas} ramas de {'/'.join(FUERA)} no visitadas a proposito)")
    if peticiones >= max_peticiones:
        L.append(f"  (tope de {max_peticiones} peticiones alcanzado; "
                 f"quedaban {len(monton)} ramas por abrir)")
        L.append("  Si faltan proyecciones, repetir con --tope mas alto.")
    L.append("")

    # Resumen por rama, que es lo que de verdad hay que leer del fichero
    ramas = {}
    for _, up in encontrados:
        ramas["/".join(up.split("/")[:3])] = ramas.get("/".join(up.split("/")[:3]), 0) + 1
    L.append("--- ficheros por rama ---")
    for k in sorted(ramas):
        L.append(f"  {ramas[k]:5d}  {k}")
    L.append("")

    L.append(f"--- ficheros encontrados: {len(encontrados)} ---")
    for rama, fich in list(ficheros_por_rama.items())[:25]:
        L.append(f"  {rama}:")
        for nombre, up in fich:
            L.append(f"      {nombre}")
            L.append(f"        {up}")
    L.append("")

    # De los que suenan a temperatura, se abre uno por OPeNDAP para ver la malla
    cand = [(n, u) for n, u in encontrados
            if any(k in (n + u).lower() for k in INTERES)]
    L.append(f"--- candidatos de temperatura: {len(cand)} ---")
    for n, _ in cand[:40]:
        L.append(f"  {n}")
    L.append("")

    # Se prueba sobre una PROYECCION, no sobre lo primero que salga. En el
    # sondeo anterior el candidato elegido fue un fichero de observaciones y su
    # fallo de OPeNDAP no decia nada sobre lo que nos interesa bajar.
    proy = [(n, u) for n, u in cand if "proyecc" in u.lower()]
    if proy:
        cand = proy
        L.append(f"--- de ellos, {len(proy)} son proyecciones ---")
        for n, _ in proy[:40]:
            L.append(f"  {n}")
        L.append("")

    if cand:
        L.append("--- prueba de OPeNDAP sobre el primer candidato ---")
        nombre, up = cand[0]
        u = url_dods(up)
        L.append(f"  {u}")
        try:
            import xarray as xr

            ds = xr.open_dataset(u, decode_timedelta=False)
            L.append(f"  variables: {list(ds.data_vars)}")
            L.append(f"  dimensiones: {dict(ds.sizes)}")
            L.append(f"  coordenadas: {list(ds.coords)}")
            for c in ds.coords:
                v = ds[c].values
                try:
                    L.append(f"    {c}: {v.min()} .. {v.max()}  (n={v.size})")
                except Exception:  # noqa: BLE001
                    L.append(f"    {c}: {v[:3]} ... (n={v.size})")
            L.append("  -> OPeNDAP funciona: se puede recortar sin bajar el fichero entero")
        except Exception as e:  # noqa: BLE001
            L.append(f"  ERROR abriendo por OPeNDAP: {e.__class__.__name__}: {e}")
            L.append("")
            # Plan B: si OPeNDAP no sirve hay que bajar el fichero entero, y
            # entonces lo primero que hace falta saber es cuanto pesa.
            L.append("--- plan B: el fichero entero por HTTPServer ---")
            uh = url_http(up)
            L.append(f"  {uh}")
            try:
                import urllib.request

                pet = urllib.request.Request(uh, method="HEAD")
                with urllib.request.urlopen(pet, timeout=60) as r:
                    n = int(r.headers.get("Content-Length", 0))
                L.append(f"  responde: {n / 1e6:,.1f} MB por fichero")
                L.append(f"  -> los {len(cand)} candidatos serian "
                         f"{n * len(cand) / 1e9:,.1f} GB. Habra que elegir cuales.")
            except Exception as e2:  # noqa: BLE001
                L.append(f"  tampoco responde: {e2.__class__.__name__}: {e2}")
    L.append("")

    texto = "\n".join(L)
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(texto)
    print(texto[:9000])
    print(f"\nEscrito {destino}")
    json.dump([{"nombre": n, "urlPath": u} for n, u in encontrados],
              open(os.path.join(BASE, "adaptecca_ficheros.json"), "w"),
              indent=1, ensure_ascii=False)
    print(f"Inventario completo en adaptecca_ficheros.json ({len(encontrados)} entradas)")


# ---------------------------------------------------------------------------
# Descripcion fina de un fichero de climatologia
# ---------------------------------------------------------------------------
# Ruta regular, confirmada sobre el inventario del sondeo:
#   Climatologia/Temperatura/<var>/climatology_CMIP6_ESD-RegBA_<var>_<esc>.nc
RAMA_CLIM = ("peninsula/Proyecciones_CMIP6_en_rejilla/Climatologia/Temperatura/"
             "{v}/climatology_CMIP6_ESD-RegBA_{v}_{e}.nc")
ESCENARIOS = ("ssp126", "ssp245", "ssp370", "ssp585")

# Lo que de verdad responde a la pregunta del proyecto, y por que:
NUESTRAS = {
    "tasmaxp99":     "percentil 99 de la maxima: es literalmente nuestro tx_p99",
    "tasmaxmax":     "maxima absoluta del periodo",
    "tasmaxhwdmax":  "duracion maxima de ola de calor",
    "tasmax":        "maxima media, para el confort medio",
    "tasminNa20":    "noches por encima de 20 C: noches tropicales, absolutas",
    "cdd":           "grados-dia de refrigeracion: cuanto aire acondicionado",
    "tmean":         "media, para comparar con la climatologia observada",
}


def describe(destino, variables=None, escenario="ssp585"):
    """Abre un fichero por OPeNDAP y vuelca TODAS las etiquetas de sus ejes.

    Hace falta antes de escribir la descarga. El sondeo solo imprimio las tres
    primeras etiquetas de cada eje ('far_future', 'medium_future'...), y con eso
    no se puede seleccionar el verano ni el periodo de referencia sin adivinar.
    Adivinar nombres ya salio caro una vez, con el limite de 6 meses de AEMET.
    """
    import xarray as xr

    variables = variables or ["tasmaxp99"]
    L = [f"Descripcion de AdapteCCa - {datetime.now():%Y-%m-%d %H:%M}", ""]

    for v in variables:
        up = RAMA_CLIM.format(v=v, e=escenario)
        u = url_dods(up)
        L.append(f"=== {v} / {escenario} ===")
        L.append(f"  {u}")
        print(f"Abriendo {v}...", flush=True)
        try:
            ds = xr.open_dataset(u, decode_timedelta=False)
        except Exception as e:  # noqa: BLE001
            L.append(f"  ERROR: {e.__class__.__name__}: {e}")
            L.append("")
            continue

        for nv in ds.data_vars:
            a = ds[nv].attrs
            L.append(f"  variable {nv}: dims {ds[nv].dims}  "
                     f"units={a.get('units', '?')}  {a.get('long_name', '')}")
        L.append(f"  dimensiones: {dict(ds.sizes)}")

        for c in ds.coords:
            val = ds[c].values
            if val.dtype.kind in "SU" or val.size <= 24:
                etiquetas = [x.decode() if isinstance(x, bytes) else str(x)
                             for x in np.atleast_1d(val)]
                L.append(f"  {c} (n={val.size}): {etiquetas}")
            else:
                paso = float(np.diff(val).mean()) if val.size > 1 else 0.0
                L.append(f"  {c} (n={val.size}): {val.min():.3f} .. {val.max():.3f}"
                         f"  paso {paso:.4f}")

        # Cuanto costaria el recorte a Galicia, que es lo que decide si esto
        # se puede bajar entero o hay que elegir variables
        if "lat" in ds.coords and "lon" in ds.coords:
            la, lo = ds.lat.values, ds.lon.values
            nla = int(((la >= SUR) & (la <= NORTE)).sum())
            nlo = int(((lo >= OESTE) & (lo <= ESTE)).sum())
            otras = 1
            for d, n in ds.sizes.items():
                if d not in ("lat", "lon"):
                    otras *= n
            mb = nla * nlo * otras * len(ds.data_vars) * 4 / 1e6
            L.append(f"  recorte a Galicia: {nla} x {nlo} = {nla * nlo} celdas "
                     f"de {la.size * lo.size}  ({nla * nlo / (la.size * lo.size):.1%})")
            L.append(f"  -> {mb:,.1f} MB por fichero; "
                     f"{mb * len(NUESTRAS) * len(ESCENARIOS) / 1000:,.2f} GB "
                     f"si bajamos {len(NUESTRAS)} variables x {len(ESCENARIOS)} escenarios")

        # Un valor real, para confirmar unidades: si tasmaxp99 sale en kelvin
        # o el anomalo sale en absoluto, mejor enterarse ahora
        try:
            prin = list(ds.data_vars)[0]
            sub = ds[prin].sel(lat=slice(SUR, NORTE), lon=slice(OESTE, ESTE))
            m = float(np.nanmean(np.asarray(sub.values, dtype=float)))
            L.append(f"  media de {prin} sobre Galicia (todos los ejes): {m:,.2f}")
        except Exception as e:  # noqa: BLE001
            L.append(f"  no se pudo leer un valor: {e.__class__.__name__}: {e}")
        L.append("")
        ds.close()

    texto = "\n".join(L)
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(texto)
    print("\n" + texto)
    print(f"Escrito {destino}")


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
# Etiquetas confirmadas con --describe, no supuestas:
#   time_filter: Jan..Dec, DJF, JJA, MAM, SON, year
#   period:      reference, near_future, medium_future, far_future
#   member:      'average' + 11 modelos
FILTROS = ("JJA", "year")
PERIODOS = {"reference": "1971-2000", "near_future": "2011-2040",
            "medium_future": "2041-2070", "far_future": "2071-2100"}
DIR = os.path.join(BASE, "proyecciones")


def _txt(v):
    """Las etiquetas vienen como bytes en un array de numpy."""
    return [x.decode() if isinstance(x, bytes) else str(x) for x in np.atleast_1d(v)]


def _indices(etiquetas, quiero, eje):
    """Posiciones de 'quiero' dentro de 'etiquetas'. Aborta si falta alguna.

    Se aborta a proposito en vez de seguir con lo que haya: un eje que se
    selecciona mal no da error, da numeros. Es justo el tipo de fallo silencioso
    que ya nos ha costado un informe entero.
    """
    faltan = [q for q in quiero if q not in etiquetas]
    if faltan:
        raise SystemExit(
            f"El eje '{eje}' no tiene {faltan}. Lo que hay es: {etiquetas}\n"
            f"Vuelve a lanzar --describe: la estructura del fichero ha cambiado.")
    return [etiquetas.index(q) for q in quiero]


def baja_uno(var, esc, destino, intentos=4):
    """Un fichero: recorta a Galicia, resume los 11 modelos y escribe un CSV."""
    import pandas as pd
    import xarray as xr

    u = url_dods(RAMA_CLIM.format(v=var, e=esc))
    ds = None
    for i in range(intentos):
        try:
            ds = xr.open_dataset(u, decode_timedelta=False)
            break
        except Exception as e:  # noqa: BLE001
            espera = 5 * 2 ** i
            if i == intentos - 1:
                raise RuntimeError(f"{e.__class__.__name__}: {e}") from e
            print(f"    fallo ({e.__class__.__name__}), reintento en {espera} s",
                  flush=True)
            time.sleep(espera)

    tf = _txt(ds.time_filter.values)
    pe = _txt(ds.period.values)
    mi = _txt(ds.member.values)
    i_tf = _indices(tf, FILTROS, "time_filter")
    i_pe = _indices(pe, list(PERIODOS), "period")
    i_med = mi.index("average") if "average" in mi else 0
    i_mod = [k for k in range(len(mi)) if k != i_med]     # los 11 modelos

    sub = ds.isel(time_filter=i_tf, period=i_pe).sel(
        lat=slice(SUR, NORTE), lon=slice(OESTE, ESTE))

    filas = []
    lat, lon = sub.lat.values, sub.lon.values
    for sufijo in ("", "_anom"):
        nombre = var + sufijo
        if nombre not in sub.data_vars:
            continue
        a = np.asarray(sub[nombre].values, dtype=float)   # member,tf,period,lat,lon
        med = a[i_med]
        # Las celdas de mar son NaN en los 11 modelos, y reducirlas hace que
        # numpy avise por cada fichero ("All-NaN slice encountered"). No se
        # silencia el aviso: se reduce solo donde hay dato, que ademas es mas
        # rapido. Misma solucion que en el paso 13.
        mods = a[i_mod]
        hay = np.isfinite(mods).any(axis=0)
        p10 = np.full(med.shape, np.nan)
        p90 = np.full(med.shape, np.nan)
        if hay.any():
            p10[hay] = np.nanpercentile(mods[:, hay], 10, axis=0)
            p90[hay] = np.nanpercentile(mods[:, hay], 90, axis=0)
        for j, f in enumerate(FILTROS):
            for k, p in enumerate(PERIODOS):
                for ii in range(lat.size):
                    for jj in range(lon.size):
                        v = med[j, k, ii, jj]
                        if not np.isfinite(v):
                            continue        # mar y fuera de mascara
                        filas.append((round(float(lat[ii]), 3),
                                      round(float(lon[jj]), 3), f, p,
                                      "abs" if sufijo == "" else "anom",
                                      round(float(v), 3),
                                      round(float(p10[j, k, ii, jj]), 3),
                                      round(float(p90[j, k, ii, jj]), 3)))
    ds.close()

    t = pd.DataFrame(filas, columns=["lat", "lon", "filtro", "periodo", "tipo",
                                     "valor", "p10", "p90"])
    t.insert(0, "escenario", esc)
    t.insert(0, "variable", var)
    t.to_csv(destino, index=False)
    return len(t)


def descargar(variables=None, escenarios=None):
    variables = variables or list(NUESTRAS)
    escenarios = escenarios or list(ESCENARIOS)
    os.makedirs(DIR, exist_ok=True)

    tareas = [(v, e) for v in variables for e in escenarios]
    print(f"{len(tareas)} ficheros: {len(variables)} variables x "
          f"{len(escenarios)} escenarios.")
    print("Cada uno se recorta a Galicia por OPeNDAP: viaja el 2,6 % del fichero.\n")

    fallos = []
    for n, (v, e) in enumerate(tareas, 1):
        destino = os.path.join(DIR, f"{v}_{e}.csv")
        if os.path.exists(destino) and os.path.getsize(destino) > 0:
            print(f"[{n:2d}/{len(tareas)}] {v:14s} {e}  ya estaba", flush=True)
            continue
        print(f"[{n:2d}/{len(tareas)}] {v:14s} {e}  ...", end=" ", flush=True)
        t0 = time.time()
        try:
            filas = baja_uno(v, e, destino)
            print(f"{filas:,} filas en {time.time() - t0:.0f} s", flush=True)
        except SystemExit:
            raise
        except Exception as ex:  # noqa: BLE001
            print(f"FALLO: {ex}", flush=True)
            fallos.append((v, e, str(ex)))
            if os.path.exists(destino):
                os.remove(destino)     # nunca dejar un fichero a medias

    print(f"\nHecho. {len(tareas) - len(fallos)} de {len(tareas)}.")
    if fallos:
        print("Fallaron, se pueden reintentar volviendo a lanzar el comando:")
        for v, e, m in fallos:
            print(f"  {v} {e}: {m[:90]}")
    else:
        print("Ahora: python 09_proyecciones.py --analizar")


# ---------------------------------------------------------------------------
# Analisis
# ---------------------------------------------------------------------------
def _rho(a, b):
    """Correlacion de rangos (Spearman), sin depender de scipy."""
    import pandas as pd

    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return float("nan")
    ra = pd.Series(a[m]).rank().values
    rb = pd.Series(b[m]).rank().values
    # Si una de las dos series es constante la correlacion no existe. Sin este
    # guardia numpy divide por cero, avisa por pantalla y devuelve nan igual.
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def analizar():
    import pandas as pd

    if not os.path.isdir(DIR):
        sys.exit(f"No hay nada en {DIR}. Lanza primero --descargar.")
    trozos = [pd.read_csv(os.path.join(DIR, f))
              for f in sorted(os.listdir(DIR)) if f.endswith(".csv")]
    if not trozos:
        sys.exit(f"No hay CSV en {DIR}. Lanza primero --descargar.")
    d = pd.concat(trozos, ignore_index=True)

    salida = os.path.join(BASE, "proyecciones_galicia.csv.gz")
    d.to_csv(salida, index=False, compression="gzip")

    L = [f"Proyecciones AdapteCCa para Galicia - {datetime.now():%Y-%m-%d %H:%M}",
         "",
         f"{len(d):,} filas | {d.variable.nunique()} variables | "
         f"{d.escenario.nunique()} escenarios | "
         f"{d[['lat', 'lon']].drop_duplicates().shape[0]} celdas de 5 km",
         "Referencia 1971-2000. Horquilla p10-p90 sobre los 11 modelos.",
         ""]

    ab = d[d.tipo == "abs"]
    an = d[d.tipo == "anom"]

    # --- coherencia interna: la anomalia tiene que ser futuro - referencia ---
    L.append("=== comprobacion: anomalia == futuro - referencia ===")
    clave = ["variable", "escenario", "filtro", "lat", "lon"]
    ref = ab[ab.periodo == "reference"].set_index(clave).valor
    peor = 0.0
    for p in ("near_future", "medium_future", "far_future"):
        fa = ab[ab.periodo == p].set_index(clave).valor
        aa = an[an.periodo == p].set_index(clave).valor
        j = pd.concat({"fut": fa, "ref": ref, "anom": aa}, axis=1).dropna()
        if j.empty:
            continue
        err = (j.fut - j.ref - j.anom).abs()
        peor = max(peor, float(err.max()))
        L.append(f"  {p:15s} error maximo {err.max():.4f}  "
                 f"(mediana {err.median():.4f})")
    L.append("  ok: los dos caminos dan lo mismo" if peor < 0.05 else
             "  OJO: no cuadran; algo se esta seleccionando mal")
    L.append("")

    # --- cuanto sube cada indice ---
    L.append("=== cuanto cambia cada indice en verano (JJA) ===")
    L.append("mediana sobre las celdas de Galicia; entre parentesis, p10-p90 entre modelos")
    jja = an[an.filtro == "JJA"]
    for v in sorted(jja.variable.unique()):
        L.append(f"\n  {v}  ({NUESTRAS.get(v, '')})")
        L.append(f"    {'escenario':10s} {'2011-2040':>22s} {'2041-2070':>22s} "
                 f"{'2071-2100':>22s}")
        for e in sorted(jja.escenario.unique()):
            cel = []
            for p in ("near_future", "medium_future", "far_future"):
                g = jja[(jja.variable == v) & (jja.escenario == e)
                        & (jja.periodo == p)]
                if g.empty:
                    cel.append(f"{'-':>22s}")
                    continue
                cel.append(f"{g.valor.median():+7.2f} "
                           f"({g.p10.median():+.2f} a {g.p90.median():+.2f})".rjust(22))
            L.append(f"    {e:10s} " + " ".join(cel))
    L.append("")

    # --- ritmo implicito frente a lo observado ---
    L.append("=== el ritmo que proyectan, frente al que medimos ===")
    L.append("near_future (2011-2040, centro 2025) menos reference (1971-2000,")
    L.append("centro 1985) son 40 anios, asi que la anomalia dividida por 4 es")
    L.append("C/decada y se puede comparar con nuestras cifras.")
    g = jja[(jja.variable == "tasmax") & (jja.periodo == "near_future")]
    if not g.empty:
        for e in sorted(g.escenario.unique()):
            h = g[g.escenario == e]
            L.append(f"  {e}: {h.valor.median() / 4:+.2f} C/decada")
    L.append("  observado: ROCIO 1951-2022 +0,20 | AEMET 2011-2025 +1,13 | "
             "ERA5-Land 2011-2025 +1,31")
    L.append("")

    # --- aguanta el orden entre sitios? ---
    L.append("=== LA pregunta: aguanta el orden entre sitios? ===")
    L.append("correlacion de rangos entre el mapa de hoy y el de cada futuro.")
    L.append("1,00 seria 'el orden no cambia en absoluto'.")
    for v in ("tasmaxp99", "tasmax"):
        L.append(f"\n  {v}:")
        for e in sorted(ab.escenario.unique()):
            base = ab[(ab.variable == v) & (ab.escenario == e)
                      & (ab.filtro == "JJA") & (ab.periodo == "reference")]
            if base.empty:
                continue
            base = base.set_index(["lat", "lon"]).valor
            linea = []
            for p in ("near_future", "medium_future", "far_future"):
                fut = ab[(ab.variable == v) & (ab.escenario == e)
                         & (ab.filtro == "JJA") & (ab.periodo == p)]
                if fut.empty:
                    continue
                fut = fut.set_index(["lat", "lon"]).valor
                j = pd.concat({"a": base, "b": fut}, axis=1).dropna()
                linea.append(f"{p.split('_')[0]:7s} {_rho(j.a.values, j.b.values):.3f}")
            L.append(f"    {e:10s} " + "   ".join(linea))
    L.append("")

    # --- se abre la brecha? ---
    L.append("=== se abre la brecha entre sitios frescos y calurosos? ===")
    L.append("correlacion entre lo caluroso que es un sitio hoy y cuanto se")
    L.append("calienta. Positiva = los calurosos se calientan mas.")
    for e in sorted(ab.escenario.unique()):
        base = ab[(ab.variable == "tasmaxp99") & (ab.escenario == e)
                  & (ab.filtro == "JJA") & (ab.periodo == "reference")]
        anm = an[(an.variable == "tasmaxp99") & (an.escenario == e)
                 & (an.filtro == "JJA") & (an.periodo == "medium_future")]
        if base.empty or anm.empty:
            continue
        j = pd.concat({"clim": base.set_index(["lat", "lon"]).valor,
                       "delta": anm.set_index(["lat", "lon"]).valor},
                      axis=1).dropna()
        if j.empty:
            continue
        q = j.clim.quantile([0.25, 0.75])
        fresco = j[j.clim <= q.iloc[0]]
        calido = j[j.clim >= q.iloc[1]]
        L.append(f"  {e}: rho {_rho(j.clim.values, j.delta.values):+.3f} | "
                 f"cuarto fresco {fresco.clim.mean():.1f}C {fresco.delta.mean():+.2f} | "
                 f"cuarto calido {calido.clim.mean():.1f}C {calido.delta.mean():+.2f}")
    L.append("")

    # --- el sitio concreto ---
    L.append("=== los extremos de Galicia, hoy y en 2041-2070 ===")
    for e in ("ssp245", "ssp585"):
        base = ab[(ab.variable == "tasmaxp99") & (ab.escenario == e)
                  & (ab.filtro == "JJA") & (ab.periodo == "reference")]
        fut = ab[(ab.variable == "tasmaxp99") & (ab.escenario == e)
                 & (ab.filtro == "JJA") & (ab.periodo == "medium_future")]
        if base.empty or fut.empty:
            continue
        j = pd.concat({"hoy": base.set_index(["lat", "lon"]).valor,
                       "fut": fut.set_index(["lat", "lon"]).valor},
                      axis=1).dropna().reset_index()
        j["salto"] = j.fut - j.hoy
        L.append(f"\n  {e} -- las 5 celdas mas frescas de hoy:")
        for _, r in j.nsmallest(5, "hoy").iterrows():
            L.append(f"    {r.lat:.2f} {r.lon:.2f}   hoy {r.hoy:5.1f}  "
                     f"2041-2070 {r.fut:5.1f}  ({r.salto:+.1f})")
        L.append(f"  {e} -- las 5 mas calurosas de hoy:")
        for _, r in j.nlargest(5, "hoy").iterrows():
            L.append(f"    {r.lat:.2f} {r.lon:.2f}   hoy {r.hoy:5.1f}  "
                     f"2041-2070 {r.fut:5.1f}  ({r.salto:+.1f})")
        L.append(f"  rango entre la mas fresca y la mas calurosa: "
                 f"hoy {j.hoy.max() - j.hoy.min():.1f} C, "
                 f"en 2041-2070 {j.fut.max() - j.fut.min():.1f} C")
    L.append("")

    # --- aplicar el delta a nuestro ranking de 1 km ---
    ruta_rank = os.path.join(BASE, "ranking_60_40.csv")
    if os.path.exists(ruta_rank):
        L.append("=== nuestro ranking de 1 km, con el delta encima ===")
        r = pd.read_csv(ruta_rank)
        for e in sorted(ab.escenario.unique()):
            anm = an[(an.variable == "tasmaxp99") & (an.escenario == e)
                     & (an.filtro == "JJA") & (an.periodo == "medium_future")]
            if anm.empty:
                continue
            # vecino mas proximo: la rejilla es de 0,05 grados, asi que basta
            # con redondear a la celda, sin arbol de busqueda
            cl = anm.groupby([anm.lat.round(3), anm.lon.round(3)]).valor.mean()
            latg = np.array(sorted({k[0] for k in cl.index}))
            long_ = np.array(sorted({k[1] for k in cl.index}))
            ila = np.abs(r.lat.values[:, None] - latg[None]).argmin(1)
            ilo = np.abs(r.lon.values[:, None] - long_[None]).argmin(1)
            delta = np.array([cl.get((latg[a], long_[b]), np.nan)
                              for a, b in zip(ila, ilo)])
            r[f"d_{e}"] = delta
            r[f"tx_p99_{e}"] = r.tx_p99_1km + delta
        cols = [c for c in r.columns if c.startswith("tx_p99_ssp")]
        if cols:
            hoy = r.nsmallest(20, "tx_p99_1km")
            L.append(f"  top 20 de hoy: {hoy.tx_p99_1km.min():.1f} a "
                     f"{hoy.tx_p99_1km.max():.1f} C")
            for c in cols:
                fut = r.nsmallest(20, c)
                comunes = len(set(map(tuple, hoy[["lat", "lon"]].values))
                              & set(map(tuple, fut[["lat", "lon"]].values)))
                L.append(f"  {c[7:]}: {comunes} de los 20 mejores de hoy siguen "
                         f"en el top 20; rho global "
                         f"{_rho(r.tx_p99_1km.values, r[c].values):.3f}")
            r.to_csv(os.path.join(BASE, "ranking_con_proyeccion.csv"), index=False)
            L.append("  escrito ranking_con_proyeccion.csv")
    else:
        L.append("(no esta ranking_60_40.csv, se salta el cruce con el 1 km)")
    L.append("")

    L.append("=== limite que no se puede saltar ===")
    L.append("AdapteCCa no publica ningun indice de confort con humedad: ni")
    L.append("humidex, ni temperatura aparente, ni bulbo humedo. El 40 % del")
    L.append("criterio no tiene proyeccion, solo observacion. Lo que hay aqui")
    L.append("proyecta el 60 % de picos extremos, que es la parte que pesa mas,")
    L.append("pero conviene no presentarlo como si cubriera el criterio entero.")

    texto = "\n".join(L)
    with open(os.path.join(BASE, "resumen_proyecciones.txt"), "w",
              encoding="utf-8") as fh:
        fh.write(texto)
    print(texto)
    print(f"\nEscritos resumen_proyecciones.txt y {os.path.basename(salida)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--descargar", action="store_true")
    ap.add_argument("--describe", action="store_true",
                    help="volcar los ejes de un fichero de climatologia")
    ap.add_argument("--analizar", action="store_true")
    ap.add_argument("--var", default=None,
                    help="variables separadas por comas (por defecto, las 7)")
    ap.add_argument("--esc", default=",".join(ESCENARIOS),
                    help="escenarios separados por comas")
    ap.add_argument("--prof", type=int, default=8)
    ap.add_argument("--tope", type=int, default=600,
                    help="maximo de peticiones al catalogo")
    args = ap.parse_args()

    if args.explorar:
        explorar(os.path.join(BASE, "adaptecca_exploracion.txt"),
                 prof=args.prof, max_peticiones=args.tope)
        return

    pedidas = ([v.strip() for v in args.var.split(",") if v.strip()]
               if args.var else None)

    if args.describe:
        describe(os.path.join(BASE, "adaptecca_ejes.txt"),
                 variables=pedidas or ["tasmaxp99", "tasminNa20", "tasmaxhwdmax"])
        return

    if args.descargar:
        descargar(variables=pedidas,
                  escenarios=[x.strip() for x in args.esc.split(",") if x.strip()])
        return

    if args.analizar:
        analizar()
        return

    sys.exit("Elige un modo:\n"
             "  --explorar    recorrer el catalogo (ya hecho)\n"
             "  --describe    ver los ejes de un fichero (ya hecho)\n"
             "  --descargar   bajar los 28 recortes de Galicia\n"
             "  --analizar    responder si el ranking aguanta")


if __name__ == "__main__":
    main()
