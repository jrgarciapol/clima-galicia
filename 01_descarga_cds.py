"""PASO 1 - Descarga ERA5-Land horario para Galicia, 1996-2025.

Por que horario y no el producto diario ya agregado
---------------------------------------------------
El conjunto `derived-era5-land-daily-statistics` viene con los estadisticos
diarios ya hechos, que suena mas comodo. Pero solo admite **un anio y un mes
por peticion** (en el formulario web, anio y mes son botones de radio, no
casillas). Con las variables necesarias serian unas 1.800 peticiones.

`reanalysis-era5-land` es el conjunto base y acepta listas. Y al traer los datos
hora a hora permite ademas:

  - calcular el humidex y la temperatura aparente en cada hora y quedarse con
    el maximo del dia, en lugar de aproximarlos desde la maxima diaria;
  - definir la noche como es debido (minima entre las 21 y las 9 hora local)
    para las noches tropicales;
  - incorporar el viento, que en Galicia es justo lo que salva a la costa norte
    en los episodios de calor.

El limite de tamanio de peticion
--------------------------------
El CDS limita el tamanio de cada peticion, donde un campo es una combinacion de
variable, dia y hora. Un anio entero con las cuatro variables son
4 x 12 x 31 x 24 = 35.712 campos: se rechaza con un "cost limits exceeded" que
ademas llega como HTTP 403, el mismo codigo que usa el servidor cuando faltan
los terminos de uso. Por eso el manejo de errores mira el texto antes que el
codigo.

La documentacion dice 12.000 campos, pero el servidor real rechaza 8.928 y
acepta 5.952. El limite efectivo esta entre los dos, asi que aqui se usa 6.000,
medido contra el servidor y no leido de la documentacion.

Resultado: bimestres, 5.952 campos por peticion, 6 peticiones por anio,
180 en total para los 30 anios. Si aun asi el servidor se quejara, el script
reduce el tamanio solo y reintenta.

Volumen: unos 36 MB por anio, algo mas de 1 GB en total.
Tiempo: unos 20 minutos de cola por peticion, asi que unas 2 horas por anio.

Requisitos previos (una sola vez)
---------------------------------
  1. Cuenta gratuita en https://cds.climate.copernicus.eu/
  2. Aceptar los terminos en
     https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
     (pestania "Download", al final de la pagina)
  3. Token en ~/.cdsapirc  ->  usa `python 00_configura.py`, que lo hace por ti.

Uso:
    python 01_descarga_cds.py                  # 1996-2025, troceado automatico
    python 01_descarga_cds.py --desde 2025     # un anio, para probar
    python 01_descarga_cds.py --trozos 6       # fuerza bimestres
    python 01_descarga_cds.py --verificar      # audita lo descargado y sale

Es reanudable: lo ya descargado se salta. Cada fichero se baja a un temporal y
se renombra al final, asi que una interrupcion nunca deja un .nc a medias.

Este script es el unico del kit que no necesita numpy, pandas ni netCDF4: solo
cdsapi. Por eso puede correr en una Raspberry Pi modesta sin compilar nada.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "descargas")
DATASET = "reanalysis-era5-land"

# Galicia con un pequenio margen: [norte, oeste, sur, este]
AREA = [43.95, -9.45, 41.70, -6.60]

VARIABLES = [
    "2m_temperature",
    "2m_dewpoint_temperature",
    "10m_u_component_of_wind",
    "10m_v_component_of_wind",
]

MESES = [f"{m:02d}" for m in range(1, 13)]
DIAS = [f"{d:02d}" for d in range(1, 32)]
HORAS = [f"{h:02d}:00" for h in range(24)]

# La documentacion del CDS dice 12.000 campos por peticion para
# reanalysis-era5-land, pero el servidor real rechaza 8.928 y acepta 5.952.
# El limite efectivo esta entre ambos; se usa 6.000, medido contra el servidor.
LIMITE_CDS = 6000
MARGEN = 1.0
TROZOS_VALIDOS = [1, 2, 3, 4, 6, 12]


def coste(n_meses):
    """Campos de una peticion: variable x dia x hora."""
    return len(VARIABLES) * n_meses * len(DIAS) * len(HORAS)


def elige_trozos():
    """El menor numero de peticiones por anio que cabe en el limite del CDS."""
    for t in TROZOS_VALIDOS:
        if coste(12 // t) <= LIMITE_CDS * MARGEN:
            return t
    return 12


def peticion(anio, meses):
    return {
        "variable": VARIABLES,
        "year": [str(anio)],
        "month": meses,
        "day": DIAS,
        "time": HORAS,
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": AREA,
    }


# Firmas de fichero: NetCDF clasico empieza por "CDF" y NetCDF-4 es HDF5, que
# empieza por \x89HDF. Comprobarlas no cuesta nada y detecta un fichero truncado
# por un corte de luz, que es el riesgo real cuando esto corre dias en una
# Raspberry. Sin esto, un fichero a medias "pesa bastante" y el script lo daria
# por bueno para siempre.
FIRMAS = (b"CDF", b"\x89HDF")


def integro(ruta, minimo=100_000):
    if not os.path.exists(ruta) or os.path.getsize(ruta) < minimo:
        return False
    with open(ruta, "rb") as fh:
        cab = fh.read(8)
    return any(cab.startswith(f) for f in FIRMAS)


def verifica(directorio):
    """Audita lo descargado. Util al juntar descargas de dos maquinas."""
    if not os.path.isdir(directorio):
        print(f"no existe {directorio}")
        return
    ficheros = sorted(f for f in os.listdir(directorio) if f.endswith(".nc"))
    buenos, malos, total = [], [], 0
    for f in ficheros:
        r = os.path.join(directorio, f)
        total += os.path.getsize(r)
        (buenos if integro(r) else malos).append(f)
    print(f"{len(ficheros)} ficheros, {total / 1e9:.2f} GB")
    print(f"  integros: {len(buenos)}")
    if malos:
        print(f"  DANADOS o incompletos: {len(malos)}")
        for f in malos:
            print(f"    {f}  ({os.path.getsize(os.path.join(directorio, f)) / 1e6:.1f} MB)")
        print("  borralos y relanza el script: se volveran a pedir")
    anios = sorted({f.split("_")[1][:4] for f in buenos})
    if anios:
        print(f"  anios con algun fichero: {anios[0]}-{anios[-1]} ({len(anios)} anios)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=1996)
    ap.add_argument("--hasta", type=int, default=2025)
    ap.add_argument("--trozos", type=int, default=0,
                    help="peticiones por anio (1,2,3,4,6,12). 0 = automatico")
    ap.add_argument("--verificar", action="store_true",
                    help="audita descargas/ y sale, sin pedir nada")
    args = ap.parse_args()

    if args.verificar:
        verifica(DIR)
        return

    try:
        import cdsapi
    except ImportError:
        sys.exit("Falta cdsapi:  pip install -r requirements.txt")

    os.makedirs(DIR, exist_ok=True)
    for f in os.listdir(DIR):          # restos de una ejecucion interrumpida
        if f.endswith(".parcial"):
            os.remove(os.path.join(DIR, f))
    c = cdsapi.Client()

    trozos = args.trozos or elige_trozos()
    if trozos not in TROZOS_VALIDOS:
        sys.exit(f"--trozos debe ser uno de {TROZOS_VALIDOS}")

    anios = list(range(args.desde, args.hasta + 1))
    print(f"Periodo {args.desde}-{args.hasta}, {len(VARIABLES)} variables.")
    print(f"Limite del CDS: {LIMITE_CDS:,} campos por peticion.")

    while True:
        tam = 12 // trozos
        bloques = [MESES[i:i + tam] for i in range(0, 12, tam)]
        n_pet = len(anios) * len(bloques)
        print(f"\nTroceado: {trozos} peticion(es) por anio, {tam} meses cada una "
              f"-> {coste(tam):,} campos ({n_pet} peticiones en total)")
        print(f"Espacio estimado: ~{len(anios) * 0.036:.2f} GB")
        print("ERA5-Land se sirve desde cinta: la cola puede tardar. Dejalo corriendo.\n")

        demasiado_grande = False
        fallos = []
        i = 0
        for anio in anios:
            for k, meses in enumerate(bloques):
                i += 1
                sufijo = "" if trozos == 1 else f"_p{k + 1}"
                destino = os.path.join(DIR, f"era5land_{anio}{sufijo}.nc")
                if integro(destino):
                    print(f"[{i}/{n_pet}] {anio}{sufijo} ya existe "
                          f"({os.path.getsize(destino) / 1e6:.0f} MB)")
                    continue
                if os.path.exists(destino):
                    print(f"[{i}/{n_pet}] {anio}{sufijo} estaba corrupto, se rehace")
                    os.remove(destino)

                print(f"[{i}/{n_pet}] {anio} meses {meses[0]}-{meses[-1]} ...",
                      flush=True)
                t0 = time.time()
                tmp = destino + ".parcial"
                for intento in range(3):
                    try:
                        # Se descarga a un temporal y se renombra al final. El
                        # renombrado es atomico, asi que un corte de luz deja un
                        # .parcial evidente y nunca un .nc a medias.
                        c.retrieve(DATASET, peticion(anio, meses), tmp)
                        if not integro(tmp):
                            raise RuntimeError("el fichero recibido no es NetCDF valido")
                        os.replace(tmp, destino)
                        print(f"    ok  {os.path.getsize(destino) / 1e6:.0f} MB "
                              f"en {(time.time() - t0) / 60:.1f} min")
                        break
                    except Exception as e:  # noqa: BLE001
                        msg = str(e).lower()
                        # El orden importa: "request too large" tambien llega
                        # como HTTP 403, igual que la falta de licencia.
                        if "too large" in msg or "cost limit" in msg:
                            print("    peticion demasiado grande para el CDS")
                            demasiado_grande = True
                            break
                        if "licence" in msg or "license" in msg or "not licensed" in msg:
                            sys.exit(
                                "\nFaltan los terminos de uso. Entra en\n"
                                "  https://cds.climate.copernicus.eu/datasets/"
                                "reanalysis-era5-land\n"
                                "pestania Download, y aceptalos al final de la pagina.")
                        print(f"    fallo ({e.__class__.__name__}): {str(e)[:200]}")
                        time.sleep(30 * (intento + 1))
                else:
                    fallos.append(f"{anio}{sufijo}")
                if demasiado_grande:
                    break
            if demasiado_grande:
                break

        if not demasiado_grande:
            if fallos:
                print(f"\nno se pudieron descargar: {', '.join(fallos)}")
                print("relanza el script para reintentarlos")
            break

        siguiente = next((t for t in TROZOS_VALIDOS if t > trozos), None)
        if siguiente is None:
            sys.exit("\nNi troceando por meses cabe en el limite. Avisame.")
        print(f"\nReduzco el tamanio: {trozos} -> {siguiente} peticiones por anio "
              f"y reintento.")
        trozos = siguiente

    print("\nSiguiente paso:  python 02_indices.py")


if __name__ == "__main__":
    main()
