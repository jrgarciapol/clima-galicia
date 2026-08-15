"""PASO 14 - Monta el informe interactivo en un solo fichero HTML.

Que hace
--------
Reune las salidas de los pasos 2, 6, 9, 10, 12 y 13 en un unico HTML que se abre
con doble clic: mapa sobre OpenStreetMap con selector de escenario, graficas de
la brecha, comparacion de sitios y la metodologia.

El fichero es AUTOCONTENIDO: lleva dentro Leaflet, los datos y las graficas. Lo
unico que pide a la red son las teselas del mapa de fondo, y si no hay conexion
el resto del informe funciona igual.

Uso:
    python 14_informe.py              # prepara datos, monta y verifica
    python 14_informe.py --verificar  # solo comprueba las cifras del HTML

Necesita: alta_resolucion.csv.gz, ranking_con_proyeccion.csv,
proyecciones_galicia.csv.gz, indices_estaciones.csv, tendencias_estaciones.csv,
estaciones_lista.csv, aemet_series.csv y rocio_tendencias.csv.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "informe")
LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"


def trae_leaflet():
    """Leaflet se empotra en el HTML para que el fichero sea autocontenido."""
    for nombre in ("leaflet.css", "leaflet.js"):
        destino = os.path.join(DIR, nombre)
        if os.path.exists(destino) and os.path.getsize(destino) > 5000:
            continue
        url = LEAFLET + ("leaflet.min.css" if nombre.endswith("css") else "leaflet.min.js")
        print(f"  bajando {nombre}...", flush=True)
        with urllib.request.urlopen(url, timeout=90) as r, open(destino, "wb") as f:
            f.write(r.read())


def paso(guion):
    print(f"--- {guion} ---", flush=True)
    r = subprocess.run([sys.executable, guion], cwd=DIR)
    if r.returncode:
        raise SystemExit(f"{guion} fallo")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verificar", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(DIR):
        sys.exit(f"Falta la carpeta {DIR} con los guiones del informe.")

    if a.verificar:
        paso("verifica.py")
        return

    trae_leaflet()
    paso("prep.py")
    paso("prep2.py")
    paso("monta.py")
    paso("verifica.py")
    ruta = os.path.join(DIR, "informe_galicia.html")
    print(f"\nListo: {ruta}  ({os.path.getsize(ruta)/1e6:.2f} MB)")
    print("Abrelo con doble clic. Sube ese fichero al repositorio.")


if __name__ == "__main__":
    main()
