"""PASO 5 - WRF de MeteoGalicia (1-4 km) restringido a los dias que importan.

La idea: bajar los 15 anios completos del archivo WRF son cientos de gigas y
varios dias de descarga. Pero como el criterio es *evitar episodios de calor
extremo*, los dias calidos son literalmente los unicos que aportan informacion.
Asi que este paso:

  1. Lee los NetCDF de ERA5-Land del paso 1 y elige los N dias mas calidos de
     cada verano sobre Galicia.
  2. Descarga del THREDDS de MeteoGalicia solo esos dias, recortados a Galicia
     y solo con las variables necesarias.

Con 40 dias por anio y 15 anios son 600 dias en vez de 5.500: entre un 5 % y un
10 % del volumen, sin perder nada relevante para la pregunta.

Uso:
    python 05_wrf_dias_calidos.py --explorar
        Reconocimiento: no descarga nada. Recorre el catalogo, deduce las rutas
        y escribe wrf_exploracion.txt. EJECUTA ESTO PRIMERO y comparte el
        fichero: el catalogo de MeteoGalicia cambia y conviene verlo antes.

    python 05_wrf_dias_calidos.py --dias 40 --desde 2011
        Descarga de verdad.

    python 05_wrf_dias_calidos.py --conjunto modelos/WRF_ARW_1KM_HIST --dias 40
        Fuerza un conjunto concreto en vez de elegirlo automaticamente.

Servidor
--------
MeteoGalicia movio el THREDDS: `mandeo.meteogalicia.es` devuelve HTTP 502 y el
servicio vivo es `thredds.meteogalicia.gal`. El script prueba los dos y usa el
que responda; con GAL_THREDDS=<url> se fuerza uno concreto.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thredds  # noqa: E402

# GAL_BASE permite redirigir entradas y salidas a otro directorio.
# Lo usan las pruebas para no tocar jamas tus descargas reales.
BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR_WRF = os.path.join(BASE, "wrf")
BBOX = (43.95, -9.45, 41.70, -6.60)  # norte, oeste, sur, este

# Nombres candidatos de las variables en los ficheros de MeteoGalicia.
# El modo --explorar imprime los reales; se filtran contra esa lista.
VARS_CANDIDATAS = ["temp", "T2", "t2m", "temperature", "rh", "RH2", "rh2",
                   "dewpoint", "td2"]


# ---------------------------------------------------------------------------
# 1. Dias calidos a partir de ERA5-Land
# ---------------------------------------------------------------------------

def serie_galicia(fuente="auto"):
    """Tmax media de Galicia dia a dia. Devuelve (serie, de_donde_sale).

    Dos fuentes posibles, y da igual cual:

      malla       diarios_galicia.nc, la cache de ERA5-Land del paso 2.
      estaciones  estaciones_diario.csv, la red de MeteoGalicia del paso 3.

    Aqui no se esta midiendo nada, solo *ordenando* los dias para quedarse con
    los mas calurosos. Para eso las estaciones valen exactamente igual que la
    malla: un dia de ola de calor lo es en toda Galicia a la vez. Poder usar las
    estaciones permite bajar el WRF sin esperar a que termine el Copernicus, que
    es el camino critico.
    """
    cache = os.path.join(BASE, "diarios_galicia.nc")
    csv = os.path.join(BASE, "estaciones_diario.csv")

    if fuente in ("auto", "malla") and os.path.exists(cache):
        import xarray as xr
        ds = xr.open_dataset(cache)
        if "tmax" not in ds:
            sys.exit(f"{cache} no tiene la variable tmax ({list(ds.data_vars)})")
        da = ds["tmax"]
        media = da.mean(dim=[d for d in da.dims if d != "time"], skipna=True)
        s = pd.Series(media.values,
                      index=pd.DatetimeIndex(da.time.values).normalize())
        return s, "malla ERA5-Land"

    if fuente in ("auto", "estaciones") and os.path.exists(csv):
        d = pd.read_csv(csv, parse_dates=["fecha"], usecols=["fecha", "tmax"])
        # mediana, no media: entran y salen estaciones a lo largo de los anios y
        # la media saltaria al cambiar la composicion de la red
        s = d.dropna(subset=["tmax"]).groupby("fecha").tmax.median()
        s.index = pd.DatetimeIndex(s.index).normalize()
        return s, "estaciones de MeteoGalicia"

    sys.exit("No hay ni diarios_galicia.nc (pasos 1-2) ni estaciones_diario.csv "
             "(paso 3). Ejecuta alguno de los dos antes.")


def dias_calidos(por_anio=40, desde=None, hasta=None, meses=(5, 6, 7, 8, 9),
                 fuente="auto"):
    """Los `por_anio` dias mas calidos de cada anio, por Tmax media de Galicia."""
    s, origen = serie_galicia(fuente)
    print(f"dias calidos elegidos a partir de: {origen} "
          f"({s.index.year.min()}-{s.index.year.max()})")
    s = s[s.index.month.isin(meses)]
    if desde:
        s = s[s.index.year >= desde]
    if hasta:
        s = s[s.index.year <= hasta]

    elegidos = []
    for a, sub in s.groupby(s.index.year):
        elegidos.append(sub.nlargest(min(por_anio, len(sub))))
    fuera = pd.concat(elegidos).sort_index()
    return fuera


# ---------------------------------------------------------------------------
# 2. Descubrimiento del catalogo
# ---------------------------------------------------------------------------

def explorar(destino, prof=4, max_peticiones=200):
    L = [f"Exploracion del THREDDS de MeteoGalicia - {datetime.now():%Y-%m-%d %H:%M}"]

    # --- 0) que host esta vivo? ---------------------------------------------
    L.append("--- eleccion de servidor ---")
    raiz, estados = thredds.detecta_host()
    for h, e in estados:
        L.append(f"  {e:24s} {h}")
    L.append(f"  en uso: {raiz}")
    L.append("")

    # --- 1) el servidor responde siquiera? ---------------------------------
    L.append("--- alcanzabilidad ---")
    for u in (thredds.CATALOGO_RAIZ, f"{thredds.RAIZ}/catalog.html",
              f"{thredds.RAIZ}/catalog/modelos/catalog.xml"):
        try:
            r = thredds._get(u, intentos=1, timeout=60)
            L.append(f"  OK    {len(r.content):>9,} bytes  {u}")
        except thredds.ErrorThredds as e:
            L.append(f"  FALLA {str(e):>15s}  {u}")
    L.append("")

    # --- 1) sondeo directo ---------------------------------------------------
    # El recorrido del catalogo puede fallar entero y aun asi ser posible
    # descargar, si se conoce una ruta concreta. Esto lo comprueba por separado:
    # es el diagnostico que de verdad decide si el paso 5 puede funcionar.
    L.append("--- sondeo de rutas concretas ---")
    for rel in ("catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml",
                "catalog/modelos/WRF_ARW_1KM_HIST/catalog.html",
                "catalog/modelos/catalog.html",
                "catalog/catalog.xml"):
        u = f"{thredds.RAIZ}/{rel}"
        try:
            subs, fich = thredds.catalogo(u)
            L.append(f"  OK    {len(subs):>4} subcat. {len(fich):>4} fich.  {rel}")
            for t, x in (subs[:3] + subs[-3:] if len(subs) > 6 else subs)[:6]:
                L.append(f"          sub: {t[:38]:38s} {x}")
            for t, x in fich[:3]:
                L.append(f"          fich: {x}")
        except thredds.ErrorThredds as e:
            L.append(f"  FALLA {str(e):>15s}                {rel}")
    L.append("")

    # --- 2) que dice el catalogo de un dia concreto --------------------------
    # Aqui se acaban las adivinanzas: el catalogo de un dia declara el urlPath
    # exacto de cada fichero y las bases de todos los servicios (NCSS, OPeNDAP,
    # descarga directa). Se vuelca tal cual para poder leerlo.
    L.append("--- catalogo de un dia, en crudo ---")
    dia_url = None
    try:
        subs_c, _ = thredds.catalogo(
            f"{thredds.RAIZ}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml")
        fechas = [(t, u) for t, u in subs_c if t.strip().isdigit()]
        if fechas:
            dia_url = fechas[0][1]
    except thredds.ErrorThredds as e:
        L.append(f"  no se pudo listar el conjunto: {e}")

    servs, ficheros_dia = {}, []
    if dia_url:
        L.append(f"  {dia_url}")
        try:
            crudo = thredds._get(dia_url).content.decode("utf-8", "replace")
            L.append("  " + "\n  ".join(crudo[:2500].splitlines()))
        except thredds.ErrorThredds as e:
            L.append(f"  ERROR {e}")
        servs = thredds.servicios(dia_url)
        try:
            _, ficheros_dia = thredds.catalogo(dia_url)
        except thredds.ErrorThredds:
            pass
        L.append(f"  servicios declarados: {servs or 'ninguno'}")
        L.append(f"  ficheros            : {[u for _, u in ficheros_dia][:4]}")
    L.append("")

    L.append("--- NCSS sobre un fichero conocido ---")
    candidatos = [u for _, u in ficheros_dia[:2]]
    # ojo al orden: el `id` que sale del HTML no lleva el prefijo `modelos/`,
    # pero la ruta real de los servicios si lo lleva
    conocido = ("WRF_ARW_1KM_HIST/20260727/"
                "wrf_arw_det_history_d02_20260727_0000.nc4")
    candidatos += [f"modelos/{conocido}", conocido]
    base_ncss = servs.get("netcdfsubset") or servs.get("ncss")
    L.append(f"  base NCSS declarada: {base_ncss or '(ninguna, se prueban las habituales)'}")
    info = None
    for up in dict.fromkeys(candidatos):
        errores = []
        info = thredds.describe(up, base=base_ncss, errores=errores)
        if info:
            L.append(f"  OK  {up}")
            L.append(f"    endpoint : {info['endpoint']}")
            L.append(f"    bbox     : {info['bbox']}")
            L.append(f"    ejes     : {info['ejes']}")
            L.append(f"    variables ({len(info['variables'])}): "
                     f"{', '.join(info['variables'])}")
            break
        L.append(f"  sin NCSS para {up}")
        for e in errores:
            L.append(f"      {e}")
    if not info and servs:
        L.append("  -> el NCSS no responde; los planes B y C son estos servicios:")
        for t, b in servs.items():
            L.append(f"      {t:14s} {b}")
    L.append("")

    # --- OPeNDAP: el plan B, y el que probablemente use el paso 5 ------------
    L.append("--- OPeNDAP sobre ese mismo fichero ---")
    base_dods = servs.get("opendap")
    if not base_dods:
        L.append("  el catalogo no declara OPeNDAP en este nodo")
    else:
        up = candidatos[0] if candidatos else f"modelos/{conocido}"
        u = base_dods.rstrip("/") + "/" + up.lstrip("/")
        L.append(f"  {u}")
        try:
            import xarray as xr
            with xr.open_dataset(u) as d:
                L.append(f"  dimensiones: {dict(d.sizes)}")
                L.append(f"  coordenadas: {list(d.coords)}")
                L.append(f"  variables ({len(d.data_vars)}): "
                         f"{', '.join(sorted(d.data_vars))}")
                for v in ("temp", "rh", "T2", "t2m"):
                    if v in d.variables:
                        L.append(f"    {v}: dims={d[v].dims} "
                                 f"unidades={d[v].attrs.get('units', '?')}")
                mb_total = sum(x.size * x.dtype.itemsize
                               for x in d.data_vars.values()) / 1e6
                L.append(f"  tamanio completo del fichero: ~{mb_total:,.0f} MB "
                         f"(por eso no se baja entero)")
        except Exception as e:  # noqa: BLE001
            L.append(f"  ERROR {e.__class__.__name__}: {str(e)[:300]}")
    L.append("")

    # --- 3) recorrido del catalogo ------------------------------------------
    L.append(f"--- recorrido del catalogo (profundidad {prof}) ---")
    traza = []
    try:
        conjuntos = thredds.descubre_wrf(max_prof=prof, max_peticiones=max_peticiones,
                                         traza=traza)
    except thredds.ErrorThredds as e:
        L.append(f"  ERROR al recorrer: {e}")
        conjuntos = []
    L.extend(traza)
    L.append("")

    L.append(f"--- conjuntos con 'wrf' en el nombre: {len(conjuntos)} ---")
    for nombre, url in conjuntos:
        L.append(f"  {nombre[:45]:45s} {url}")
    L.append("")

    # --- 4) detalle de cada conjunto ----------------------------------------
    for nombre, url in conjuntos[:12]:
        L.append(f"--- {nombre} ---")
        L.append(f"  url: {url}")
        # Cuanto archivo hay es lo primero que hay que saber: un conjunto de
        # 1 km con solo 3 anios no sirve para una climatologia de 15.
        try:
            rf = thredds.rango_fechas(url)
            if rf:
                L.append(f"  archivo         : {rf['n']} fechas, "
                         f"{rf['primera']} .. {rf['ultima']}")
                L.append(f"  anios           : {', '.join(rf['anios'])}")
            else:
                L.append("  archivo         : no organizado por fechas en este nivel")
        except thredds.ErrorThredds as e:
            L.append(f"  archivo         : ERROR {e}")
        try:
            pl = thredds.plantilla_desde_ejemplo(url)
            L.append(f"  patron_catalogo : {pl['patron_catalogo']}")
            L.append(f"  patron_fichero  : {pl['patron_fichero']}")
            L.append(f"  ejemplo         : {pl['ejemplo']}")
            L.append(f"  recorrido       : {pl['recorrido']}")
            sv = thredds.servicios(pl["url_hoja"]) or thredds.servicios(url)
            L.append(f"  servicios       : {sv or 'no declarados en este nodo'}")
            errs = []
            info = thredds.describe(pl["ejemplo"], errores=errs,
                                    base=sv.get("netcdfsubset") or sv.get("ncss"))
            if info:
                L.append(f"  endpoint NCSS   : {info['endpoint']}")
                L.append(f"  bbox            : {info['bbox']}")
                L.append(f"  ejes            : {info['ejes']}")
                L.append(f"  variables ({len(info['variables'])}): "
                         f"{', '.join(info['variables'][:60])}")
            else:
                L.append("  no se pudo describir el fichero por NCSS:")
                for e in errs[:6]:
                    L.append(f"      {e}")
        except thredds.ErrorThredds as e:
            L.append(f"  ERROR: {e}")
        L.append("")

    texto = "\n".join(L)
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(texto)
    print(texto[:8000])
    print(f"\nEscrito {destino}")


def elige_conjunto(conjuntos):
    """Prefiere el archivo historico de mayor resolucion disponible."""
    def puntua(par):
        n = (par[0] + " " + par[1]).lower()
        p = 0
        if "hist" in n:
            p += 100          # archivo historico, no la pasada operativa
        if "1km" in n or "1_km" in n:
            p += 50
        elif "d03" in n:
            p += 40
        elif "4km" in n or "d02" in n:
            p += 30
        elif "12km" in n or "d01" in n:
            p += 10
        if "novo" in n or "new" in n:
            p += 5
        # el propio catalogo marca uno de los conjuntos de 1 km como
        # DEPRECATED; no tiene sentido montar el analisis sobre el
        if "deprecated" in n or "obsolet" in n:
            p -= 200
        return p
    return max(conjuntos, key=puntua)


# ---------------------------------------------------------------------------
# 3. Descarga
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--prof", type=int, default=4, help="profundidad del recorrido")
    ap.add_argument("--dias", type=int, default=40, help="dias calidos por anio")
    ap.add_argument("--desde", type=int, default=None)
    ap.add_argument("--hasta", type=int, default=None)
    ap.add_argument("--conjunto", default=None,
                    help="conjunto a forzar: ruta corta (modelos/WRF_ARW_1KM_HIST) "
                         "o URL completa del catalogo")
    ap.add_argument("--stride", type=int, default=1, help="1 = resolucion nativa")
    ap.add_argument("--via", choices=["auto", "ncss", "opendap"], default="auto",
                    help="auto: NCSS si responde, OPeNDAP si no")
    ap.add_argument("--estaticos", action="store_true",
                    help="descarga solo los campos fijos (topografia y usos del "
                         "suelo). Una peticion; hace falta para separar tierra "
                         "de mar y de embalses")
    ap.add_argument("--dominio", default="d02",
                    help="que dominio del modelo, cuando el dia publica varios "
                         "(en WRF_ARW_1KM_HIST: d02 = 1 km, d01 = 5 km)")
    ap.add_argument("--fuente", choices=["auto", "malla", "estaciones"],
                    default="auto",
                    help="de donde salen los dias calidos (por defecto, la malla "
                         "si existe y si no las estaciones)")
    ap.add_argument("--max-dias", type=int, default=None, help="tope de seguridad")
    args = ap.parse_args()

    os.makedirs(DIR_WRF, exist_ok=True)

    if args.explorar:
        explorar(os.path.join(BASE, "wrf_exploracion.txt"), prof=args.prof)
        return

    raiz, estados = thredds.detecta_host()
    for h, e in estados:
        print(f"  {e:24s} {h}")
    if not any("OK" in e or "forzado" in e for _, e in estados):
        sys.exit("Ningun servidor THREDDS responde. Lanza --explorar para el detalle.")
    print(f"servidor: {raiz}\n")

    # --- que conjunto usamos -------------------------------------------------
    if args.conjunto:
        # Se admite tanto la URL completa del catalogo como la ruta corta
        # (modelos/WRF_ARW_1KM_HIST). plantilla_desde_ejemplo necesita una URL.
        ruta = args.conjunto
        if not ruta.startswith("http"):
            ruta = f"{thredds.RAIZ}/catalog/{ruta.strip('/')}/catalog.xml"
        elif not ruta.endswith(".xml"):
            ruta = ruta.rstrip("/") + "/catalog.xml"
        nombre = args.conjunto.rstrip("/").rsplit("/", 1)[-1]
        print(f"Conjunto forzado: {ruta}")
    else:
        conjuntos = thredds.descubre_wrf(max_prof=args.prof)
        if not conjuntos:
            sys.exit("No se encontro ningun conjunto WRF. Lanza --explorar.")
        nombre, ruta = elige_conjunto(conjuntos)
        print(f"Conjunto elegido automaticamente: {nombre}  ({ruta})")
        print("Si no es el que quieres, usa --conjunto\n")

    plantilla = thredds.plantilla_desde_ejemplo(ruta, prefiere=args.dominio)
    print(f"patron: {plantilla['patron_catalogo']}/{plantilla['patron_fichero']}")
    if "%Y" not in plantilla["patron_catalogo"] + plantilla["patron_fichero"]:
        sys.exit(
            f"El conjunto elegido no es un archivo por fechas (patron "
            f"'{plantilla['patron_fichero']}'). Los conjuntos 'fmrc'/'latest' son "
            f"la pasada operativa mas reciente, no sirven. Usa --conjunto "
            f"modelos/WRF_ARW_1KM_HIST.")

    # Las bases de los servicios las declara el propio catalogo; no se adivinan.
    servs = thredds.servicios(plantilla["url_hoja"]) or thredds.servicios(ruta)
    base_ncss = servs.get("netcdfsubset") or servs.get("ncss")
    base_dods = servs.get("opendap")
    print(f"servicios declarados: {servs or 'ninguno'}")

    errores = []
    info = thredds.describe(plantilla["ejemplo"], base=base_ncss, errores=errores)
    via = args.via
    if via == "auto":
        via = "ncss" if info else "opendap"
    if via == "ncss" and not info:
        for e in errores:
            print(f"  {e}")
        sys.exit("El NCSS no describe el fichero. Prueba --via opendap, o --explorar.")
    if via == "opendap" and not base_dods:
        sys.exit("El catalogo no declara OPeNDAP. Usa --via ncss.")

    if info:
        disponibles = info["variables"]
    else:
        # sin NCSS no hay descripcion previa; se mira el propio fichero por DAP
        import xarray as xr
        print("NCSS no disponible; leyendo la cabecera por OPeNDAP ...")
        for e in errores[:4]:
            print(f"  {e}")
        with xr.open_dataset(base_dods.rstrip("/") + "/" + plantilla["ejemplo"]) as d:
            disponibles = sorted(d.data_vars)
    variables = [v for v in disponibles
                 if v in VARS_CANDIDATAS or v.lower() in
                 {c.lower() for c in VARS_CANDIDATAS}]
    if not variables:
        print(f"Variables disponibles: {disponibles}")
        sys.exit("Ninguna variable candidata. Revisa VARS_CANDIDATAS en este fichero.")
    print(f"via: {via}")
    print(f"variables a descargar: {variables}")
    print(f"endpoint: {info['endpoint'] if info else base_dods}\n")

    # --- campos fijos: topografia y usos del suelo ---------------------------
    # Sin esto el analisis rankea el oceano y los embalses como "los sitios mas
    # frescos de Galicia", que es cierto y completamente inutil.
    ESTATICAS = ["topo", "land_use", "lsmask", "landmask", "HGT", "LU_INDEX"]
    est_disp = [v for v in disponibles if v in ESTATICAS]
    ruta_est = os.path.join(DIR_WRF, "estaticos.nc")
    if est_disp and not os.path.exists(ruta_est):
        print(f"Campos fijos ({', '.join(est_disp)}) ...")
        rel = plantilla["ejemplo"]
        try:
            # sin filtro temporal: son campos sin tiempo, o con uno solo
            thredds.descarga_ncss(rel, ruta_est, est_disp, BBOX,
                                  base=base_ncss, stride=args.stride)
            print(f"  wrf/estaticos.nc  {os.path.getsize(ruta_est) / 1e6:.1f} MB\n")
        except (thredds.ErrorThredds, OSError) as e:
            print(f"  no se pudieron descargar: {e}\n")
    elif not est_disp:
        print(f"Aviso: no hay campos fijos entre {disponibles[:8]}...; "
              f"el paso 6 no podra separar tierra de agua\n")

    if args.estaticos:
        print("Hecho. Ahora: python 06_alta_resolucion.py")
        return

    # --- que dias --------------------------------------------------------------
    dias = dias_calidos(args.dias, args.desde, args.hasta, fuente=args.fuente)

    # El archivo no cubre todo el periodo: WRF_ARW_1KM_HIST empieza el
    # 2021-09-03. Pedir dias anteriores son 404 garantizados, y una pantalla
    # llena de FALLO que parece una averia y no lo es.
    rf = None
    try:
        rf = thredds.rango_fechas(ruta)
    except thredds.ErrorThredds:
        pass
    if rf:
        ini = pd.Timestamp(rf["primera"])
        fin_arch = pd.Timestamp(rf["ultima"])
        fuera = dias.index[(dias.index < ini) | (dias.index > fin_arch)]
        if len(fuera):
            print(f"El archivo va de {ini:%Y-%m-%d} a {fin_arch:%Y-%m-%d}: "
                  f"descarto {len(fuera)} dias fuera de rango "
                  f"({fuera.min():%Y-%m-%d} .. {fuera.max():%Y-%m-%d})")
            dias = dias[(dias.index >= ini) & (dias.index <= fin_arch)]
        # los dias sueltos que falten dentro del rango si se intentan: el
        # catalogo lista la carpeta, pero puede no tener el dominio pedido
        disponibles = {t.strip() for t, _ in thredds.catalogo(ruta)[0]}
        if disponibles:
            hay = dias.index.strftime("%Y%m%d").isin(disponibles)
            if (~hay).any():
                print(f"  y {(~hay).sum()} dias que el catalogo no lista")
                dias = dias[hay]
    if not len(dias):
        sys.exit("No queda ningun dia que descargar.")
    print(f"quedan {len(dias)} dias\n")
    if args.max_dias:
        dias = dias.nlargest(args.max_dias).sort_index()
    print(f"{len(dias)} dias calidos seleccionados "
          f"({dias.index.year.min()}-{dias.index.year.max()}), "
          f"Tmax media de Galicia entre {dias.min():.1f} y {dias.max():.1f} C\n")
    dias.rename("tmax_media_galicia").to_csv(os.path.join(BASE, "dias_calidos.csv"))

    manifiesto = {"conjunto": ruta, "plantilla": plantilla, "variables": variables,
                  "via": via, "endpoint": info["endpoint"] if info else base_dods,
                  "base_ncss": base_ncss, "base_dods": base_dods,
                  "servicios": servs, "bbox": BBOX, "stride": args.stride}
    with open(os.path.join(BASE, "wrf_manifiesto.json"), "w") as fh:
        json.dump(manifiesto, fh, indent=2, ensure_ascii=False)

    # --- descarga --------------------------------------------------------------
    ok, fallos, cacheados = 0, [], 0
    for n, fecha in enumerate(dias.index, 1):
        rel = fecha.strftime(plantilla["patron_catalogo"])
        fich = fecha.strftime(plantilla["patron_fichero"])
        url_path = f"{rel}/{fich}"
        destino = os.path.join(DIR_WRF, f"wrf_{fecha:%Y%m%d}.nc")
        # solo las 24 h del propio dia: la pasada trae 72-96 h, y los alcances
        # largos no son comparables con los cortos
        ini, fin_ = f"{fecha:%Y-%m-%d}T00:00:00Z", f"{fecha:%Y-%m-%d}T23:00:00Z"
        try:
            if via == "opendap":
                r = thredds.descarga_opendap(
                    url_path, destino, variables, BBOX, base_dods,
                    inicio=ini, fin=fin_, stride=args.stride)
            else:
                r = thredds.descarga_ncss(
                    url_path, destino, variables, BBOX, endpoint=None,
                    base=base_ncss, stride=args.stride, inicio=ini, fin=fin_)
            if r == "cache":
                cacheados += 1
            else:
                ok += 1
            estado = "cache" if r == "cache" else "ok"
        # OPeNDAP no pasa por `_get`: sus fallos llegan como OSError de netCDF4
        except (thredds.ErrorThredds, OSError, ValueError, KeyError) as e:
            msg = f"{e.__class__.__name__}: {e}"[:300]
            fallos.append((str(fecha.date()), msg))
            estado = "FALLO"
        tam = os.path.getsize(destino) / 1e6 if os.path.exists(destino) else 0
        print(f"[{n}/{len(dias)}] {fecha:%Y-%m-%d} {estado:5s} {tam:7.1f} MB", flush=True)
        # el motivo de los primeros fallos, en pantalla: enterarse al final,
        # cuando ya han pasado 300 lineas de FALLO, no sirve de nada
        if estado == "FALLO" and len(fallos) <= 3:
            print(f"        {fallos[-1][1]}", flush=True)
            if len(fallos) == 3:
                print("        (el resto de motivos, en wrf_fallos.txt)",
                      flush=True)

    print(f"\ndescargados {ok}, ya estaban {cacheados}, fallos {len(fallos)}")
    if fallos:
        with open(os.path.join(BASE, "wrf_fallos.txt"), "w", encoding="utf-8") as fh:
            for f, e in fallos:
                fh.write(f"{f}\t{e}\n")
        print("detalle en wrf_fallos.txt (relanza el script para reintentarlos)")
    print("\nSiguiente paso:  python 06_alta_resolucion.py")


if __name__ == "__main__":
    main()
