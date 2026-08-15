"""Sincroniza el kit y las salidas con el repositorio de GitHub.

Tres cosas, un comando para cada una. Se ejecuta SIEMPRE dentro de la carpeta
del proyecto (la que tiene el .git dentro):

    python sincroniza.py                       # traer lo ultimo (git pull)
    python sincroniza.py clima-galicia.zip     # instalar un kit nuevo y subirlo
    python sincroniza.py --subir               # subir las salidas generadas

Lo importante no es ahorrar cuatro comandos, es la comprobacion previa. Antes
de cualquier subida se revisa que no se cuele nada pesado, y si algo lo hace el
guion ABORTA en vez de subir. Ese error no se deshace del todo: aunque luego
borres el fichero, se queda en el historial de git y GitHub sigue sirviendolo.

La red de seguridad normal es el .gitignore. Esto es la segunda red, por si el
.gitignore se borra, se edita mal, o el fichero pesado aparece en un sitio que
no cubre ningun patron.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile

try:                                    # que no reviente en la consola de Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Un fichero suelto por encima de esto es sospechoso. GitHub avisa a los 50 MB
# y rechaza a los 100; se corta mucho antes para tener margen.
LIMITE_MB = 20

# Carpetas de datos brutos. Se comparan por segmento de ruta, asi que valen
# tanto "wrf/algo.nc" como "salidas/wrf/algo.nc".
CARPETAS_PROHIBIDAS = {"descargas", "wrf", "aemet", "rocio", "__pycache__"}

# Ficheros de datos que nunca son un resultado agregado.
EXTENSIONES_PROHIBIDAS = (".nc", ".nc4", ".grib", ".grib2", ".parcial",
                          ".tar.gz", ".tgz", ".tar", ".hdf", ".h5")

# Credenciales. Subir esto es peor que subir 10 GB.
SECRETOS = {".cdsapirc", ".aemetrc", ".aemetrc.txt", ".netrc"}


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------
def git(*args, comprueba=True):
    """Ejecuta git y devuelve su salida. Aborta si falla y comprueba=True."""
    try:
        r = subprocess.run(["git"] + list(args), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise SystemExit(
            "No encuentro el programa 'git'.\n"
            "  Windows: instala Git for Windows desde https://git-scm.com/download/win\n"
            "  Raspberry: sudo apt install git")
    if comprueba and r.returncode:
        raise SystemExit(f"git {' '.join(args)} fallo:\n{r.stderr.strip()}")
    return r.stdout


def raiz():
    """Carpeta raiz del clon. Aborta con una explicacion si no estamos dentro."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(
            "Esto no es un clon de git.\n"
            "Ejecuta el guion dentro de la carpeta del proyecto, la que tiene\n"
            "una subcarpeta .git. Si aun no la has creado:\n"
            "  git clone https://github.com/jrgarciapol/clima-galicia.git")
    return r.stdout.strip()


def rama():
    n = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    return "main" if n == "HEAD" else n


def cambios():
    """Lista [(estado, ruta)] de lo que git ve como pendiente.

    Se usa -z en vez de la salida normal porque git entrecomilla y escapa los
    nombres con espacios o con acentos, y aqui hay que abrir los ficheros para
    medirlos. Con -z vienen tal cual, separados por NUL.
    """
    bruto = git("status", "--porcelain", "-z")
    piezas = [p for p in bruto.split("\0") if p]
    salida, i = [], 0
    while i < len(piezas):
        p = piezas[i]
        estado, ruta = p[:2], p[3:]
        if estado and estado[0] in "RC":   # renombrado: viene la ruta origen detras
            i += 1
        salida.append((estado.strip() or "?", ruta))
        i += 1
    return salida


# ---------------------------------------------------------------------------
# La comprobacion
# ---------------------------------------------------------------------------
def motivo_peligroso(ruta, base):
    """Devuelve por que esta ruta no debe subirse, o None si es inofensiva."""
    partes = ruta.rstrip("/").split("/")
    nombre = partes[-1]

    if nombre in SECRETOS:
        return "CREDENCIAL"
    for seg in partes:
        if seg in CARPETAS_PROHIBIDAS:
            return f"carpeta de datos brutos ({seg}/)"
    bajo = ruta.lower()
    for ext in EXTENSIONES_PROHIBIDAS:
        if bajo.endswith(ext):
            return f"fichero de datos ({ext})"

    completa = os.path.join(base, ruta)
    if ruta.endswith("/") or os.path.isdir(completa):
        mb = sum(os.path.getsize(os.path.join(d, f))
                 for d, _, fs in os.walk(completa) for f in fs
                 if os.path.exists(os.path.join(d, f))) / 1e6
        if mb > LIMITE_MB:
            return f"carpeta de {mb:.0f} MB"
        return None
    if os.path.exists(completa):
        mb = os.path.getsize(completa) / 1e6
        if mb > LIMITE_MB:
            return f"pesa {mb:.1f} MB"
    return None


def revisa(base, lista):
    """Imprime lo que se va a subir. Aborta si hay algo peligroso."""
    if not lista:
        return 0.0

    peligros, total = [], 0.0
    print(f"{len(lista)} cambios pendientes:\n")
    for estado, ruta in sorted(lista, key=lambda x: x[1]):
        completa = os.path.join(base, ruta)
        if os.path.isfile(completa):
            mb = os.path.getsize(completa) / 1e6
            total += mb
            tam = f"{mb * 1000:8.0f} KB" if mb < 1 else f"{mb:8.1f} MB"
        else:
            tam = "         "
        motivo = motivo_peligroso(ruta, base)
        if motivo:
            peligros.append((ruta, motivo))
            print(f"  {estado:2s} {tam}  {ruta}   <-- {motivo}")
        else:
            print(f"  {estado:2s} {tam}  {ruta}")

    print(f"\n  total: {total:.1f} MB")

    if peligros:
        print("\n" + "=" * 68)
        print("ABORTADO. Esto no debe subirse a GitHub:\n")
        for ruta, motivo in peligros:
            print(f"  {ruta}   ({motivo})")
        print("\nLo normal es que falte el .gitignore o que se haya editado.")
        print("Comprueba que existe y que incluye descargas/, wrf/, aemet/ y")
        print("rocio/. Si el fichero esta bien pero git ya lo tenia fichado:")
        print("  git rm --cached -r <ruta>       (no lo borra del disco)")
        if any(m == "CREDENCIAL" for _, m in peligros):
            print("\nHay una CREDENCIAL entre los cambios. Si llega a subirse hay")
            print("que darla por comprometida y regenerarla, no basta con borrarla.")
        print("=" * 68)
        raise SystemExit(1)

    return total


# ---------------------------------------------------------------------------
# Instalar un kit nuevo
# ---------------------------------------------------------------------------
def instala(ruta_zip, base):
    """Descomprime el kit encima del clon. Devuelve la lista de ficheros."""
    if not os.path.exists(ruta_zip):
        raise SystemExit(f"No existe el fichero {ruta_zip}")

    escritos = []
    with zipfile.ZipFile(ruta_zip) as z:
        nombres = [n for n in z.namelist() if not n.endswith("/")]
        if not nombres:
            raise SystemExit("El zip esta vacio.")

        # El kit viene dentro de una carpeta "kit/". Se quita ese primer nivel
        # para que los ficheros caigan en la raiz del clon, que es donde el
        # resto de guiones espera encontrarse unos a otros.
        primeros = {n.split("/")[0] for n in nombres if "/" in n}
        quita = primeros.pop() + "/" if len(primeros) == 1 else ""

        for n in nombres:
            destino_rel = n[len(quita):] if quita and n.startswith(quita) else n
            if not destino_rel:
                continue
            # zip-slip: un zip puede traer rutas con .. o absolutas
            destino = os.path.normpath(os.path.join(base, destino_rel))
            if not destino.startswith(os.path.normpath(base) + os.sep):
                print(f"  IGNORADO por ruta sospechosa: {n}")
                continue
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with z.open(n) as f, open(destino, "wb") as g:
                g.write(f.read())
            escritos.append(destino_rel)

    print(f"{len(escritos)} ficheros escritos desde {os.path.basename(ruta_zip)}")
    return escritos


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
def sube(base, mensaje, confirmar=True):
    lista = cambios()
    if not lista:
        print("No hay nada que subir: el clon esta igual que el repositorio.")
        return
    revisa(base, lista)

    if confirmar:
        try:
            if input("\n?Subir a GitHub? [s/N] ").strip().lower() not in ("s", "si", "y"):
                print("Cancelado. No se ha tocado nada.")
                return
        except EOFError:
            print("\nSin consola interactiva. Usa --si para subir sin preguntar.")
            return

    git("add", "-A")
    if not git("diff", "--cached", "--name-only").strip():
        print("Nada que confirmar.")
        return
    git("commit", "-m", mensaje)
    r = rama()
    salida = subprocess.run(["git", "push", "-u", "origin", r],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if salida.returncode:
        print(salida.stderr.strip())
        raise SystemExit(
            "\nEl push ha fallado, pero el commit esta hecho en local: no se ha\n"
            "perdido nada. Si el motivo es que el repositorio tiene cambios mas\n"
            "nuevos, haz 'git pull --rebase' y vuelve a ejecutar --subir.")
    print(f"Subido a origin/{r}: {mensaje}")


def trae(base):
    antes = git("rev-parse", "HEAD").strip()
    r = subprocess.run(["git", "pull", "--ff-only"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stderr.strip())
        raise SystemExit(
            "\nNo se ha podido traer sin mas. Suele ser porque hay cambios\n"
            "locales sin subir. Mira 'python sincroniza.py --subir' primero.")
    ahora = git("rev-parse", "HEAD").strip()
    if antes == ahora:
        print("Ya estabas al dia.")
    else:
        print(git("diff", "--stat", antes, ahora).rstrip() or "(sin cambios)")

    pendientes = cambios()
    if pendientes:
        print(f"\nOjo: tienes {len(pendientes)} cambios locales sin subir.")
        print("Para verlos y subirlos: python sincroniza.py --subir")


def main():
    ap = argparse.ArgumentParser(
        description="Sincroniza el proyecto con GitHub sin subir datos brutos.")
    ap.add_argument("zip", nargs="?", help="kit nuevo a instalar (clima-galicia.zip)")
    ap.add_argument("--subir", action="store_true",
                    help="subir las salidas generadas")
    ap.add_argument("-m", "--mensaje", default=None, help="mensaje del commit")
    ap.add_argument("--si", action="store_true", help="no preguntar antes de subir")
    ap.add_argument("--revisar", action="store_true",
                    help="solo comprobar que no hay nada peligroso, sin subir")
    a = ap.parse_args()

    base = raiz()
    os.chdir(base)
    print(f"Proyecto: {base}   rama: {rama()}\n")

    if a.zip:
        instala(a.zip, base)
        print()
        sube(base, a.mensaje or f"kit desde {os.path.basename(a.zip)}",
             confirmar=not a.si)
    elif a.subir:
        sube(base, a.mensaje or "salidas", confirmar=not a.si)
    elif a.revisar:
        lista = cambios()
        if not lista:
            print("No hay cambios pendientes.")
        else:
            revisa(base, lista)
            print("\nTodo en orden, nada peligroso.")
    else:
        trae(base)


if __name__ == "__main__":
    main()
