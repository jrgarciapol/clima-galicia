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


def url_dods(url_path):
    return f"{RAIZ}/dodsC/{url_path}"


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
    # no tiene por que coincidir con la del catalogo.
    L.append(f"--- recorrido del catalogo (profundidad {prof}) ---")
    traza, encontrados, vistos = [], [], set()
    pendientes = [(CATALOGO, "raiz", 0)]
    peticiones = 0
    ficheros_por_rama = {}
    while pendientes and peticiones < max_peticiones:
        url, titulo, p = pendientes.pop(0)
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
        for tit, sub in subs:
            if p < prof:
                pendientes.append((sub, tit, p + 1))
    L.extend(traza)
    if peticiones >= max_peticiones:
        L.append(f"  (tope de {max_peticiones} peticiones alcanzado)")
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
            L.append("  (si falla, habra que bajar por HTTPServer el fichero completo)")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--prof", type=int, default=5)
    args = ap.parse_args()

    if args.explorar:
        explorar(os.path.join(BASE, "adaptecca_exploracion.txt"), prof=args.prof)
        return

    sys.exit("Por ahora solo esta implementado --explorar.\n"
             "Lanza:  python 09_proyecciones.py --explorar\n"
             "y comparte adaptecca_exploracion.txt: con el inventario real se\n"
             "concreta que escenarios e indices bajar, sin adivinar nombres.")


if __name__ == "__main__":
    main()
