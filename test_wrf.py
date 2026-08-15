"""Pruebas de los pasos 5 y 6 sin tocar la red.

Se simula un servidor THREDDS con la estructura real de MeteoGalicia
(catalogos anidados por fecha, ficheros wrf_arw_det_history_dNN_YYYYMMDD_HHMM.nc4)
para comprobar que el descubrimiento de rutas funciona sin tener nada codificado
a mano. Despues se fabrican campos WRF sinteticos con un patron sub-rejilla
conocido y se comprueba que el paso 6 lo recupera.
"""
import glob
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import xarray as xr

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)

# Directorio de trabajo aislado. Sin esto, las pruebas borrarian descargas/ y
# wrf/ reales, que son horas de descarga.
TMP = os.path.join(KIT, "_pruebas_tmp")
shutil.rmtree(TMP, ignore_errors=True)
os.makedirs(TMP)
shutil.copy(os.path.join(KIT, "celdas_galicia.csv"), TMP)
os.environ["GAL_BASE"] = TMP
ENTORNO = dict(os.environ)

import thredds  # noqa: E402

# ---------------------------------------------------------------------------
# 1. Servidor THREDDS simulado
# ---------------------------------------------------------------------------
# Se reproduce lo que hace de verdad MeteoGalicia y que rompio la primera
# version: la jerarquia de URL NO coincide con la del catalogo. El catalogo raiz
# apunta a la vez a /thredds/catalog/modelos/... (datasetScan) y a
# /thredds/catalogos/DATOS/ARCHIVE/... (catalogos estaticos), y un nodo
# intermedio puede no existir como fichero aunque sus hijos si.
NSC = "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"
NSX = "http://www.w3.org/1999/xlink"
H = "https://thredds.meteogalicia.gal/thredds"      # el host vivo
H_MUERTO = "https://mandeo.meteogalicia.es/thredds"  # el que devuelve 502

FECHAS_FALSAS = ["20230715", "20240802", "20250604", "20260727"]


# Bloque <service> tal y como lo publica TDS: compuesto, con las bases reales.
# La del NCSS cambia entre TDS 4.x (/thredds/ncss/) y 5.x (/thredds/ncss/grid/),
# asi que adivinarla es justamente lo que no hay que hacer.
SERVICIOS = (
    '<service name="todo" serviceType="Compound" base="">'
    # base deliberadamente distinta de las dos habituales: si el codigo la
    # adivina en vez de leerla, esta prueba falla
    '<service name="ncss" serviceType="NetcdfSubset" base="/thredds/subset/grid/"/>'
    '<service name="dap" serviceType="OPENDAP" base="/thredds/dodsC/"/>'
    '<service name="http" serviceType="HTTPServer" base="/thredds/fileServer/"/>'
    "</service>")


def cat(cuerpo, servicios=""):
    return (f'<?xml version="1.0"?><catalog xmlns="{NSC}" xmlns:xlink="{NSX}">'
            f"{servicios}{cuerpo}</catalog>").encode()


def ref(titulo, href):
    return f'<catalogRef xlink:title="{titulo}" xlink:href="{href}" name="{titulo}"/>'


def ds(nombre, urlpath):
    return f'<dataset name="{nombre}" urlPath="{urlpath}"/>'


CATALOGOS = {
    # raiz: mezcla las dos jerarquias, y una de ellas cuelga de /catalogos/
    f"{H}/catalog.xml": cat(
        ref("Modelos numericos", "catalog/modelos/catalog.xml")
        + ref("Arquivo WRF", "catalogos/DATOS/ARCHIVE/WRF/WRF_hist.xml")
        + ref("Observacion", "catalog/observacion/catalog.xml")),

    # este nodo intermedio NO existe como fichero: devuelve 404, igual que en
    # el servidor real. El recorrido tiene que sobrevivir a esto.
    f"{H}/catalog/observacion/catalog.xml": None,

    f"{H}/catalog/modelos/catalog.xml": cat(
        ref("WRF_ARW_1KM_HIST", "WRF_ARW_1KM_HIST/catalog.xml")
        + ref("wrf", "wrf/catalog.xml")
        + ref("ROMS", "ROMS/catalog.xml")),
    # rama honda y en minusculas, como la real: modelos/wrf/rawoutput/wrf_4km
    f"{H}/catalog/modelos/wrf/catalog.xml": cat(ref("rawoutput", "rawoutput/catalog.xml")),
    f"{H}/catalog/modelos/wrf/rawoutput/catalog.xml": cat(
        ref("wrf_4km", "wrf_4km/catalog.xml")),
    f"{H}/catalog/modelos/wrf/rawoutput/wrf_4km/catalog.xml": cat(
        ds("wrf_arw_det_history_d02_20250715_0000.nc4",
           "modelos/wrf/rawoutput/wrf_4km/wrf_arw_det_history_d02_20250715_0000.nc4")),
    f"{H}/catalog/modelos/ROMS/catalog.xml": cat(""),
    f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml": cat(
        "".join(ref(f, f"{f}/catalog.xml") for f in FECHAS_FALSAS)),

    # el archivo historico, en la otra rama de URL
    f"{H}/catalogos/DATOS/ARCHIVE/WRF/WRF_hist.xml": cat(
        ref("d01", "d01/catalog.xml") + ref("d02", "d02/catalog.xml")
        + ref("d03", "d03/catalog.xml")),
}
for f in FECHAS_FALSAS:
    # El urlPath real NO lleva el prefijo `modelos/` que si tiene la URL del
    # catalogo. Si se dedujera la ruta de descarga a partir de la URL en vez de
    # leer el atributo urlPath, todas las peticiones NCSS darian 404.
    CATALOGOS[f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/{f}/catalog.xml"] = cat(
        ds(f"wrf_arw_det_history_d02_{f}_0000.nc4",
           f"WRF_ARW_1KM_HIST/{f}/wrf_arw_det_history_d02_{f}_0000.nc4"),
        servicios=SERVICIOS)
for d in ("d01", "d02", "d03"):
    base = f"{H}/catalogos/DATOS/ARCHIVE/WRF"
    CATALOGOS[f"{base}/{d}/catalog.xml"] = cat(ref("2025", "2025/catalog.xml"))
    CATALOGOS[f"{base}/{d}/2025/catalog.xml"] = cat(ref("07", "07/catalog.xml"))
    CATALOGOS[f"{base}/{d}/2025/07/catalog.xml"] = cat(
        ds(f"wrf_arw_det_history_{d}_20250715_0000.nc4",
           f"modelos/WRF_HIST/{d}/2025/07/wrf_arw_det_history_{d}_20250715_0000.nc4"),
        servicios=SERVICIOS)

XML_NCSS = b"""<?xml version="1.0"?>
<gridDataset location="test">
  <axis name="time" shape="24"/>
  <axis name="y" shape="180"/>
  <axis name="x" shape="200"/>
  <grid name="temp"/><grid name="rh"/><grid name="mslp"/><grid name="swflx"/>
  <LatLonBox><west>-9.5</west><east>-6.5</east><south>41.7</south><north>44.0</north></LatLonBox>
</gridDataset>"""


# Un formulario HTML de verdad no es XML bien formado (meta sin cerrar, &nbsp;).
# Con un "<html/>" de juguete la prueba pasaria sin comprobar nada.
FORMULARIO_HTML = (
    b'<!DOCTYPE html><html lang="gl"><head><meta charset="utf-8">'
    b"<title>NetCDF Subset Service</title></head><body>"
    b"<h3>Variables:</h3>&nbsp;<form><input name=var>"
    b"</form></body></html>")


class RespFalsa:
    def __init__(self, contenido):
        self.content = contenido
        self.status_code = 200


def _get_falso(url, params=None, intentos=3, timeout=120, stream=False):
    if url.startswith(H_MUERTO):
        raise thredds.ErrorThredds("HTTP 502")
    if url in CATALOGOS:
        if CATALOGOS[url] is None:
            raise thredds.ErrorThredds("HTTP 404")
        return RespFalsa(CATALOGOS[url])
    # El NCSS real solo describe el dataset en <endpoint>/dataset.xml. Pedir el
    # endpoint pelado devuelve el formulario HTML, que NO es un fallo HTTP: si el
    # codigo no lo distingue, cree que ha descrito el fichero y no ha descrito nada.
    # Va antes que el filtro generico de .xml porque dataset.xml tambien lo es.
    if "/subset/grid/" in url or "/ncss/" in url:
        if url.startswith(f"{H}/subset/grid/") and url.endswith("/dataset.xml"):
            return RespFalsa(XML_NCSS)
        if url.endswith("/dataset.xml"):
            raise thredds.ErrorThredds("HTTP 404")
        return RespFalsa(FORMULARIO_HTML)
    if url.endswith("catalog.xml") or url.endswith(".xml"):
        raise thredds.ErrorThredds("HTTP 404")
    if url.endswith("catalog.html"):
        return RespFalsa(b"<html/>")
    raise thredds.ErrorThredds(f"inesperado {url}")


thredds._get = _get_falso

print("=== eleccion de servidor ===")
# 1) el orden normal: el primero de la lista responde
thredds.HOSTS = [H, H_MUERTO]
raiz, estados = thredds.detecta_host()
for h, e in estados:
    print(f"  {e:24s} {h}")
assert raiz == H and thredds.CATALOGO_RAIZ == f"{H}/catalog.xml"

# 2) el caso que motivo todo esto: el primero esta caido y hay que pasar al
#    siguiente sin intervencion manual
thredds.HOSTS = [H_MUERTO, H]
raiz, estados = thredds.detecta_host()
for h, e in estados:
    print(f"  {e:24s} {h}")
assert raiz == H, f"deberia haber caido al host vivo, uso {raiz}"
assert "502" in estados[0][1], estados
# y el cambio tiene que arrastrar tambien a los endpoints de descarga
assert thredds.urls_ncss("x/y.nc4")[0].startswith(H), thredds.urls_ncss("x/y.nc4")

# 3) ninguno responde: no debe explotar, debe decirlo
thredds.HOSTS = [H_MUERTO]
raiz, estados = thredds.detecta_host()
assert all("FALLA" in e for _, e in estados), estados
thredds.HOSTS = [H, H_MUERTO]
thredds.detecta_host()
print("  ok: elige el host vivo, cae al alternativo y no oculta el fallo total")

print("\n=== descubrimiento de conjuntos WRF ===")
traza = []
conj = thredds.descubre_wrf(traza=traza)
for t in traza:
    print(t)
urls = [u for _, u in conj]
print(f"  encontrados: {len(conj)}")
for t, u in conj:
    print(f"    {t:28s} {u}")

assert f"{H}/catalogos/DATOS/ARCHIVE/WRF/WRF_hist.xml" in urls, \
    "debe seguir el enlace a la rama /catalogos/, que no comparte prefijo de URL"
assert f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml" in urls
assert any(u.endswith("WRF/d03/catalog.xml") for u in urls), \
    "debe bajar tambien a los dominios del archivo historico"
assert not any("ROMS" in u for u in urls), "no debe colar conjuntos que no son WRF"
assert any("404" in t and "Observacion" in t for t in traza), \
    "un nodo roto debe quedar registrado en la traza, no desaparecer en silencio"
assert f"{H}/catalog/modelos/wrf/rawoutput/wrf_4km/catalog.xml" in urls, \
    "debe llegar a las ramas hondas (4 niveles) y reconocer 'wrf' en minusculas"
assert not any(t.strip().startswith("[4] 2025") for t in traza), \
    "no debe bajar por los nodos de fecha: son hojas y hay miles"
assert not any(f.split("/")[-1] in [u.rstrip("/").split("/")[-2] for u in urls]
               for f in FECHAS_FALSAS), \
    ("los nodos de fecha heredan 'wrf' de la URL del padre; si se cuelan, la "
     "lista de conjuntos se llena de dias y tapa a los conjuntos reales")
assert len(conj) <= 8, f"demasiados 'conjuntos': {len(conj)}"
print("  ok: dos jerarquias, un nodo roto, rama honda en minusculas, y sobrevive")

# ---------------------------------------------------------------------------
# 1 bis. El caso real de thredds.meteogalicia.gal: indice de la raiz obsoleto
# ---------------------------------------------------------------------------
# El catalog.xml de la raiz existe y trae 29 entradas con los titulos correctos,
# pero TODOS sus href devuelven 404: es una copia del indice del servidor viejo.
# La rama viva cuelga de /catalog/modelos/..., y su nodo intermedio `modelos`
# tampoco existe como fichero. Desde la raiz, por XML, no se llega a nada.
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "paso05", os.path.join(KIT, "05_wrf_dias_calidos.py"))
paso05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paso05)
paso05_pre_elige = paso05.elige_conjunto

H2 = "https://ejemplo.gal/thredds"
CATALOGOS.update({
    # indice obsoleto: titulos buenos, href muertos
    f"{H2}/catalog.xml": cat(
        ref("WRF_HIST", "catalogos/DATOS/ARCHIVE/WRF/WRF_hist.xml")
        + ref("WRF_1.3km_DEPRECATED_HIST", "catalogos/DATOS/ARCHIVE/WRF/WRF_1KM_hist.xml")
        + ref("WRF_1km_HIST", "catalogos/DATOS/ARCHIVE/WRF/WRF_1KM_hist_novo.xml")),
    # la pagina que genera el propio TDS si tiene los enlaces vivos
    f"{H2}/catalog.html": (
        b"<html><body><table>"
        b"<tr><td><a href='catalog/modelos/WRF_ARW_1KM_HIST/catalog.html'>"
        b"WRF_ARW_1KM_HIST/</a></td></tr>"
        b"<tr><td><a href='catalog/modelos/ROMS/catalog.html'>ROMS/</a></td></tr>"
        b"<tr><td><a href='#arriba'>volver</a></td></tr>"
        b"</table></body></html>"),
    f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.html": (
        b"<html><body>"
        b"<a href='20260726/catalog.html'>20260726/</a>"
        b"<a href='20260727/catalog.html'>20260727/</a>"
        b"</body></html>"),
    # En el HTML el fichero aparece como ?dataset=<id>, y el id NO lleva el
    # prefijo `modelos/` que si lleva la ruta real de los servicios. Usar el id
    # como urlPath da 404 en NCSS y en OPeNDAP.
    f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/20260727/catalog.html": (
        b"<html><body><a href='catalog.html?dataset=WRF_ARW_1KM_HIST/20260727/"
        b"wrf_arw_det_history_d02_20260727_0000.nc4'>"
        b"wrf_arw_det_history_d02_20260727_0000.nc4</a></body></html>"),
    f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/20260727/catalog.xml": cat(
        ds("wrf_arw_det_history_d02_20260727_0000.nc4",
           "modelos/WRF_ARW_1KM_HIST/20260727/"
           "wrf_arw_det_history_d02_20260727_0000.nc4"),
        servicios=SERVICIOS),
    f"{H2}/catalog/modelos/ROMS/catalog.html": b"<html><body></body></html>",
})

print("\n=== respaldo por HTML cuando el indice XML esta obsoleto ===")
thredds.fija_raiz(H2)
thredds.SEMILLAS = []          # sin semillas: tiene que apaniarselas solo
traza2 = []
conj2 = thredds.descubre_wrf(traza=traza2)
for t in traza2:
    print(t)
urls2 = [u for _, u in conj2]
print(f"  encontrados: {[t for t, _ in conj2]}")
assert f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.html" in urls2, \
    ("si la raiz solo se lee por XML no se llega a la rama viva; hay que "
     "entrar tambien por catalog.html")
assert not any("ROMS" in u for u in urls2)
# los tres del indice obsoleto no deben sobrevivir: uno de ellos
# ("WRF_1km_HIST", con "novo" en la URL) puntua MAS que el bueno, asi que si se
# colara la eleccion automatica se iria a un conjunto que no existe
assert len(conj2) == 1, [t for t, _ in conj2]
assert any("inalcanzables" in t for t in traza2), \
    "descartar en silencio seria peor que no descartar"
assert paso05_pre_elige(conj2)[0] == "WRF_ARW_1KM_HIST"

# El HTML da el `id` del dataset (sin `modelos/`); la ruta buena esta en el
# catalog.xml hermano. Hay que preferir el XML: con el id, NCSS y OPeNDAP dan 404.
HOJA = f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/20260727/catalog.html"
subs_h, fich_h = thredds.catalogo(HOJA)
print(f"  fichero: {fich_h[0][1]}")
assert fich_h == [("wrf_arw_det_history_d02_20260727_0000.nc4",
                   "modelos/WRF_ARW_1KM_HIST/20260727/"
                   "wrf_arw_det_history_d02_20260727_0000.nc4")], fich_h
assert fich_h[0][1].startswith("modelos/"), \
    "el id del HTML no vale como urlPath: le falta el prefijo del servicio"

pl_h = thredds.plantilla_desde_ejemplo(
    f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.html")
print(f"  plantilla por HTML: {pl_h['patron_catalogo']}/{pl_h['patron_fichero']}")
assert pl_h["patron_catalogo"] == "modelos/WRF_ARW_1KM_HIST/%Y%m%d", \
    pl_h["patron_catalogo"]

rf_h = thredds.rango_fechas(f"{H2}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.html")
assert rf_h and rf_h["n"] == 2 and rf_h["ultima"] == "20260727", rf_h
print("  ok: se navega por HTML igual que por XML, sin rutas a mano")

thredds.fija_raiz(H)
thredds.SEMILLAS = ["catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml"]

print("\n=== eleccion automatica ===")
elegido = paso05.elige_conjunto(conj)
print(f"  elegido: {elegido[0]}")
assert "1KM" in elegido[1] or "d03" in elegido[1], \
    f"deberia preferir la mayor resolucion historica, eligio {elegido}"
print("  ok")

print("\n=== deduccion de la plantilla de rutas ===")
pl = thredds.plantilla_desde_ejemplo(f"{H}/catalogos/DATOS/ARCHIVE/WRF/d03/catalog.xml")
print(f"  catalogo: {pl['patron_catalogo']}")
print(f"  fichero : {pl['patron_fichero']}")
assert pl["patron_catalogo"] == "modelos/WRF_HIST/d03/%Y/%m", pl["patron_catalogo"]
assert pl["patron_fichero"] == "wrf_arw_det_history_d03_%Y%m%d_0000.nc4", pl["patron_fichero"]
f = pd.Timestamp("2022-08-13")
reconstruido = f"{f.strftime(pl['patron_catalogo'])}/{f.strftime(pl['patron_fichero'])}"
assert reconstruido == \
    "modelos/WRF_HIST/d03/2022/08/wrf_arw_det_history_d03_20220813_0000.nc4", reconstruido
print(f"  reconstruida para 2022-08-13: {reconstruido}")

URL_1KM = f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml"
pl2 = thredds.plantilla_desde_ejemplo(URL_1KM)
print(f"  catalogo (1 km): {pl2['patron_catalogo']}")
assert pl2["patron_catalogo"] == "WRF_ARW_1KM_HIST/%Y%m%d", pl2["patron_catalogo"]
assert pl2["patron_fichero"] == "wrf_arw_det_history_d02_%Y%m%d_0000.nc4"
assert not pl2["patron_catalogo"].startswith("modelos/"), \
    "la ruta de descarga sale del atributo urlPath, no de la URL del catalogo"
print("  ok: dos estructuras de carpetas distintas, ninguna codificada a mano")

print("\n=== hasta donde llega el archivo ===")
rf = thredds.rango_fechas(URL_1KM)
print(f"  {rf['n']} fechas, {rf['primera']} .. {rf['ultima']}, anios {rf['anios']}")
assert rf["primera"] == "20230715" and rf["ultima"] == "20260727", rf
assert rf["n"] == len(FECHAS_FALSAS) and rf["por_dia"]
assert rf["anios"] == ["2023", "2024", "2025", "2026"], rf["anios"]
# un conjunto que no se organiza por fechas no debe inventarse un rango
assert thredds.rango_fechas(f"{H}/catalogos/DATOS/ARCHIVE/WRF/WRF_hist.xml") is None
print("  ok: una sola peticion basta para saber si un conjunto cubre 15 anios")

print("\n=== eleccion de dominio dentro de un mismo dia ===")
# Cada dia de WRF_ARW_1KM_HIST publica d02 (1 km) y d01 (5 km) en la misma
# carpeta. Coger el primero del catalogo es jugarsela al orden.
CATALOGOS[f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/20260727/catalog.xml"] = cat(
    ds("Saida d01 (5 km)",
       "modelos/WRF_ARW_1KM_HIST/20260727/wrf_arw_det_history_d01_20260727_0000.nc4")
    + ds("Saida d02 (1 km)",
         "modelos/WRF_ARW_1KM_HIST/20260727/wrf_arw_det_history_d02_20260727_0000.nc4"),
    servicios=SERVICIOS)
CONJ_1KM = f"{H}/catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml"
pl_d01 = thredds.plantilla_desde_ejemplo(CONJ_1KM)
print(f"  sin pedir dominio -> {pl_d01['patron_fichero']}")
assert "d01" in pl_d01["patron_fichero"], "el catalogo lista d01 primero"
pl_d02 = thredds.plantilla_desde_ejemplo(CONJ_1KM, prefiere="d02")
print(f"  pidiendo d02      -> {pl_d02['patron_fichero']}")
assert pl_d02["patron_fichero"] == "wrf_arw_det_history_d02_%Y%m%d_0000.nc4"
try:
    thredds.plantilla_desde_ejemplo(CONJ_1KM, prefiere="d09")
    raise AssertionError("un dominio inexistente debe fallar, no caer en otro")
except thredds.ErrorThredds as ex:
    print(f"  dominio inexistente: {str(ex)[:70]}")
print("  ok: se coge la malla de 1 km, no la que salga primero")

print("\n=== servicios declarados y descripcion por NCSS ===")
# los <service> se declaran en el catalogo donde vive el fichero, no en el nodo
# raiz del conjunto; plantilla_desde_ejemplo lo devuelve por eso
assert pl["url_hoja"] == f"{H}/catalogos/DATOS/ARCHIVE/WRF/d03/2025/07/catalog.xml", \
    pl["url_hoja"]
assert thredds.servicios(f"{H}/catalogos/DATOS/ARCHIVE/WRF/d03/catalog.xml") == {}, \
    "el nodo intermedio no declara servicios: por eso hace falta la hoja"
servs = thredds.servicios(pl["url_hoja"])
print(f"  servicios: {servs}")
assert servs["netcdfsubset"] == f"{H}/subset/grid/", servs
assert servs["opendap"] == f"{H}/dodsC/" and servs["httpserver"] == f"{H}/fileServer/"
assert "compound" not in servs, "el servicio compuesto no es un endpoint"

# sin la base declarada no hay forma de acertar: las rutas habituales no valen
fallos = []
assert thredds.describe(pl["ejemplo"], errores=fallos) is None
assert fallos, "un None mudo no permite diagnosticar nada"
print(f"  sin la base declarada: {len(fallos)} intentos fallidos, p.ej. {fallos[0][:70]}")
assert any("no es XML" in f for f in fallos), \
    ("el endpoint pelado devuelve el formulario HTML; hay que notar que no es "
     "una descripcion, no tomarlo por buena")

info = thredds.describe(pl["ejemplo"], base=servs["netcdfsubset"])
assert info and info["endpoint"].startswith(f"{H}/subset/grid/"), info
assert info["variables"] == ["mslp", "rh", "swflx", "temp"], info["variables"]
assert info["bbox"]["north"] == "44.0"
cands = [v for v in info["variables"] if v in paso05.VARS_CANDIDATAS]
assert "temp" in cands and "rh" in cands and "swflx" not in cands and "mslp" not in cands
print(f"  variables filtradas: {cands}  ok")

# ---------------------------------------------------------------------------
# 2. Seleccion de dias calidos desde ERA5-Land sintetico
# ---------------------------------------------------------------------------
print("\n=== recorte por OPeNDAP (plan B) ===")
# xarray abre una ruta local igual que una URL DAP, asi que la logica de
# recorte se puede probar de verdad sin red: lo que se comprueba es que la caja
# geografica y las 24 h se traducen bien, que es donde estan los errores.
DAP = os.path.join(TMP, "dap")
os.makedirs(DAP, exist_ok=True)
horas = pd.date_range("2026-07-27", periods=96, freq="h")   # pasada de 4 dias
glat = np.arange(40.0, 45.0, 0.05)                          # mas ancho que Galicia
glon = np.arange(-11.0, -5.0, 0.05)
campo = np.random.default_rng(1).normal(
    290, 5, (len(horas), len(glat), len(glon))).astype("float32")
xr.Dataset(
    {"temp": (("time", "lat", "lon"), campo),
     "rh": (("time", "lat", "lon"), campo * 0 + 60),
     "mslp": (("time", "lat", "lon"), campo * 0 + 101325)},
    coords={"time": horas, "lat": glat, "lon": glon},
).to_netcdf(os.path.join(DAP, "entero.nc"))

sal = os.path.join(TMP, "recorte.nc")
thredds.descarga_opendap(
    "entero.nc", sal, ["temp", "rh"], paso05.BBOX, DAP,
    inicio="2026-07-27T00:00:00", fin="2026-07-27T23:00:00")
rec = xr.open_dataset(sal)
print(f"  entero: {campo.shape} -> recorte: "
      f"{tuple(rec.sizes[d] for d in ('time', 'lat', 'lon'))}")
assert rec.sizes["time"] == 24, f"debe quedarse con 24 h, no {rec.sizes['time']}"
assert set(rec.data_vars) == {"temp", "rh"}, "mslp no se ha pedido"
n, o, s, e = paso05.BBOX
assert rec.lat.min() >= s - 0.05 and rec.lat.max() <= n + 0.05, "recorte en latitud"
assert rec.lon.min() >= o - 0.05 and rec.lon.max() <= e + 0.05, "recorte en longitud"
peso = os.path.getsize(sal) / os.path.getsize(os.path.join(DAP, "entero.nc"))
print(f"  el recorte pesa el {peso:.1%} del fichero completo")
assert peso < 0.05, f"el recorte deberia ser una fraccion minima, es {peso:.1%}"
rec.close()

# rejilla proyectada (lat/lon 2D), que es como publica el WRF crudo
LO2, LA2 = np.meshgrid(glon, glat)
xr.Dataset(
    {"temp": (("time", "y", "x"), campo[:24])},
    coords={"time": horas[:24], "lat": (("y", "x"), LA2), "lon": (("y", "x"), LO2)},
).to_netcdf(os.path.join(DAP, "curvo.nc"))
sal2 = os.path.join(TMP, "recorte2.nc")
thredds.descarga_opendap("curvo.nc", sal2, ["temp"], paso05.BBOX, DAP)
rec2 = xr.open_dataset(sal2)
print(f"  rejilla 2D: {LA2.shape} -> {rec2.temp.shape[1:]}")
assert rec2.temp.shape[1] < LA2.shape[0] and rec2.temp.shape[2] < LA2.shape[1]
assert float(rec2.lat.min()) >= s - 0.05 and float(rec2.lat.max()) <= n + 0.05
rec2.close()

# una caja fuera de la rejilla tiene que fallar con un mensaje claro, no
# devolver un fichero vacio que reventaria tres pasos mas adelante
try:
    thredds.descarga_opendap("curvo.nc", os.path.join(TMP, "nada.nc"),
                             ["temp"], (10.0, 100.0, 5.0, 110.0), DAP)
    raise AssertionError("deberia haber fallado: la caja no corta la rejilla")
except thredds.ErrorThredds as ex:
    print(f"  caja fuera de rejilla: {ex}")
print("  ok: recorta bien en rejilla regular y proyectada, y avisa si no corta")

print("\n=== seleccion de dias calidos ===")
# Los dias calidos se eligen sobre la cache diaria que produce 02_indices.py,
# no sobre los NetCDF horarios: es mucho mas rapido y ya esta en grados.
fechas = pd.date_range("2011-01-01", "2015-12-31", freq="D")
lats, lons = np.arange(41.8, 43.9, 0.1), np.arange(-9.3, -6.7, 0.1)
est = np.cos(2 * np.pi * (fechas.dayofyear.values - 200) / 365.25)
rng = np.random.default_rng(3)
pico = rng.gumbel(0, 2.0, len(fechas)) * np.clip(est, 0, None)
serie = 14 + 8 * est + pico
campo = (serie[:, None, None] + np.zeros((1, len(lats), len(lons)))).astype("float32")
xr.Dataset({"tmax": (("time", "latitude", "longitude"), campo)},
           coords={"time": fechas, "latitude": lats, "longitude": lons}
           ).to_netcdf(os.path.join(TMP, "diarios_galicia.nc"))

dc = paso05.dias_calidos(por_anio=10)
print(f"  {len(dc)} dias, {dc.index.year.min()}-{dc.index.year.max()}")
assert len(dc) == 50, len(dc)
assert dc.index.year.value_counts().eq(10).all(), "10 por anio exactos"
assert dc.index.month.isin([5, 6, 7, 8, 9]).all(), "solo temporada calida"
umbral = pd.Series(serie, index=fechas)
umbral = umbral[umbral.index.month.isin([5, 6, 7, 8, 9])]
assert dc.min() >= umbral.quantile(0.90), \
    "los elegidos deben estar en la cola calida de la distribucion"
print(f"  Tmax entre {dc.min():.1f} y {dc.max():.1f} C  ok")

# --- misma seleccion partiendo de las estaciones, sin la malla --------------
# Es lo que permite lanzar el WRF sin esperar a que acabe el Copernicus.
est_filas = []
for est, desfase in (("A", 0.0), ("B", -1.5), ("C", 2.0)):
    est_filas.append(pd.DataFrame({
        "fecha": fechas, "estacion": est,
        "tmax": serie + desfase + rng.normal(0, 0.3, len(fechas))}))
pd.concat(est_filas).to_csv(os.path.join(TMP, "estaciones_diario.csv"), index=False)

dc_est = paso05.dias_calidos(por_anio=10, fuente="estaciones")
solape = len(set(dc.index) & set(dc_est.index)) / len(dc)
print(f"  eligiendo desde estaciones: {len(dc_est)} dias, "
      f"solape con la malla {solape:.0%}")
assert len(dc_est) == 50
assert solape > 0.8, \
    ("si las dos fuentes no eligen practicamente los mismos dias, no se puede "
     f"sustituir una por otra: solape {solape:.0%}")

# y con `auto` la malla tiene preferencia cuando existe
s, origen = paso05.serie_galicia("auto")
assert "ERA5" in origen, origen
os.rename(os.path.join(TMP, "diarios_galicia.nc"),
          os.path.join(TMP, "diarios_guardado.nc"))
s, origen = paso05.serie_galicia("auto")
assert "estaciones" in origen, origen
os.rename(os.path.join(TMP, "diarios_guardado.nc"),
          os.path.join(TMP, "diarios_galicia.nc"))
print("  ok: mismas fechas por las dos vias, y auto prefiere la malla")

# ---------------------------------------------------------------------------
# 3. Paso 6: recuperacion del patron sub-rejilla
# ---------------------------------------------------------------------------
print("\n=== seleccion del nivel de 2 m ===")
spec6 = importlib.util.spec_from_file_location(
    "paso06", os.path.join(KIT, "06_alta_resolucion.py"))
paso06 = importlib.util.module_from_spec(spec6)
spec6.loader.exec_module(paso06)

varias = xr.DataArray(
    np.arange(3 * 2 * 2, dtype=float).reshape(3, 2, 2),
    dims=("height", "y", "x"), coords={"height": [2.0, 10.0, 100.0]})
sel = paso06.a_dos_metros(varias)
assert sel.shape == (2, 2) and float(sel[0, 0]) == 0.0, "debe coger el nivel de 2 m"

invertido = xr.DataArray(
    np.arange(3 * 2 * 2, dtype=float).reshape(3, 2, 2),
    dims=("height", "y", "x"), coords={"height": [100.0, 10.0, 2.0]})
sel = paso06.a_dos_metros(invertido)
assert float(sel[0, 0]) == 8.0, "no debe asumir que el primer nivel es el de abajo"

uno = xr.DataArray(np.zeros((1, 2, 2)), dims=("height", "y", "x"))
assert paso06.a_dos_metros(uno).shape == (2, 2)

sin_vert = xr.DataArray(np.zeros((4, 2, 2)), dims=("time", "y", "x"))
assert paso06.a_dos_metros(sin_vert).shape == (4, 2, 2), "sin eje vertical, no toca nada"
print("  ok: 2 m elegido correctamente aunque los niveles vengan al reves")

print("\n=== paso 6: fusion de escalas ===")
DW = os.path.join(TMP, "wrf")
shutil.rmtree(DW, ignore_errors=True)
os.makedirs(DW)

# rejilla de 1 km aproximada sobre Galicia
wlat = np.arange(41.85, 43.80, 0.009)
wlon = np.arange(-9.30, -6.75, 0.012)
LON, LAT = np.meshgrid(wlon, wlat)

# patron sub-rejilla conocido: valles calidos con longitud de onda de ~4 km,
# que es justo lo que una celda de 9 km promedia y hace desaparecer
patron = 2.5 * np.sin(LAT * 2 * np.pi / 0.036) * np.cos(LON * 2 * np.pi / 0.048)
# mas un gradiente de gran escala que SI ve ERA5-Land y que no debe colarse
# en la anomalia
gran_escala = 8.0 * (LON + 9.3) / 2.55

for i, f in enumerate(dc.index[:12]):
    horas = pd.date_range(f, periods=24, freq="h")
    ciclo = np.clip(np.sin((np.arange(24) - 6) * np.pi / 14), 0, None)
    base = 22 + gran_escala + patron + i * 0.2
    campo = (base[None] + 8 * ciclo[:, None, None]).astype("float32")
    rh = np.clip(90 - 2.0 * (campo - 20), 15, 100).astype("float32")
    xr.Dataset(
        {"temp": (("time", "y", "x"), campo + 273.15),
         "rh": (("time", "y", "x"), rh)},
        coords={"time": horas, "lat": (("y", "x"), LAT), "lon": (("y", "x"), LON)},
    ).to_netcdf(os.path.join(DW, f"wrf_{f:%Y%m%d}.nc"))
print(f"  {len(glob.glob(os.path.join(DW, '*.nc')))} ficheros WRF sinteticos "
      f"de {LAT.shape[0]}x{LAT.shape[1]} puntos")

# climatologia ERA5-Land de referencia, coherente con el gradiente de gran escala
celdas = pd.read_csv(os.path.join(TMP, "celdas_galicia.csv"))
celdas["tx_p99"] = 26 + 8.0 * (celdas.lon + 9.3) / 2.55
celdas["tx_verano"] = celdas.tx_p99 - 6
celdas["hx_p99"] = celdas.tx_p99 + 2
celdas.to_csv(os.path.join(TMP, "indices_galicia.csv"), index=False)

r = subprocess.run([sys.executable, "06_alta_resolucion.py"], cwd=KIT,
                   capture_output=True, text=True, env=ENTORNO)
print(r.stdout[-2500:])
if r.returncode != 0:
    print(r.stderr[-3000:])
    sys.exit("06_alta_resolucion.py fallo")

alta = pd.read_csv(os.path.join(TMP, "alta_resolucion.csv.gz"))
print(f"\n  filas: {len(alta):,}  columnas: {list(alta.columns)}")
assert len(alta) == LAT.size

# el patron fino debe recuperarse; el gradiente de gran escala NO debe aparecer
a = alta.anom_tx_medio.values
print(f"  anomalia recuperada: {a.min():+.2f} a {a.max():+.2f} C (impuesta +-2.5)")
assert a.std() > 0.8, f"deberia recuperar el patron fino, std={a.std():.2f}"
corr_gran = np.corrcoef(alta.lon.values, a)[0, 1]
print(f"  correlacion anomalia vs longitud: {corr_gran:+.3f} (debe ser ~0)")
assert abs(corr_gran) < 0.2, "el gradiente de gran escala se esta colando en la anomalia"

# la fusion debe conservar el gradiente de ERA5-Land
corr_fus = np.corrcoef(alta.lon.values, alta.tx_p99_1km.values)[0, 1]
print(f"  correlacion fusion vs longitud: {corr_fus:+.3f} (debe ser alta)")
assert corr_fus > 0.8, "la fusion debe conservar el gradiente de 30 anios"

rango_era = celdas.tx_p99.max() - celdas.tx_p99.min()
rango_fus = alta.tx_p99_1km.max() - alta.tx_p99_1km.min()
print(f"  rango ERA5-Land {rango_era:.1f} C -> tras fusion {rango_fus:.1f} C")
assert rango_fus > rango_era, "la fusion debe anadir contraste, no quitarlo"

for c in ("wrf_tx_medio", "wrf_tx_p90", "wrf_n_ge32", "wrf_hx_p90", "tx_p99_1km"):
    assert c in alta.columns, f"falta {c}"
assert alta.wrf_hx_p90.gt(alta.wrf_tx_p90 - 0.01).all(), "el humidex nunca baja de la T"

print("\n=== mascara de tierra: mar y embalses fuera ===")
# Reproduce lo que paso de verdad: el tercio oeste es oceano (frio y sin
# relieve) y hay un embalse tierra adentro. Sin mascara, los dos copan el
# ranking de "sitios frescos" y ademas enfrian el entorno de 9 km de la costa,
# que sale con una anomalia positiva que es puro artefacto.
mar = LON < -8.9
embalse = (np.abs(LAT - 42.6) < 0.02) & (np.abs(LON + 7.5) < 0.03)
agua = mar | embalse
topo_f = np.where(agua, 0.0, 50 + 900 * (LAT - 41.85) / 1.95)
usos_f = np.where(agua, 17.0, 5.0)          # 17 = agua en la tabla MODIS
xr.Dataset({"topo": (("y", "x"), topo_f), "land_use": (("y", "x"), usos_f)},
           coords={"lat": (("y", "x"), LAT), "lon": (("y", "x"), LON)},
           ).to_netcdf(os.path.join(DW, "estaticos.nc"))

for i, f in enumerate(dc.index[:12]):        # rehace los dias con agua fria
    horas = pd.date_range(f, periods=24, freq="h")
    ciclo = np.clip(np.sin((np.arange(24) - 6) * np.pi / 14), 0, None)
    base = np.where(agua, 18.0, 22 + gran_escala + patron + i * 0.2)
    campo = (base[None] + np.where(agua, 1.0, 8.0) * ciclo[:, None, None]).astype("float32")
    rh = np.clip(90 - 2.0 * (campo - 20), 15, 100).astype("float32")
    xr.Dataset({"temp": (("time", "y", "x"), campo + 273.15),
                "rh": (("time", "y", "x"), rh)},
               coords={"time": horas, "lat": (("y", "x"), LAT),
                       "lon": (("y", "x"), LON)},
               ).to_netcdf(os.path.join(DW, f"wrf_{f:%Y%m%d}.nc"))

r = subprocess.run([sys.executable, "06_alta_resolucion.py"], cwd=KIT,
                   capture_output=True, text=True, env=ENTORNO)
if r.returncode != 0:
    print(r.stdout[-1500:], r.stderr[-2000:])
    sys.exit("06 fallo con mascara")
print("  " + "\n  ".join(l for l in r.stdout.splitlines()
                         if "tierra" in l or "agua" in l or "desviacion" in l
                         or "sin separar" in l))

alta2 = pd.read_csv(os.path.join(TMP, "alta_resolucion.csv.gz"))
assert "tierra" in alta2.columns and "altitud" in alta2.columns
frac = alta2.tierra.mean()
print(f"  tierra detectada: {frac:.1%} (impuesto {(~agua).mean():.1%})")
assert abs(frac - (~agua).mean()) < 0.02, "la categoria de agua no se dedujo bien"

# 1) el ranking no puede estar copado por el agua
firme = alta2[alta2.tierra == 1]
frescos = firme.nsmallest(20, "wrf_tx_p90")
assert (frescos.lon > -8.9).all(), "el oceano se ha colado entre los mas frescos"
assert not ((frescos.lat - 42.6).abs() < 0.03).any() or \
       not ((frescos.lon + 7.5).abs() < 0.04).any(), "el embalse se ha colado"

# 2) y la costa no debe salir artificialmente calida respecto a su entorno
costa = firme[(firme.lon > -8.9) & (firme.lon < -8.75)]
interior = firme[(firme.lon > -7.5) & (firme.lon < -7.2)]
sesgo = costa.anom_tx_medio.mean() - interior.anom_tx_medio.mean()
print(f"  sesgo costa-interior en la anomalia: {sesgo:+.2f} C (debe ser ~0)")
assert abs(sesgo) < 0.6, \
    (f"la costa sale {sesgo:+.2f} C respecto al interior: el mar sigue "
     f"entrando en la media de 9 km")
assert alta2.loc[alta2.tierra == 0, "anom_tx_medio"].isna().all(), \
    "el agua no debe tener anomalia, ni siquiera calculada"
print("  ok: agua fuera del ranking y fuera de la media de 9 km")

print("\n=== prueba fisica: relieve frente a fallo del modelo ===")
# Se anade un bloque de 2x2 km que esta 8 C mas frio que su entorno SIN que la
# topografia lo acompanie. Es el caso real de Ourense: no es agua, no esta alto,
# y no puede ser cierto. Tiene que quedar marcado y fuera del ranking.
fallo = (np.abs(LAT - 42.70) < 0.010) & (np.abs(LON + 7.90) < 0.014)
print(f"  bloque artificial de {fallo.sum()} puntos, 8 C por debajo de su entorno")
for i, f in enumerate(dc.index[:12]):
    horas = pd.date_range(f, periods=24, freq="h")
    ciclo = np.clip(np.sin((np.arange(24) - 6) * np.pi / 14), 0, None)
    # la temperatura sigue al relieve (gradiente de -6.5 C/km) salvo en el fallo
    base = np.where(agua, 18.0,
                    22 + gran_escala + patron - 6.5e-3 * topo_f + i * 0.2)
    base = np.where(fallo, base - 8.0, base)
    campo = (base[None] + np.where(agua, 1.0, 8.0) * ciclo[:, None, None]).astype("float32")
    rh = np.clip(90 - 2.0 * (campo - 20), 15, 100).astype("float32")
    xr.Dataset({"temp": (("time", "y", "x"), campo + 273.15),
                "rh": (("time", "y", "x"), rh)},
               coords={"time": horas, "lat": (("y", "x"), LAT),
                       "lon": (("y", "x"), LON)},
               ).to_netcdf(os.path.join(DW, f"wrf_{f:%Y%m%d}.nc"))

r = subprocess.run([sys.executable, "06_alta_resolucion.py"], cwd=KIT,
                   capture_output=True, text=True, env=ENTORNO)
if r.returncode != 0:
    print(r.stdout[-1500:], r.stderr[-2000:])
    sys.exit("06 fallo en la prueba fisica")
print("  " + "\n  ".join(l.strip() for l in r.stdout.splitlines()
                         if "gradiente" in l or "correlacion con" in l
                         or "incompatibles" in l or "NO es relieve" in l))

alta3 = pd.read_csv(os.path.join(TMP, "alta_resolucion.csv.gz"))
assert {"anom_altitud", "residuo", "sospechoso"} <= set(alta3.columns)

# 1) el gradiente ajustado tiene que salir cerca del que se impuso (-6.5 C/km)
grad = [l for l in r.stdout.splitlines() if "gradiente ajustado" in l][0]
val = float(grad.split(":")[1].split("C")[0])
print(f"  gradiente recuperado {val:+.2f} C/km frente a -6.50 impuesto")
assert -9 < val < -4, f"deberia recuperar el gradiente fisico, dio {val}"

# 2) el bloque falso, marcado; y casi nada mas
marcados = alta3[alta3.sospechoso == 1]
print(f"  marcados: {len(marcados)} de {int(alta3.tierra.sum())} puntos de tierra")
en_bloque = ((marcados.lat - 42.70).abs() < 0.012) & ((marcados.lon + 7.90).abs() < 0.016)
assert en_bloque.mean() > 0.8, \
    f"solo el {en_bloque.mean():.0%} de los marcados es el bloque falso: hay falsos positivos"
assert len(marcados) >= fallo.sum() * 0.5, "no ha cazado el bloque falso"

# 3) y no debe aparecer en el ranking de sitios frescos
res = open(os.path.join(TMP, "resumen_alta_resolucion.txt"), encoding="utf-8").read()
assert "42.70" not in res and "42.69" not in res, \
    "el bloque falso se ha colado en el resumen como sitio fresco"
print("  ok: recupera el gradiente fisico y marca lo que no lo cumple")

mb = os.path.getsize(os.path.join(TMP, "alta_resolucion.csv.gz")) / 1e6
print(f"  fichero comprimido: {mb:.1f} MB (limite de GitHub: 100 MB)")
assert mb < 90

shutil.rmtree(TMP, ignore_errors=True)
print("\nPASOS 5 Y 6 VALIDADOS")
