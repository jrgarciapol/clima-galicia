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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--describe", action="store_true",
                    help="volcar los ejes de un fichero de climatologia")
    ap.add_argument("--var", default="tasmaxp99,tasminNa20,tasmaxhwdmax",
                    help="variables a describir, separadas por comas")
    ap.add_argument("--prof", type=int, default=8)
    ap.add_argument("--tope", type=int, default=600,
                    help="maximo de peticiones al catalogo")
    args = ap.parse_args()

    if args.explorar:
        explorar(os.path.join(BASE, "adaptecca_exploracion.txt"),
                 prof=args.prof, max_peticiones=args.tope)
        return

    if args.describe:
        describe(os.path.join(BASE, "adaptecca_ejes.txt"),
                 variables=[v.strip() for v in args.var.split(",") if v.strip()])
        return

    sys.exit("Por ahora solo esta implementado --explorar.\n"
             "Lanza:  python 09_proyecciones.py --explorar\n"
             "y comparte adaptecca_exploracion.txt: con el inventario real se\n"
             "concreta que escenarios e indices bajar, sin adivinar nombres.")


if __name__ == "__main__":
    main()
