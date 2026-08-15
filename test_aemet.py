"""Pruebas del paso 12 sin tocar la red.

Se simula el servidor de AEMET con sus rarezas reales, que son las que rompen
una carga en silencio: respuesta en dos saltos, ISO-8859-15, coma decimal,
coordenadas en grados-minutos-segundos, marcas como 'Ip', y un limite de rango
por peticion que no esta documentado y hay que medir.
"""
import importlib.util
import json
import os
import shutil
import sys
from datetime import date

import numpy as np
import pandas as pd

KIT = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(KIT, "_pruebas_aemet")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
os.environ["GAL_BASE"] = TMP
os.environ["AEMET_API_KEY"] = "clave.eyJleHAiOjIwMDAwMDAwMDB9.firma"

spec = importlib.util.spec_from_file_location("p12", os.path.join(KIT, "12_aemet.py"))
p12 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p12)

print("=== lectura de la clave y su caducidad ===")
k = p12.clave()
assert k.startswith("clave."), k
cad = p12.caducidad(k)
print(f"  caduca {cad}")
assert cad == date(2033, 5, 18), cad
assert p12.caducidad("no-es-un-jwt") is None, "no debe explotar con basura"

# --- el fichero, con las cuatro formas de escribirlo mal --------------------
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjIwMDAwMDAwMDB9.aG9sYQ=="   # con relleno "="
del os.environ["AEMET_API_KEY"]
casa = os.path.join(TMP, "casa")
os.makedirs(casa, exist_ok=True)
_expand = os.path.expanduser
os.path.expanduser = lambda p: p.replace("~", casa)
for nombre, contenido, que in [
        (".aemetrc", JWT + "\n", "la clave a secas"),
        (".aemetrc", f"# mi clave de AEMET\napi_key = {JWT}\n", "con prefijo y comentario"),
        (".aemetrc", f'"{JWT}"\n', "entrecomillada"),
        (".aemetrc.txt", JWT, "con la extension que anade el Bloc de notas")]:
    for f in (".aemetrc", ".aemetrc.txt"):
        r = os.path.join(casa, f)
        if os.path.exists(r):
            os.remove(r)
    with open(os.path.join(casa, nombre), "w", encoding="utf-8") as fh:
        fh.write(contenido)
    leida = p12.clave()
    print(f"  {que:42s} -> {'OK' if leida == JWT else 'MAL: ' + leida[:40]}")
    assert leida == JWT, f"{que}: leyo {leida!r}"
# y con BOM, que es lo que escribe el Bloc de notas en «UTF-8 con BOM»
with open(os.path.join(casa, ".aemetrc"), "w", encoding="utf-8-sig") as fh:
    fh.write(JWT)
assert p12.clave() == JWT, "un BOM al principio no debe colarse en la clave"
print("  con BOM del Bloc de notas                  -> OK")
# --- el error mas probable: la clave en la carpeta del proyecto -------------
for f in (".aemetrc", ".aemetrc.txt"):
    r = os.path.join(casa, f)
    if os.path.exists(r):
        os.remove(r)
with open(os.path.join(TMP, ".aemetrc"), "w", encoding="utf-8") as fh:
    fh.write(JWT)          # TMP es GAL_BASE, o sea la carpeta del proyecto
try:
    p12.clave()
    raise AssertionError("no debe leerla de la carpeta del proyecto")
except SystemExit as ex:
    aviso = str(ex)
print("  " + "\n  ".join(aviso.splitlines()[:3]))
assert "PERO la he encontrado aqui" in aviso, \
    "si esta en el sitio equivocado, hay que decirlo, no dar un 'no existe'"
assert "mv " in aviso, "y hay que dar la orden exacta para moverla"
assert TMP in aviso
print("  ...")
print("  ok: detecta la clave mal colocada y dice como moverla")
os.remove(os.path.join(TMP, ".aemetrc"))

os.path.expanduser = _expand
os.environ["AEMET_API_KEY"] = "clave.eyJleHAiOjIwMDAwMDAwMDB9.firma"
print("  ok: la clave sale del entorno o del fichero, y el entorno manda")

print("\n=== numeros con coma decimal y marcas especiales ===")
assert p12.num("23,4") == 23.4
assert p12.num("-1,5") == -1.5
assert p12.num("Ip") == 0.0, "precipitacion inapreciable es cero, no nulo"
assert p12.num("") is None and p12.num(None) is None
assert p12.num("Acum") is None, "acumulada no es un valor del dia"
assert p12.num(" 8,0 ") == 8.0
# el fallo silencioso que esto evita: float('23,4') revienta, pero
# float('23.4'.replace(...)) mal hecho daria 234
assert p12.num("23,4") != 234
print("  ok")

print("\n=== coordenadas en grados-minutos-segundos ===")
# AEMET no da decimales: 431825N son 43 grados 18 minutos 25 segundos
assert abs(p12.grados("431825N") - 43.30694) < 1e-4, p12.grados("431825N")
assert abs(p12.grados("082514W") - (-8.42056)) < 1e-4, p12.grados("082514W")
assert p12.grados("082514W") < 0, "el oeste es negativo"
assert p12.grados(None) is None and p12.grados("basura") is None
print(f"  431825N -> {p12.grados('431825N')}   082514W -> {p12.grados('082514W')}")
print("  ok: si se leyeran como decimales, A Coruña acabaria en Somalia")

# ---------------------------------------------------------------------------
# Servidor simulado
# ---------------------------------------------------------------------------
LIMITE_MESES = 6         # lo que admite AEMET de verdad, medido el 29-07-2026
PETICIONES = []

INVENTARIO = [
    {"indicativo": "1387", "nombre": "A CORUÑA", "provincia": "A CORUÑA",
     "altitud": "58", "latitud": "432200N", "longitud": "082500W"},
    {"indicativo": "1428", "nombre": "SANTIAGO DE COMPOSTELA AEROPUERTO",
     "provincia": "A CORUÑA", "altitud": "370", "latitud": "425339N",
     "longitud": "082431W"},
    {"indicativo": "1690A", "nombre": "OURENSE", "provincia": "OURENSE",
     "altitud": "143", "latitud": "422000N", "longitud": "075100W"},
    {"indicativo": "9999", "nombre": "MADRID RETIRO", "provincia": "MADRID",
     "altitud": "667", "latitud": "402445N", "longitud": "034041W"},
]

rng = np.random.default_rng(7)


def dia_falso(idema, f):
    # tendencia real impuesta: +0.25 C/decada, mas variabilidad decenal fuerte
    t = (f.year - 1960) / 10
    base = 18 + 0.25 * t + 2.6 * np.sin(2 * np.pi * (f.year - 1960) / 22)
    est = 9 * np.sin(2 * np.pi * (f.dayofyear - 110) / 365.25)
    tx = base + est + rng.normal(0, 3.0)
    return {"fecha": f.strftime("%Y-%m-%d"), "indicativo": idema,
            "tmax": f"{tx:.1f}".replace(".", ","),
            "tmin": f"{tx - 8:.1f}".replace(".", ","),
            "tmed": f"{tx - 4:.1f}".replace(".", ","),
            "prec": "Ip"}


def _pide_falso(url, k, intentos=4):
    PETICIONES.append(url)
    if "inventarioestaciones" in url:
        return INVENTARIO
    import re
    m = re.search(r"fechaini/([\d-]+)T.*?fechafin/([\d-]+)T.*?estacion/([^/]+)/", url)
    f0, f1, idema = (pd.Timestamp(m.group(1)), pd.Timestamp(m.group(2)), m.group(3))
    # El servidor real contesta esto, con el limite dentro del mensaje:
    if (f1 - f0).days > LIMITE_MESES * 31:
        raise p12.ErrorAemet(
            "sin datos: El rango de fechas no puede ser superior a 6 meses")
    if idema == "1690A" and f0.year < 1990:
        raise p12.ErrorAemet("sin datos: no hay observaciones")
    if f0.year < 1960:
        raise p12.ErrorAemet("sin datos: anterior al inicio de la serie")
    return [dia_falso(idema, f) for f in pd.date_range(f0, f1, freq="D")]


p12._pide = _pide_falso
p12.PAUSA = 0

print("\n=== inventario: solo Galicia, coordenadas convertidas ===")
inv = p12.inventario("x")
print(f"  {len(inv)} estaciones: {[e['nombre'] for e in inv]}")
assert len(inv) == 3, "Madrid no debe colarse"
assert all(e["lon"] < 0 for e in inv), "toda Galicia esta al oeste"
assert all(41 < e["lat"] < 44.5 for e in inv), [e["lat"] for e in inv]
assert inv[0]["nombre"] == "A Coruña", inv[0]["nombre"]
print("  ok")

print("\n=== medicion del limite: leerlo del mensaje del servidor ===")
traza = []
lim = p12.mide_limite("x", "1387", traza)
for t in traza:
    print(t)
print(f"  limite: {lim} meses (el servidor admite {LIMITE_MESES})")
assert lim == LIMITE_MESES, f"deberia dar {LIMITE_MESES}, dio {lim}"
assert any("el propio servidor dice el limite" in t for t in traza), \
    "cuando el servidor dice el limite en el mensaje, hay que leerlo"
assert len(traza) <= 3, \
    "leyendo el mensaje no hace falta recorrer la escalera entera"

# Y la escalera tiene que seguir funcionando si el servidor NO lo dice
guardado = _pide_falso
def _mudo(url, k, intentos=4):
    try:
        return guardado(url, k, intentos)
    except p12.ErrorAemet as e:
        raise p12.ErrorAemet("sin datos" if "superior a" in str(e) else str(e))
p12._pide = _mudo
traza2 = []
lim2 = p12.mide_limite("x", "1387", traza2)
p12._pide = guardado
print(f"  sin mensaje explicito, por escalera: {lim2} meses")
assert lim2 == LIMITE_MESES, f"la escalera deberia dar {LIMITE_MESES}, dio {lim2}"
print("  ok: lee el limite si se lo dicen, y si no lo mide")

print("\n=== el fallo que hizo fracasar el primer reconocimiento ===")
# Pedir un anio entero supera el limite de 6 meses: TODAS las peticiones eran
# invalidas y el informe concluyo "sin datos antes de 2010" para las 58
# estaciones. No era falta de datos, era que ninguna peticion valia.
try:
    p12.diarios("x", "1387", date(1960, 1, 1), date(1960, 12, 31))
    raise AssertionError("un anio entero deberia ser rechazado")
except p12.ErrorAemet as e:
    print(f"  un anio entero -> {str(e)[:70]}")
# el sondeo corto que ahora usa --explorar si vale
d = p12.diarios("x", "1387", date(1960, 1, 1), date(1960, 1, 10))
assert len(d) == 10, len(d)
print(f"  diez dias        -> {len(d)} dias, valido")
print("  ok: por eso el sondeo pide diez dias y no un anio")

print("\n=== la cache del sondeo, que se lee antes de reescribir ===")
# El fallo original: explorar() reescribia aemet_estaciones.json con el
# inventario recien bajado (sin `desde`) y DESPUES leia la cache de ese mismo
# fichero. Nunca encontraba nada y resondeaba las 58 en cada pasada.
p12.PAUSA = 0
PETICIONES.clear()
p12.explorar("x", max_est=2)
n_primera = len([u for u in PETICIONES if "diarios" in u])
guardado_inv = json.load(open(os.path.join(TMP, "aemet_estaciones.json"),
                              encoding="utf-8"))
con_desde = [e for e in guardado_inv if e.get("desde")]
print(f"  primera pasada: {n_primera} peticiones de sondeo, "
      f"{len(con_desde)} estaciones con anio anotado")
assert con_desde, "el anio de inicio debe quedar guardado en el JSON"
PETICIONES.clear()
p12.explorar("x", max_est=2)
n_segunda = len([u for u in PETICIONES if "diarios" in u])
print(f"  segunda pasada: {n_segunda} peticiones de sondeo")
assert n_segunda < n_primera, \
    (f"la segunda pasada gasto {n_segunda} y la primera {n_primera}: la cache "
     "no sirve de nada si se lee despues de sobrescribir el fichero")
texto_exp = open(os.path.join(TMP, "aemet_exploracion.txt"), encoding="utf-8").read()
assert "ya sondeadas antes" in texto_exp
assert "2 ya sondeadas antes" in texto_exp, texto_exp[:400]
# La orden sugerida NO debe llevar --desde: con el, una estacion que empieza en
# 1980 arrancaria en 1940 y gastaria 80 peticiones vacias.
import re as _re
for linea in texto_exp.splitlines():
    if "--descargar" in linea:
        assert "--desde" not in linea, \
            f"la orden sugerida no debe fijar un --desde global: {linea.strip()}"
print("  ok: lo ya sondeado no se vuelve a pedir")

print("\n=== descarga: reanudable y sin repetir peticiones ===")
json.dump(inv, open(os.path.join(TMP, "aemet_estaciones.json"), "w"),
          ensure_ascii=False)
PETICIONES.clear()
p12.descargar("x", 1960, 1961, LIMITE_MESES)
n1 = len(PETICIONES)
ficheros = os.listdir(os.path.join(TMP, "aemet"))
print(f"  {n1} peticiones, {len(ficheros)} ficheros")
PETICIONES.clear()
p12.descargar("x", 1960, 1961, LIMITE_MESES)
print(f"  al repetir: {len(PETICIONES)} peticiones")
assert len(PETICIONES) == 0, "lo ya descargado no se vuelve a pedir"
assert not any(f.endswith(".parcial") for f in ficheros), \
    "no deben quedar ficheros a medias"
# una estacion sin datos en el periodo no debe reintentarse cada vez
assert any(f.startswith("1690A") for f in ficheros), \
    "un periodo vacio se marca con un fichero vacio, no se deja sin registrar"
# cada estacion arranca en SU anio, no en el mas antiguo de todas
inv2 = [dict(e) for e in inv]
inv2[0]["desde"] = 1960     # A Coruña
inv2[1]["desde"] = 2000     # Santiago
inv2[2]["desde"] = 2010     # Ourense
json.dump(inv2, open(os.path.join(TMP, "aemet_estaciones.json"), "w"),
          ensure_ascii=False)
shutil.rmtree(os.path.join(TMP, "aemet"))
PETICIONES.clear()
p12.descargar("x", None, 2011, LIMITE_MESES)
por_est = {}
for u in PETICIONES:
    i = u.split("estacion/")[1].split("/")[0]
    por_est[i] = por_est.get(i, 0) + 1
print(f"  peticiones por estacion: {por_est}")
assert por_est["1387"] > por_est["1428"] > por_est["1690A"], \
    ("cada estacion debe arrancar en su propio anio: pedir 1960 para una que "
     f"empieza en 2010 son peticiones tiradas. {por_est}")
assert por_est["1690A"] == 4, f"2010-2011 son 4 bloques de 6 meses, no {por_est['1690A']}"
print("  ok: sin --desde, cada una arranca donde de verdad empieza")
shutil.rmtree(os.path.join(TMP, "aemet"))
json.dump(inv, open(os.path.join(TMP, "aemet_estaciones.json"), "w"),
          ensure_ascii=False)
p12.descargar("x", 1960, 1961, LIMITE_MESES)

# y se puede pedir solo un subconjunto de estaciones
PETICIONES.clear()
p12.descargar("x", 1962, 1962, LIMITE_MESES, solo="1387")
assert all("estacion/1387/" in u for u in PETICIONES), \
    "--estaciones debe filtrar de verdad"
print(f"  con --estaciones 1387: {len(PETICIONES)} peticiones, solo esa")
print("  ok")

print("\n=== un corte de red NO puede confundirse con 'no hay datos' ===")
# Es lo que tumbo la descarga en la Raspberry al bloque 1.103 de 3.306. Y lo
# grave no es la caida: es que si el corte se toma por un "no hay datos", se
# escribe un fichero vacio, se marca como hecho y ese trozo de serie queda
# ausente para siempre sin que nada lo delate.
shutil.rmtree(os.path.join(TMP, "aemet"), ignore_errors=True)
json.dump(inv, open(os.path.join(TMP, "aemet_estaciones.json"), "w"),
          ensure_ascii=False)
import requests as _rq
llamadas = {"n": 0}
bueno = _pide_falso


def _con_corte(url, k, intentos=4):
    llamadas["n"] += 1
    if 3 <= llamadas["n"] <= 6:      # la red se cae un rato
        raise p12.ErrorRed("Connection aborted, RemoteDisconnected")
    return bueno(url, k, intentos)


p12._pide = _con_corte
p12.descargar("x", 1962, 1963, LIMITE_MESES, solo="1387")
p12._pide = bueno
ficheros = sorted(os.listdir(os.path.join(TMP, "aemet")))
print(f"  bloques pedidos: 4; ficheros escritos: {len(ficheros)}")
assert len(ficheros) < 4, \
    ("los bloques que fallaron por red NO deben escribirse: si se escriben "
     "vacios, quedan como 'sin datos' para siempre")
vacios = [f for f in ficheros
          if os.path.getsize(os.path.join(TMP, "aemet", f)) <= 2]
assert not vacios, f"ningun fichero vacio deberia venir de un corte de red: {vacios}"

# y al relanzar con la red buena, se completan
p12.descargar("x", 1962, 1963, LIMITE_MESES, solo="1387")
ficheros2 = sorted(os.listdir(os.path.join(TMP, "aemet")))
print(f"  al relanzar con red: {len(ficheros2)} ficheros")
assert len(ficheros2) == 4, f"deberia completarse al relanzar, hay {len(ficheros2)}"
for f in ficheros2:
    assert os.path.getsize(os.path.join(TMP, "aemet", f)) > 2, f
print("  ok: el corte deja el hueco pendiente y se rellena al relanzar")

print("\n=== reintentos de transporte antes de rendirse ===")
intentos = {"n": 0}


class RespOK:
    status_code = 200
    def json(self):
        return {"estado": 200, "datos": "http://x/d"}
    content = b"[]"


def _flaky(url, params=None, timeout=None):
    intentos["n"] += 1
    if intentos["n"] < 3:
        raise _rq.exceptions.ConnectionError("Remote end closed connection")
    return RespOK()


guardado_s, p12.S = p12.S, type("S", (), {"get": staticmethod(_flaky)})()
p12_time = p12.time.sleep
p12.time.sleep = lambda s: None
r = p12._get("http://x", "k")
p12.time.sleep = p12_time
p12.S = guardado_s
print(f"  dos fallos seguidos -> {intentos['n']} intentos, y a la tercera funciono")
assert intentos["n"] == 3, intentos
print("  ok: un parpadeo de red no tumba cuatro horas de descarga")

print("\n=== un anio con el verano incompleto no debe colarse ===")
# Xinzo de Limia 2015: 331 dias del anio (pasa un filtro de 330) pero le
# faltaban 34. Si esos 34 cayeran en verano, los indices de calor de ese anio
# saldrian falseados y nada lo indicaria.
shutil.rmtree(os.path.join(TMP, "aemet"), ignore_errors=True)
os.makedirs(os.path.join(TMP, "aemet"))
fechas = pd.date_range("2000-01-01", "2000-12-31", freq="D")
# quitamos 35 dias de julio y agosto: quedan 331 del anio, 57 de verano
quita = pd.date_range("2000-07-10", periods=35, freq="D")
recorte = [f for f in fechas if f not in set(quita)]
json.dump([dia_falso("1387", f) for f in recorte],
          open(os.path.join(TMP, "aemet", "1387_200001_200012.json"), "w"))
# y un anio entero bueno, para que quede algo
for a in range(2001, 2004):
    fs = pd.date_range(f"{a}-01-01", f"{a}-12-31", freq="D")
    json.dump([dia_falso("1387", f) for f in fs],
              open(os.path.join(TMP, "aemet", f"1387_{a}01_{a}12.json"), "w"))
try:
    p12.analizar(ventana=3)
except SystemExit:
    pass
ser = pd.read_csv(os.path.join(TMP, "aemet_series.csv"))
print(f"  anios aceptados: {sorted(ser.anio.unique())}")
assert 2000 not in ser.anio.values, \
    ("un anio con 331 dias pero solo 57 de verano NO puede entrar: los indices "
     "de calor saldrian falseados")
desc = pd.read_csv(os.path.join(TMP, "aemet_anios_descartados.csv"))
fila = desc[desc.anio == 2000].iloc[0]
print(f"  descartado 2000: {fila.dias} dias del anio, {fila.verano} de verano")
assert fila.dias >= 330 and fila.verano < 87
print("  ok: se mira el verano, no solo el total")

print("\n=== analisis: el sesgo de la ventana corta ===")
shutil.rmtree(os.path.join(TMP, "aemet"))
p12.descargar("x", 1960, 2019, LIMITE_MESES)
p12.analizar(ventana=15)

texto = open(os.path.join(TMP, "resumen_aemet.txt"), encoding="utf-8").read()
ser = pd.read_csv(os.path.join(TMP, "aemet_series.csv"))
print(f"  {len(ser):,} anios-estacion; estaciones: {ser.idema.nunique()}")
assert ser.anio.min() == 1960 and ser.anio.max() == 2019
assert "1690A" in ser.idema.values, "Ourense arranca en 1990, debe estar"
assert ser[ser.idema == "1690A"].anio.min() >= 1990

# la pendiente larga tiene que acercarse a la impuesta (+0.25 C/decada)
sub = ser[ser.idema == "1387"].sort_values("anio")
larga = p12.sen(sub.anio, sub.tx_verano) * 10
print(f"  pendiente sobre 60 anios: {larga:+.2f} C/decada (impuesta +0,25)")
assert 0.05 < larga < 0.45, f"deberia recuperar la tendencia impuesta, dio {larga}"

# y las ventanas de 15 anios tienen que dispersarse mucho mas
cortas = []
for i in range(len(sub) - 15 + 1):
    w = sub.iloc[i:i + 15]
    cortas.append(p12.sen(w.anio, w.tx_verano) * 10)
cortas = np.array(cortas)
print(f"  ventanas de 15 anios: de {cortas.min():+.2f} a {cortas.max():+.2f}, "
      f"desviacion {cortas.std():.2f}")
assert cortas.std() > abs(larga) * 0.5, \
    ("las ventanas cortas deben dispersarse mucho mas que la larga: es todo el "
     "argumento del paso")
assert cortas.max() > larga * 2, \
    "alguna ventana corta debe exagerar la tendencia; si no, no hay nada que avisar"
assert "ventana corta menos serie completa" in texto or \
       "Ninguna serie llega" in texto
print("  ok: la serie larga recupera la tendencia y las ventanas cortas mienten")

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASO 12 VALIDADO")
