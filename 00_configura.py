"""PASO 0 - Comprobacion del entorno y configuracion de credenciales.

Ejecuta esto primero. Verifica que tienes todo lo necesario, te ayuda a dejar
la credencial del Copernicus en el sitio correcto (que en Windows es el punto
donde mas gente se atasca) y lanza las pruebas.

    python 00_configura.py

No descarga ningun dato ni necesita internet, salvo si le pides que instale
las dependencias.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RC = os.path.expanduser("~/.cdsapirc")
URL_CDS = "https://cds.climate.copernicus.eu/api"

DEPS = ["cdsapi", "xarray", "netCDF4", "numpy", "pandas", "requests", "scipy",
        "matplotlib"]

VERDE, ROJO, AMAR, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
if platform.system() == "Windows" and not os.environ.get("WT_SESSION"):
    VERDE = ROJO = AMAR = FIN = ""  # consolas antiguas de Windows no lo pintan


def ok(t):
    print(f"  {VERDE}OK{FIN}    {t}")


def mal(t):
    print(f"  {ROJO}FALLA{FIN} {t}")


def avi(t):
    print(f"  {AMAR}AVISO{FIN} {t}")


def titulo(t):
    print(f"\n=== {t} ===")


def pregunta(t, defecto="s"):
    r = input(f"{t} [{'S/n' if defecto == 's' else 's/N'}] ").strip().lower()
    return (r or defecto) in ("s", "si", "sí", "y", "yes")


# ---------------------------------------------------------------------------

def comprueba_python():
    titulo("Python")
    v = sys.version_info
    print(f"  version: {v.major}.{v.minor}.{v.micro}  ({sys.executable})")
    if v < (3, 9):
        mal("hace falta Python 3.9 o superior. Instalalo desde python.org")
        return False
    ok("version suficiente")
    return True


def comprueba_dependencias():
    titulo("Dependencias")
    import importlib.util

    alias = {"netCDF4": "netCDF4", "cdsapi": "cdsapi"}
    faltan = []
    for d in DEPS:
        nombre = alias.get(d, d)
        if importlib.util.find_spec(nombre) is None:
            faltan.append(d)
            mal(f"{d} no instalado")
        else:
            ok(d)
    if not faltan:
        return True
    print(f"\n  Faltan {len(faltan)}: {', '.join(faltan)}")
    if pregunta("  Instalarlas ahora con pip?"):
        r = subprocess.run([sys.executable, "-m", "pip", "install",
                            "-r", os.path.join(BASE, "requirements.txt")])
        return r.returncode == 0
    print(f"\n  Instalalas tu con:\n    {sys.executable} -m pip install -r requirements.txt")
    return False


def comprueba_disco():
    titulo("Espacio en disco")
    libre = shutil.disk_usage(BASE).free / 1e9
    print(f"  libre en {os.path.abspath(BASE)}: {libre:.0f} GB")
    if libre < 30:
        mal("menos de 30 GB. El paso 5 (WRF) no cabra; limitalo con --dias y --desde")
    elif libre < 100:
        avi("entre 30 y 100 GB: suficiente para un WRF recortado, no para 15 anios enteros")
    else:
        ok("de sobra para el analisis completo")
    return libre


def comprueba_credencial():
    titulo("Credencial del Copernicus (CDS)")
    if os.environ.get("CDSAPI_KEY"):
        ok("encontrada en la variable de entorno CDSAPI_KEY")
        return True
    if os.path.exists(RC):
        texto = open(RC).read()
        if "key:" in texto and "url:" in texto:
            clave = [l for l in texto.splitlines() if l.startswith("key:")][0]
            ok(f"{RC} existe y tiene buena pinta ({clave[:14]}...)")
            return True
        mal(f"{RC} existe pero le falta 'url:' o 'key:'")
    else:
        print(f"  no existe {RC}")

    print("""
  Para conseguirla:
    1. Crea una cuenta gratuita en https://cds.climate.copernicus.eu/
    2. IMPORTANTE: entra en
       https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
       pestania "Download", baja hasta el final y ACEPTA los terminos de uso.
       Si te saltas esto, las descargas fallan con un 403 que no explica nada.
    3. Copia tu Personal Access Token de
       https://cds.climate.copernicus.eu/how-to-api
       OJO: la pestania "Download" NO da el token, sirve para construir
       peticiones. El token esta en /how-to-api, en un bloque de dos lineas
       con url: y key:. El token es lo que va despues de "key:".
""")
    if not pregunta("  Tienes el token a mano y quieres que lo guarde yo?", "n"):
        print(f"\n  Cuando lo tengas, crea el fichero {RC} con este contenido:")
        print(f"\n    url: {URL_CDS}\n    key: TU-TOKEN\n")
        return False

    token = input("  Pega el token: ").strip()
    if len(token) < 20:
        mal("eso no parece un token (son bastante largos)")
        return False
    with open(RC, "w") as fh:
        fh.write(f"url: {URL_CDS}\nkey: {token}\n")
    ok(f"escrito {RC}")
    return True


def lanza_pruebas():
    titulo("Pruebas")
    todo_bien = True
    for t in ("test_indices.py", "test_malla.py", "test_wrf.py",
              "test_evolucion.py", "test_retorno.py", "test_aemet.py",
              "test_rocio.py"):
        print(f"  {t} ...", end=" ", flush=True)
        r = subprocess.run([sys.executable, t], cwd=BASE,
                           capture_output=True, text=True)
        # las pruebas usan assert: si algo falla, el codigo de salida no es 0
        if r.returncode == 0:
            print(f"{VERDE}pasa{FIN}")
        else:
            print(f"{ROJO}falla{FIN}")
            print((r.stdout + r.stderr)[-1500:])
            todo_bien = False
    return todo_bien


def main():
    print(f"Comprobacion del entorno - {platform.system()} {platform.release()}")
    print(f"Directorio: {os.path.abspath(BASE)}")

    if not comprueba_python():
        sys.exit(1)
    if not comprueba_dependencias():
        sys.exit("\nInstala las dependencias y vuelve a lanzar este script.")
    comprueba_disco()
    cred = comprueba_credencial()
    pruebas = lanza_pruebas()

    titulo("Resumen")
    if pruebas:
        ok("el codigo funciona correctamente en tu maquina")
    else:
        mal("alguna prueba ha fallado: mandame la salida de arriba antes de seguir")
    if cred:
        ok("credencial del CDS lista")
        print(f"\n  Siguiente paso:\n    {os.path.basename(sys.executable)} 01_descarga_cds.py")
    else:
        avi("falta la credencial del CDS")
        print("\n  Consigue el token y vuelve a lanzar 00_configura.py")

    print("\n  Mientras tanto puedes ir lanzando, que no necesita credencial:")
    print("    python 05_wrf_dias_calidos.py --explorar")


if __name__ == "__main__":
    main()
