"""Cliente minimo para el servidor THREDDS de MeteoGalicia.

El catalogo de MeteoGalicia no esta documentado de forma estable y, sobre todo,
**la jerarquia de URL no refleja la jerarquia del catalogo**: hay catalogos
estaticos colgando de /thredds/catalogos/... y datasetScan colgando de
/thredds/catalog/..., y un nodo intermedio puede no existir como fichero aunque
sus hijos si. Por eso aqui no se construye ninguna ruta a mano: se parte del
catalogo raiz y se siguen los enlaces `catalogRef` tal cual vienen, resolviendo
cada href contra la URL del catalogo que lo contiene.

Servicios que usamos:
  catalog.xml   listado de conjuntos y subcatalogos
  ncss          NetCDF Subset Service: recorta por variable, area y tiempo
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urljoin

import requests

# MeteoGalicia ha movido el THREDDS. El historico `mandeo.meteogalicia.es`
# devolvia HTTP 502 en julio de 2026; el servicio vivo es `thredds.meteogalicia.gal`.
# Se prueban en orden y se usa el primero que responda, para que el kit siga
# funcionando si vuelven a cambiarlo (o si resucita el antiguo).
HOSTS = [
    "https://thredds.meteogalicia.gal/thredds",
    "https://mandeo.meteogalicia.es/thredds",
]
# Rutas confirmadas a mano navegando el servidor. No sustituyen al recorrido del
# catalogo: se anaden como semillas porque en este servidor el indice de la raiz
# esta obsoleto (sus href dan 404) y el nodo intermedio `modelos` no existe como
# fichero, asi que hay ramas vivas a las que no se puede llegar desde la raiz.
SEMILLAS = [
    # LA importante: el indice de la raiz (/thredds/catalog.xml) trae href
    # relativos del tipo `catalogos/WRF/...`, que resueltos contra la raiz dan
    # /thredds/catalogos/... y 404. El MISMO indice servido desde
    # /thredds/catalog/catalog.xml resuelve a /thredds/catalog/catalogos/...,
    # que si existe. Es un prefijo de diferencia y desbloquea el arbol entero.
    "catalog/catalog.xml",
    "catalog/modelos/WRF_ARW_1KM_HIST/catalog.xml",
]
RAIZ = os.environ.get("GAL_THREDDS") or HOSTS[0]
CATALOGO_RAIZ = f"{RAIZ}/catalog.xml"
NS = {"c": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0",
      "xlink": "http://www.w3.org/1999/xlink"}

S = requests.Session()
S.headers["User-Agent"] = (
    "Mozilla/5.0 (compatible; analisis-climatico-galicia/2.0; +python-requests)")


class ErrorThredds(RuntimeError):
    pass


def _get(url, params=None, intentos=3, timeout=120, stream=False):
    ultimo = None
    for k in range(intentos):
        try:
            r = S.get(url, params=params, timeout=timeout, stream=stream)
            if r.status_code in (500, 502, 503, 504):
                ultimo = f"HTTP {r.status_code}"
                time.sleep(4 * (k + 1))
                continue
            if r.status_code >= 400:
                # El cuerpo de un 400 de TDS dice exactamente que parametro no
                # le gusta ("Variable rh not found", "accept format not
                # supported"...). Tirarlo y quedarse solo con el codigo
                # convierte un diagnostico de un minuto en una tarde de
                # adivinanzas.
                cuerpo = ""
                if not stream:
                    try:
                        cuerpo = re.sub(r"<[^>]+>", " ", r.text)
                        cuerpo = " " + re.sub(r"\s+", " ", cuerpo).strip()[:300]
                    except Exception:  # noqa: BLE001
                        cuerpo = ""
                raise ErrorThredds(f"HTTP {r.status_code}{cuerpo}")
            return r
        except ErrorThredds:
            raise
        except requests.RequestException as e:
            ultimo = f"{e.__class__.__name__}: {e}"
            time.sleep(4 * (k + 1))
    raise ErrorThredds(str(ultimo))


def _tag(el):
    return el.tag.split("}")[-1]


def fija_raiz(url):
    """Cambia el servidor THREDDS en uso (afecta tambien a los endpoints NCSS)."""
    global RAIZ, CATALOGO_RAIZ
    RAIZ = url.rstrip("/")
    CATALOGO_RAIZ = f"{RAIZ}/catalog.xml"
    return RAIZ


def detecta_host(traza=None):
    """Elige el primer host de HOSTS cuyo catalogo raiz responda.

    Devuelve (url_elegida, [(url, estado), ...]). Si ninguno responde deja el
    valor actual y lo indica en la lista de estados: quien llama decide si
    abortar o seguir.
    """
    if os.environ.get("GAL_THREDDS"):
        return fija_raiz(os.environ["GAL_THREDDS"]), [("GAL_THREDDS", "forzado")]
    estados = []
    for h in HOSTS:
        try:
            r = _get(f"{h}/catalog.xml", intentos=1, timeout=45)
            estados.append((h, f"OK, {len(r.content):,} bytes"))
            fija_raiz(h)
            return RAIZ, estados
        except ErrorThredds as e:
            estados.append((h, f"FALLA {e}"))
    return RAIZ, estados


RE_A = re.compile(rb"<a\s[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
                  re.I | re.S)


def enlaces_html(url):
    """(subcatalogos, ficheros) a partir de un catalog.html en vez de catalog.xml.

    Hace falta porque en `thredds.meteogalicia.gal` el catalog.xml de la raiz es
    una copia del del servidor viejo: los titulos son correctos pero los `href`
    apuntan a rutas que en este servidor devuelven 404. La pagina HTML, que es
    la que genera el propio TDS, si trae los enlaces buenos.

    CUIDADO con los ficheros: en el HTML aparecen como `?dataset=<id>`, y el `id`
    NO es el `urlPath`. En este servidor el id es
    `WRF_ARW_1KM_HIST/20260727/wrf_...nc4` mientras que la ruta real de los
    servicios es `modelos/WRF_ARW_1KM_HIST/20260727/wrf_...nc4`. Por eso, si esta
    pagina lista ficheros, se prefiere el catalog.xml hermano, que si trae el
    `urlPath` autentico; el id solo se usa si no hay XML.
    """
    r = _get(url)
    subs, ficheros, vistos = [], [], set()
    for href, texto in RE_A.findall(r.content):
        h = href.decode("utf-8", "replace").strip()
        t = re.sub(r"\s+", " ",
                   re.sub(r"<[^>]+>", "", texto.decode("utf-8", "replace"))).strip()
        if not h or h.startswith(("#", "mailto:", "javascript:")):
            continue
        if "dataset=" in h:
            up = unquote(h.split("dataset=", 1)[1].split("&")[0])
            if up and up not in vistos:
                vistos.add(up)
                ficheros.append((t or up.rsplit("/", 1)[-1], up))
        elif re.search(r"catalog\.(html|xml)$", h, re.I):
            u = urljoin(url, h)
            if u.rstrip("/") == url.rstrip("/") or u in vistos:
                continue
            vistos.add(u)
            subs.append((t.rstrip("/") or u, u))

    if ficheros:
        alt = re.sub(r"\.html?$", ".xml", url, flags=re.I)
        try:
            _, autenticos = _catalogo_xml(alt)
            if autenticos:
                return subs, autenticos
        except ErrorThredds:
            pass
    return subs, ficheros


def catalogo(url):
    """Lee un catalog.xml y devuelve (subcatalogos, ficheros).

    `url` es la URL completa del catalogo.
    subcatalogos: lista de (titulo, url_completa)
    ficheros:     lista de (nombre, urlPath)   -- urlPath es relativo al servicio

    Si el .xml no existe o es ilegible se reintenta con el .html hermano. Solo
    se acepta ese respaldo si aporta algo: si tampoco da nada, se propaga el
    error original en vez de fingir un catalogo vacio.
    """
    if re.search(r"\.html?$", url, re.I):
        return enlaces_html(url)
    try:
        return _catalogo_xml(url)
    except ErrorThredds as err:
        alt = re.sub(r"\.xml$", ".html", url, flags=re.I)
        if alt != url:
            try:
                s, f = enlaces_html(alt)
                if s or f:
                    return s, f
            except ErrorThredds:
                pass
        raise err


def _catalogo_xml(url):
    """Lectura estricta de un catalog.xml. Sin respaldos: los pone `catalogo`."""
    r = _get(url)
    try:
        raiz = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise ErrorThredds(
            f"XML ilegible ({e}); primeros bytes: {r.content[:120]!r}")

    subs, ficheros = [], []
    for el in raiz.iter():
        t = _tag(el)
        if t == "catalogRef":
            href = (el.get(f"{{{NS['xlink']}}}href")
                    or el.get("href") or "")
            if not href:
                continue
            titulo = (el.get(f"{{{NS['xlink']}}}title") or el.get("name")
                      or el.get("ID") or href)
            subs.append((titulo, urljoin(url, href)))
        elif t == "dataset":
            up = el.get("urlPath")
            if up:
                ficheros.append((el.get("name") or up.rsplit("/", 1)[-1], up))
    return subs, ficheros


ES_FECHA = re.compile(r"^(19|20)\d{2}((0[1-9]|1[0-2])((0[1-9]|[12]\d|3[01]))?)?$")


def descubre_wrf(max_prof=4, max_peticiones=200, traza=None):
    """Recorre el catalogo desde la raiz buscando conjuntos que suenen a WRF.

    Devuelve lista de (titulo, url_catalogo). Si se pasa `traza` (una lista),
    se le anaden lineas de diagnostico: cada catalogo visitado, cuantos hijos
    tenia y que error dio, si lo hubo.
    """
    def log(t):
        if traza is not None:
            traza.append(t)

    encontrados, vistos, vivos = [], set(), {}
    # Se entra por tres sitios a la vez: el catalog.xml de la raiz (indice
    # obsoleto pero con los titulos buenos), el catalog.html de la raiz (que
    # genera el propio TDS y trae los enlaces vivos) y las semillas confirmadas.
    pendientes = [(CATALOGO_RAIZ, "raiz", 0),
                  (f"{RAIZ}/catalog.html", "raiz(html)", 0)]
    pendientes += [(f"{RAIZ}/{s}", f"semilla:{s.split('/')[-2]}", 1)
                   for s in SEMILLAS]
    peticiones = 0

    while pendientes and peticiones < max_peticiones:
        url, titulo, prof = pendientes.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        peticiones += 1
        try:
            subs, ficheros = catalogo(url)
        except ErrorThredds as e:
            vivos[url] = False
            log(f"  [{prof}] {titulo}: ERROR {e}   <- {url}")
            continue
        vivos[url] = True
        log(f"  [{prof}] {titulo}: {len(subs)} subcatalogos, "
            f"{len(ficheros)} ficheros   <- {url}")
        # Tambien cuenta el nodo que se acaba de abrir, no solo sus hijos: si no,
        # una semilla que apunte directamente a un conjunto WRF se recorreria
        # entera y se descartaria despues por no haber sido "descubierta".
        if ("wrf" in (titulo + url).lower()
                and not ES_FECHA.match(titulo.strip())
                and titulo != "raiz"):
            encontrados.append((titulo.replace("semilla:", ""), url))

        for tit, sub in subs:
            es_fecha = bool(ES_FECHA.match(tit.strip()))
            # Un nodo de fecha hereda "wrf" de la URL del padre
            # (.../WRF_ARW_1KM_HIST/20260727/catalog.xml). Contarlo como
            # conjunto llenaria la lista con miles de dias y dejaria fuera los
            # conjuntos de verdad.
            if "wrf" in (tit + sub).lower() and not es_fecha:
                encontrados.append((tit, sub))
            # No se baja por los nodos de fecha (2025, 202507, 20250715...):
            # son las hojas del arbol y hay miles. Bajar por ahi agota el
            # presupuesto de peticiones sin encontrar nada nuevo, y ademas
            # impide llegar a ramas hondas como modelos/wrf/rawoutput/wrf_4km.
            if prof < max_prof and not es_fecha:
                pendientes.append((sub, tit, prof + 1))

    if peticiones >= max_peticiones:
        log(f"  (tope de {max_peticiones} peticiones alcanzado)")

    # Solo se devuelven los conjuntos que de verdad se pueden abrir. En este
    # servidor el indice de la raiz lista conjuntos cuyo href da 404: si se
    # colaran, la eleccion automatica acabaria escogiendo uno inexistente
    # (y ademas con mejor puntuacion que el bueno, por como esta el nombre).
    fuera, seen, muertos = [], set(), []
    for t, u in encontrados:
        if u in seen:
            continue
        seen.add(u)
        if u not in vivos:
            try:
                catalogo(u)
                vivos[u] = True
            except ErrorThredds as e:
                vivos[u] = False
                log(f"  descartado (no se abre: {e}): {t} <- {u}")
        if vivos[u]:
            fuera.append((t, u))
        else:
            muertos.append(t)
    if muertos:
        log(f"  conjuntos listados pero inalcanzables: {', '.join(muertos)}")
    return fuera


def plantilla_desde_ejemplo(url_conjunto, max_niveles=4, prefiere=None):
    """Deduce como se construyen las rutas de fichero de un conjunto WRF.

    Baja por el ultimo subcatalogo de cada nivel (que suele ser la fecha mas
    reciente) hasta topar con ficheros, y a partir de uno de ellos deduce los
    patrones de strftime del directorio y del nombre.
    """
    subs, ficheros = catalogo(url_conjunto)
    recorrido = []
    url = url_conjunto
    for _ in range(max_niveles):
        if ficheros:
            break
        if not subs:
            raise ErrorThredds(f"{url}: ni subcatalogos ni ficheros")
        titulo, url = subs[-1]
        recorrido.append(titulo)
        subs, ficheros = catalogo(url)

    if not ficheros:
        raise ErrorThredds(f"{url_conjunto}: no se encontro ningun fichero")

    # Un mismo dia publica varios dominios anidados: en WRF_ARW_1KM_HIST estan
    # d02 (1 km) y d01 (5 km) en la misma carpeta. Quedarse con el primero es
    # jugarsela al orden del catalogo, asi que se puede exigir cual.
    ejemplo = ficheros[0][1]
    if prefiere:
        coincide = [u for _, u in ficheros if prefiere in u.rsplit("/", 1)[-1]]
        if not coincide:
            raise ErrorThredds(
                f"ningun fichero contiene '{prefiere}'; hay "
                f"{[u.rsplit('/', 1)[-1] for _, u in ficheros[:6]]}")
        ejemplo = coincide[0]
    nombre_fich = ejemplo.rsplit("/", 1)[-1]
    FECHA = r"(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"

    partes = []
    for p in ejemplo.rsplit("/", 1)[0].split("/"):
        if re.fullmatch(r"(19|20)\d{2}", p):
            partes.append("%Y")
        elif re.fullmatch(FECHA, p):
            partes.append("%Y%m%d")
        elif re.fullmatch(r"(0[1-9]|1[0-2])", p) and "%Y" in partes:
            partes.append("%m")
        elif re.fullmatch(r"(0[1-9]|[12]\d|3[01])", p) and "%m" in partes:
            partes.append("%d")
        else:
            partes.append(p)

    return {"patron_catalogo": "/".join(partes),
            "patron_fichero": re.sub(rf"(?<!\d){FECHA}(?!\d)", "%Y%m%d", nombre_fich),
            "ejemplo": ejemplo,
            "recorrido": recorrido,
            # el catalogo donde vive de verdad el fichero: es ahi donde se
            # declaran los <service>, no en el nodo raiz del conjunto
            "url_hoja": url,
            "n_ficheros_ejemplo": len(ficheros)}


def rango_fechas(url_conjunto):
    """Hasta donde llega hacia atras el archivo de un conjunto.

    Es la pregunta que decide si un conjunto sirve: el WRF de 1 km puede tener
    una rejilla estupenda y solo tres anios de archivo, en cuyo caso hay que
    usar el de 4 km. Devuelve dict con primera, ultima y numero de fechas, o
    None si el conjunto no esta organizado por fechas.

    Solo hace UNA peticion: el catalogo del conjunto ya lista todas sus fechas.
    """
    subs, _ = catalogo(url_conjunto)
    fechas = sorted(t.strip() for t, _ in subs if ES_FECHA.match(t.strip()))
    if not fechas:
        return None
    completas = [f for f in fechas if len(f) == 8]
    return {"primera": fechas[0], "ultima": fechas[-1], "n": len(fechas),
            "por_dia": len(completas) == len(fechas),
            "anios": sorted({f[:4] for f in fechas})}


def servicios(url):
    """{tipo: base_absoluta} de los <service> declarados en un catalog.xml.

    Adivinar la ruta del NetcdfSubset es innecesario: cada catalogo declara sus
    servicios y sus bases. TDS 4.x publica el NCSS en /thredds/ncss/ y TDS 5.x
    en /thredds/ncss/grid/, y ademas cada instalacion puede cambiarlo. Leerlo
    del propio catalogo evita el problema entero, y de paso dice si hay OPeNDAP
    y descarga directa, que son los planes B y C.
    """
    try:
        raiz = ET.fromstring(_get(url).content)
    except (ErrorThredds, ET.ParseError):
        return {}
    fuera = {}
    for el in raiz.iter():
        if _tag(el) != "service":
            continue
        base, tipo = el.get("base"), (el.get("serviceType") or "").lower()
        if base and tipo and tipo != "compound":
            fuera[tipo] = urljoin(url, base)
    return fuera


def urls_ncss(url_path, base=None):
    """Endpoints NCSS candidatos, con el declarado por el catalogo el primero."""
    up = url_path.lstrip("/")
    cands = []
    if base:
        cands.append(base.rstrip("/") + "/" + up)
    cands += [f"{RAIZ}/ncss/grid/{up}", f"{RAIZ}/ncss/{up}"]
    fuera, vistos = [], set()
    for c in cands:
        if c not in vistos:
            vistos.add(c)
            fuera.append(c)
    return fuera


def describe(url_path, base=None, errores=None):
    """Metadatos de un fichero: variables, rejilla y extension geografica.

    La descripcion de un dataset NCSS esta en `<endpoint>/dataset.xml`, no en el
    endpoint pelado: pedir el endpoint a secas devuelve el formulario HTML y no
    hay forma de distinguirlo de un fallo. Se prueban ambas formas y, si `errores`
    es una lista, se anota que dio cada intento en vez de devolver un None mudo.
    """
    def nota(t):
        if errores is not None:
            errores.append(t)

    for u in urls_ncss(url_path, base):
        for sufijo, params in (("/dataset.xml", None), ("", {"dataset": url_path})):
            try:
                r = _get(u + sufijo, params=params, intentos=2)
            except ErrorThredds as e:
                nota(f"{e}  {u}{sufijo}")
                continue
            try:
                raiz = ET.fromstring(r.content)
            except ET.ParseError:
                nota(f"no es XML ({len(r.content):,} B, "
                     f"{r.content[:60]!r})  {u}{sufijo}")
                continue
            variables = sorted({g.get("name") for g in raiz.iter("grid")
                                if g.get("name")})
            if not variables:  # a veces el XML es una pagina de error valida
                variables = sorted({v.get("name") for v in raiz.iter("variable")
                                    if v.get("name")})
            if not variables:
                nota(f"XML sin variables  {u}{sufijo}")
                continue
            ejes = {a.get("name"): a.get("shape") for a in raiz.iter("axis")}
            bbox = {}
            for b in raiz.iter("LatLonBox"):
                bbox = {c.tag: c.text for c in b}
            return {"endpoint": u, "variables": variables, "ejes": ejes,
                    "bbox": bbox}
    return None


def descarga_opendap(url_path, destino, variables, bbox, base_dods,
                     inicio=None, fin=None, stride=1):
    """Plan B: recorta por OPeNDAP en vez de por NCSS.

    Sirve para lo mismo -- pedir dos variables, un trozo de mapa y 24 horas de
    un fichero de 743 MB -- pero por otra via, porque el NCSS de esta
    instalacion puede estar limitado o desactivado. Diferencias practicas:

      - El NCSS entiende de latitud y longitud; OPeNDAP solo entiende de
        indices, asi que hay que traducir la caja a filas y columnas.
      - OPeNDAP hace varias peticiones pequenias en vez de una grande, lo que lo
        hace mas lento pero mucho mas dificil de que lo rechacen por tamanio.

    Necesita netCDF4 compilado con soporte DAP, que es lo normal en las ruedas
    de PyPI.
    """
    import numpy as np
    import xarray as xr

    if os.path.exists(destino) and os.path.getsize(destino) > 5000:
        return "cache"
    n, o, s, e = bbox
    url = base_dods.rstrip("/") + "/" + url_path.lstrip("/")
    ds = xr.open_dataset(url, decode_times=True)
    try:
        presentes = [v for v in variables if v in ds.variables]
        if not presentes:
            raise ErrorThredds(f"ninguna de {variables} en {list(ds.data_vars)[:15]}")
        ds = ds[presentes]

        # --- recorte geografico: hay que distinguir rejilla regular de proyectada
        nom_lat = next((c for c in ("lat", "latitude") if c in ds.coords), None)
        nom_lon = next((c for c in ("lon", "longitude") if c in ds.coords), None)
        if nom_lat and ds[nom_lat].ndim == 1:
            lat, lon = ds[nom_lat].values, ds[nom_lon].values
            ds = ds.sel({nom_lat: slice(s, n) if lat[0] < lat[-1] else slice(n, s),
                         nom_lon: slice(o, e) if lon[0] < lon[-1] else slice(e, o)})
        elif nom_lat and ds[nom_lat].ndim == 2:
            la, lo = ds[nom_lat].values, ds[nom_lon].values
            dentro = (la >= s) & (la <= n) & (lo >= o) & (lo <= e)
            if not dentro.any():
                raise ErrorThredds(f"la caja {bbox} no corta la rejilla del fichero")
            filas, cols = np.where(dentro)
            dy, dx = ds[nom_lat].dims
            ds = ds.isel({dy: slice(filas.min(), filas.max() + 1),
                          dx: slice(cols.min(), cols.max() + 1)})
        if stride > 1:
            ejes = [d for d in ds.dims if d.lower() not in ("time", "valid_time")]
            ds = ds.isel({d: slice(None, None, stride) for d in ejes[-2:]})

        # --- recorte temporal: el fichero trae la pasada entera (72-96 h)
        dt = next((d for d in ("time", "valid_time", "Time") if d in ds.dims), None)
        if dt and inicio and fin:
            ds = ds.sel({dt: slice(inicio, fin)})
            if ds.sizes.get(dt, 0) == 0:
                raise ErrorThredds(f"sin pasos de tiempo entre {inicio} y {fin}")

        tmp = destino + ".parcial"
        ds.load().to_netcdf(tmp)
    finally:
        ds.close()
    if os.path.getsize(tmp) < 5000:
        os.remove(tmp)
        raise ErrorThredds("fichero resultante vacio")
    os.replace(tmp, destino)
    return url


def descarga_ncss(url_path, destino, variables, bbox, endpoint=None,
                  stride=1, acepta="netcdf4", inicio=None, fin=None, base=None):
    """Descarga un recorte NCSS. bbox = (norte, oeste, sur, este).

    `inicio` y `fin` son ISO-8601 UTC. Importan mas de lo que parece: los
    ficheros operativos de MeteoGalicia contienen la pasada completa (72-96 h de
    prediccion), no solo el dia de la fecha. Sin filtro temporal se descarga
    cuatro veces mas de lo necesario y ademas se mezclan alcances de prediccion
    distintos, que no son comparables entre si.
    """
    if os.path.exists(destino) and os.path.getsize(destino) > 5000:
        return "cache"
    n, o, s, e = bbox
    params = {"var": ",".join(variables), "north": n, "west": o, "south": s,
              "east": e, "horizStride": stride, "accept": acepta,
              "addLatLon": "true"}
    if inicio and fin:
        params["time_start"] = inicio
        params["time_end"] = fin
    candidatos = [endpoint] if endpoint else urls_ncss(url_path, base)
    ultimo = None
    for u in candidatos:
        try:
            r = _get(u, params=params, stream=True, intentos=2, timeout=600)
        except ErrorThredds as ex:
            ultimo = str(ex)
            continue
        tmp = destino + ".parcial"
        total = 0
        with open(tmp, "wb") as fh:
            for trozo in r.iter_content(1 << 20):
                fh.write(trozo)
                total += len(trozo)
        if total < 5000:  # casi seguro una pagina de error
            os.remove(tmp)
            ultimo = f"respuesta de solo {total} bytes"
            continue
        os.replace(tmp, destino)
        return u
    raise ErrorThredds(f"{url_path}: {ultimo}")
