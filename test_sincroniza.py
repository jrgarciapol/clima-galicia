"""Pruebas del sincronizador, sin tocar GitHub.

Se monta un repositorio de git local de verdad (con un "remoto" que es otra
carpeta) y se comprueba lo unico que importa de este guion: que ABORTA cuando
hay datos brutos o credenciales entre los cambios, y que no aborta cuando lo
que hay son salidas normales.
"""
import importlib.util
import io
import contextlib
import os
import shutil
import subprocess
import zipfile

KIT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(KIT, "_pruebas_sinc")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)

spec = importlib.util.spec_from_file_location("sinc", os.path.join(KIT, "sincroniza.py"))
sinc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sinc)


def sh(*args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{args}: {r.stderr}"
    return r.stdout


# --- un repositorio y su remoto, los dos en disco --------------------------
REMOTO = os.path.join(TMP, "remoto.git")
CLON = os.path.join(TMP, "clon")
sh("git", "init", "--bare", "-b", "main", REMOTO, cwd=TMP)
sh("git", "clone", REMOTO, CLON, cwd=TMP)
for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
    sh("git", "config", k, v, cwd=CLON)
shutil.copy(os.path.join(KIT, ".gitignore"), CLON)
open(os.path.join(CLON, "README.md"), "w").write("# prueba\n")
sh("git", "add", "-A", cwd=CLON)
sh("git", "commit", "-m", "inicial", cwd=CLON)
sh("git", "push", "-u", "origin", "main", cwd=CLON)
os.chdir(CLON)

print("=== detecta la raiz del clon ===")
sub = os.path.join(CLON, "una", "subcarpeta")
os.makedirs(sub)
os.chdir(sub)
assert os.path.realpath(sinc.raiz()) == os.path.realpath(CLON), sinc.raiz()
print("  ok: funciona desde una subcarpeta, no solo desde la raiz")
os.chdir(CLON)
shutil.rmtree(os.path.join(CLON, "una"))

print("\n=== salidas normales: no debe abortar ===")
open(os.path.join(CLON, "resumen_aemet.txt"), "w").write("x" * 3000)
open(os.path.join(CLON, "aemet_series.csv"), "w").write("a,b\n1,2\n" * 500)
lista = sinc.cambios()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    total = sinc.revisa(CLON, lista)
print(f"  {len(lista)} cambios, {total:.3f} MB, sin abortar")
assert len(lista) == 2, lista

print("\n=== un .nc suelto: debe abortar ===")
open(os.path.join(CLON, "tmax_2010.nc"), "wb").write(b"\0" * 100)
# lo tapa el .gitignore, asi que git ni lo ve: esa es la primera red
assert not any(r.endswith(".nc") for _, r in sinc.cambios()), \
    "el .gitignore deberia ocultarlo"
print("  el .gitignore lo oculta (primera red)")

# ahora se quita el .gitignore, que es justo el escenario que hay que cubrir
os.remove(os.path.join(CLON, ".gitignore"))
lista = sinc.cambios()
assert any(r.endswith(".nc") for _, r in lista), lista
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        sinc.revisa(CLON, lista)
    raise AssertionError("tenia que abortar sin .gitignore")
except SystemExit:
    pass
assert "ABORTADO" in buf.getvalue()
print("  sin .gitignore, la segunda red lo caza y aborta")
os.remove(os.path.join(CLON, "tmax_2010.nc"))
shutil.copy(os.path.join(KIT, ".gitignore"), CLON)

print("\n=== carpeta de datos brutos ===")
os.makedirs(os.path.join(CLON, "salidas", "wrf"), exist_ok=True)
open(os.path.join(CLON, "salidas", "wrf", "d.bin"), "wb").write(b"\0" * 10)
m = sinc.motivo_peligroso("salidas/wrf/d.bin", CLON)
print(f"  salidas/wrf/d.bin -> {m}")
assert m and "wrf" in m, "debe cazarla aunque este anidada, no solo en la raiz"
shutil.rmtree(os.path.join(CLON, "salidas"))

print("\n=== credencial ===")
m = sinc.motivo_peligroso(".aemetrc", CLON)
print(f"  .aemetrc -> {m}")
assert m == "CREDENCIAL"
assert sinc.motivo_peligroso(".cdsapirc", CLON) == "CREDENCIAL"

print("\n=== fichero grande sin extension sospechosa ===")
gordo = os.path.join(CLON, "salida_enorme.csv")
open(gordo, "wb").write(b"a" * int((sinc.LIMITE_MB + 3) * 1e6))
m = sinc.motivo_peligroso("salida_enorme.csv", CLON)
print(f"  salida_enorme.csv ({sinc.LIMITE_MB + 3} MB) -> {m}")
assert m and "pesa" in m, "un .csv de 23 MB tambien tiene que parar la subida"
os.remove(gordo)

print("\n=== instalar un kit y subirlo de verdad ===")
zp = os.path.join(TMP, "kit.zip")
with zipfile.ZipFile(zp, "w") as z:
    z.writestr("kit/12_aemet.py", "print('v43')\n")
    z.writestr("kit/README.md", "# v43\n")
    z.writestr("kit/../fuera.txt", "no deberia salir de la carpeta\n")
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    escritos = sinc.instala(zp, CLON)
print(f"  escritos: {escritos}")
assert "12_aemet.py" in escritos, "hay que quitar el nivel 'kit/'"
assert not os.path.exists(os.path.join(TMP, "fuera.txt")), \
    "un zip con .. no puede escribir fuera del clon"
assert open(os.path.join(CLON, "README.md")).read() == "# v43\n"

sinc.sube(CLON, "kit v43 de prueba", confirmar=False)
enviado = sh("git", "log", "--oneline", "-1", "origin/main", cwd=CLON)
print(f"  remoto: {enviado.strip()}")
assert "v43" in enviado
assert not sinc.cambios(), "despues de subir no debe quedar nada pendiente"

print("\n=== y el .nc que sigue en disco no se ha subido ===")
open(os.path.join(CLON, "grande.nc"), "wb").write(b"\0" * 1000)
sinc.sube(CLON, "nada", confirmar=False)
fich = sh("git", "ls-tree", "-r", "--name-only", "origin/main", cwd=CLON)
print(f"  en el repositorio: {sorted(fich.split())}")
assert not any(f.endswith(".nc") for f in fich.split())

shutil.rmtree(TMP, ignore_errors=True)
print("\nSINCRONIZADOR VALIDADO")
