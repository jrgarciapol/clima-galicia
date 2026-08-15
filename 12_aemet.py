"""PASO 12 - Series largas de AEMET, para la unica pregunta que no podemos responder.

Todo lo demas de este proyecto se apoya en 15-17 anios. Basta para *ordenar*
sitios entre si y no basta para *medir* un ritmo de calentamiento: una ventana
que empieza en 2010-2011 y termina con los veranos de 2022 en adelante infla la
pendiente, y no hay forma de separar el cambio climatico de la variabilidad
decenal dentro de esa ventana.

AEMET tiene en Galicia una decena de observatorios con series diarias de decadas.
No sirven para el ranking -- estan en aeropuertos y ciudades, y son muy pocos --
pero sirven para lo otro. Y sobre todo permiten **medir el sesgo de la ventana
corta**: calcular la pendiente sobre la serie completa y sobre todas las ventanas
de 15 anios posibles, y ver cuanto se separan. Eso convierte una advertencia
cualitativa en un numero.

Uso
---
    python 12_aemet.py --explorar
        No descarga series. Comprueba la clave, lista los observatorios de
        Galicia con su periodo, y **mide contra el servidor** cual es el rango
        maximo de fechas por peticion, que la documentacion no fija y las
        fuentes de terceros contradicen. Escribe aemet_exploracion.txt.

    python 12_aemet.py --descargar --desde 1960 --estaciones 1387,1428,1495
        Descarga las series. Es reanudable: lo ya bajado se salta. El servidor
        solo admite 6 meses por peticion, asi que son dos peticiones por anio y
        estacion: conviene elegir a mano las que tengan serie larga.

    python 12_aemet.py --analizar
        Indices anuales, pendiente de Sen y el contraste ventana corta / serie
        completa. Escribe aemet_series.csv y resumen_aemet.txt.

La clave
--------
NO se escribe en este fichero. Se lee, por este orden, de:
    la variable de entorno AEMET_API_KEY
    el fichero ~/.aemetrc   (una sola linea con la clave)
Igual que .cdsapirc, ~/.aemetrc va fuera del proyecto y NUNCA al repositorio.

Licencia: los datos son de AEMET y su uso obliga a citarla como autora.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

BASE = os.environ.get("GAL_BASE") or os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(BASE, "aemet")
RAIZ = "https://opendata.aemet.es/opendata/api"

# Provincias que nos interesan. AEMET las escribe en mayusculas y sin acentos.
PROVINCIAS = {"A CORUÑA", "A CORUNA", "LA CORUÑA", "LUGO", "OURENSE", "ORENSE",
              "PONTEVEDRA"}

# 40 peticiones por minuto segun las FAQ; se deja margen porque cada descarga
# son DOS peticiones (la que devuelve la URL y la que trae los datos).
PAUSA = 3.2

# MESES por peticion. Medido contra el servidor el 29-07-2026: rechaza cualquier
# rango mayor y lo dice con todas las letras, "El rango de fechas no puede ser
# superior a 6 meses". La primera version de este script probaba en anios y no
# bajaba de 1, con lo que TODAS las peticiones eran invalidas -- y como el
# sondeo de decadas tambien pedia anios enteros, el informe concluyo que ninguna
# estacion tenia datos antes de 2010. No era verdad: es que ninguna peticion
# era valida. Un limite mal medido no da un error claro, da un resultado falso.
MESES_POR_PETICION = 6


class ErrorAemet(RuntimeError):
    """El servidor ha contestado y dice que no hay datos. Es definitivo."""


class ErrorRed(RuntimeError):
    """La conexion ha fallado. NO dice nada sobre si hay datos o no.

    La distincion es lo mas importante de este fichero. Si un corte de red se
    confunde con un "no hay datos", se escribe un fichero vacio, se marca como
    hecho y ese trozo de serie queda como ausente PARA SIEMPRE, sin que nada lo
    delate. Un hueco silencioso en una serie de 80 anios es mucho peor que un
    error ruidoso.
    """


def clave():
    k = os.environ.get("AEMET_API_KEY")
    if k:
        return k.strip()
    # En Windows, ~ es C:\Users\<tu_usuario>, el mismo sitio donde ya esta
    # .cdsapirc. Se acepta tambien .aemetrc.txt porque el Bloc de notas anade
    # esa extension sin avisar y es el error mas probable.
    for nombre in (".aemetrc", ".aemetrc.txt"):
        ruta = os.path.expanduser(os.path.join("~", nombre))
        if not os.path.exists(ruta):
            continue
        with open(ruta, encoding="utf-8-sig") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                # OJO: no partir por "=" a la ligera. La clave es un JWT en
                # base64url y puede llevar "=" de relleno al final; partirla
                # por ahi la destroza y el error que sale es un 401 confuso.
                # Solo se quita el prefijo si es un "clave=" explicito.
                for pref in ("api_key", "apikey", "clave", "key"):
                    if linea.lower().startswith(pref):
                        resto = linea[len(pref):].lstrip()
                        if resto.startswith((":", "=")):
                            linea = resto[1:].strip()
                        break
                return linea.strip().strip('"').strip("'")
    # Un "no la encuentro" a secas no ayuda: hay que decir DONDE se ha mirado.
    # El error tipico es dejarla en la carpeta del proyecto, donde ademas no se
    # ve con `ls` porque empieza por punto.
    msg = ["No encuentro la clave de AEMET. He mirado en:",
           "  la variable de entorno AEMET_API_KEY: "
           + ("definida pero vacia" if "AEMET_API_KEY" in os.environ
              else "no definida")]
    for nombre in (".aemetrc", ".aemetrc.txt"):
        r = os.path.expanduser(os.path.join("~", nombre))
        msg.append(f"  {r}: {'existe pero esta vacio' if os.path.exists(r) else 'no existe'}")

    # ¿esta en el sitio equivocado? es lo que pasa nueve de cada diez veces
    aqui = []
    for d in (os.path.dirname(os.path.abspath(__file__)), os.getcwd(), BASE):
        for nombre in (".aemetrc", ".aemetrc.txt", "aemetrc.txt", "aemetrc"):
            r = os.path.join(d, nombre)
            if os.path.exists(r) and r not in aqui:
                aqui.append(r)
    if aqui:
        msg.append("")
        msg.append("PERO la he encontrado aqui, que no es donde se busca:")
        for r in aqui:
            msg.append(f"  {r}")
        msg.append("")
        msg.append("Muevela a tu carpeta personal:")
        msg.append(f"  mv \"{aqui[0]}\" \"{os.path.expanduser('~/.aemetrc')}\"")
        msg.append("")
        msg.append("No se lee de la carpeta del proyecto a proposito: ahi acaba")
        msg.append("subida al repositorio, y el .gitignore no protege si los")
        msg.append("ficheros se suben a mano por el navegador.")
    else:
        msg += ["",
                "  Windows:  setx AEMET_API_KEY \"tu_clave\"  (y abre consola nueva)",
                "  Linux:    echo 'tu_clave' > ~/.aemetrc",
                "",
                "Recuerda que empieza por punto y `ls` no la muestra: usa `ls -la ~`."]
    sys.exit("\n".join(msg))


def caducidad(k):
    """La clave es un JWT y lleva dentro su fecha de caducidad. Conviene mirarla:
    las FAQ dicen que no expira y las que emite el portal duran 100 dias."""
    import base64
    try:
        carga = k.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        d = json.loads(base64.urlsafe_b64decode(carga))
        return datetime.fromtimestamp(d["exp"], timezone.utc).date()
    except Exception:  # noqa: BLE001
        return None


S = requests.Session()
S.headers["User-Agent"] = "analisis-climatico-galicia/1.0 (+python-requests)"


def _get(url, k=None, timeout=90):
    """GET con reintentos ante fallos de transporte.

    Una descarga de 3.300 peticiones dura horas, y en horas la red se cae: el
    servidor cierra una conexion ociosa, el wifi parpadea, el DNS tarda. Sin
    esto, cualquiera de esas cosas mata la ejecucion entera.
    """
    ultimo = None
    for n in range(5):
        try:
            return S.get(url, params={"api_key": k} if k else None,
                         timeout=timeout)
        except requests.RequestException as e:
            ultimo = f"{e.__class__.__name__}: {str(e)[:80]}"
            espera = 5 * (2 ** n)          # 5, 10, 20, 40, 80 s
            print(f"    red: {ultimo}; reintento en {espera} s", flush=True)
            time.sleep(espera)
    raise ErrorRed(ultimo)


def _pide(url, k, intentos=4):
    """Una peticion de AEMET son dos saltos: la primera devuelve un JSON con la
    URL donde estan los datos de verdad, y hay que ir a buscarlos alli."""
    for n in range(intentos):
        r = _get(url, k)
        if r.status_code == 429:            # limite de peticiones por minuto
            time.sleep(20 * (n + 1))
            continue
        if r.status_code == 401:
            raise ErrorAemet("clave rechazada (401). ¿Ha caducado?")
        if r.status_code == 404:
            raise ErrorAemet("404: no hay datos para ese rango o esa estacion")
        if r.status_code >= 500:
            time.sleep(8 * (n + 1))
            continue
        if r.status_code >= 400:
            raise ErrorAemet(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            meta = r.json()
        except ValueError:
            raise ErrorAemet(f"respuesta no es JSON: {r.text[:200]}")
        estado = meta.get("estado")
        if estado == 429:
            time.sleep(20 * (n + 1))
            continue
        if estado == 404:
            raise ErrorAemet(f"sin datos: {meta.get('descripcion', '')}")
        if estado != 200 or "datos" not in meta:
            raise ErrorAemet(f"estado {estado}: {meta.get('descripcion', '')}")

        # El segundo salto es el que se cayo en la Raspberry: iba sin
        # reintentos y sin capturar excepciones de red.
        d = _get(meta["datos"], timeout=180)
        if d.status_code != 200:
            raise ErrorRed(f"la URL de datos dio HTTP {d.status_code}")
        # AEMET sirve los ficheros en ISO-8859-15, no en UTF-8: sin esto los
        # nombres con ñ y con acento llegan rotos.
        for cod in ("utf-8", "iso-8859-15", "latin-1"):
            try:
                return json.loads(d.content.decode(cod))
            except (UnicodeDecodeError, ValueError):
                continue
        raise ErrorAemet("no se pudo decodificar el fichero de datos")
    raise ErrorAemet("agotados los reintentos")


def inventario(k):
    filas = _pide(f"{RAIZ}/valores/climatologicos/inventarioestaciones/todasestaciones/", k)
    fuera = []
    for e in filas:
        prov = (e.get("provincia") or "").strip().upper()
        if prov not in PROVINCIAS:
            continue
        fuera.append({
            "idema": e.get("indicativo"), "nombre": (e.get("nombre") or "").title(),
            "provincia": prov.title(), "altitud": num(e.get("altitud")),
            "lat": grados(e.get("latitud")), "lon": grados(e.get("longitud")),
        })
    return fuera


def grados(t):
    """AEMET da las coordenadas como 431825N o 081930W, no en decimal."""
    if not t:
        return None
    t = str(t).strip()
    signo = -1 if t[-1] in "WS" else 1
    n = t[:-1]
    try:
        g, m, sg = int(n[:-4]), int(n[-4:-2]), int(n[-2:])
    except ValueError:
        return None
    return round(signo * (g + m / 60 + sg / 3600), 5)


def num(t):
    """Los numeros vienen como cadenas con coma decimal ('23,4'). Ademas hay
    marcas especiales: 'Ip' es precipitacion inapreciable y 'Acum' acumulada."""
    if t is None:
        return None
    t = str(t).strip()
    if t in ("", "Ip", "Acum", "Varias"):
        return 0.0 if t == "Ip" else None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def diarios(k, idema, ini, fin):
    url = (f"{RAIZ}/valores/climatologicos/diarios/datos"
           f"/fechaini/{ini:%Y-%m-%d}T00:00:00UTC"
           f"/fechafin/{fin:%Y-%m-%d}T23:59:59UTC/estacion/{idema}/")
    return _pide(url, k)


def suma_meses(f, m):
    a, mes = divmod(f.month - 1 + m, 12)
    return date(f.year + a, mes + 1, 1)


def mide_limite(k, idema, traza):
    """Cuantos MESES admite de verdad una peticion.

    Dos vias, y la primera es la buena: cuando el servidor rechaza un rango
    suele decir por que, y ese mensaje trae el limite exacto. Leerlo ahorra la
    escalera entera. Si no lo dice, se prueba de mayor a menor.

    No basta con que la peticion no falle: tambien se comprueba que la respuesta
    cubra el mes de inicio. Un servidor que acepta y devuelve solo un trozo es
    peor que uno que falla, porque no avisa.
    """
    import re
    hoy = date.today().replace(day=1) - timedelta(days=1)
    for meses in (24, 12, 6, 3, 1):
        ini = suma_meses(hoy.replace(day=1), -meses + 1)
        try:
            d = diarios(k, idema, ini, hoy)
        except ErrorAemet as e:
            traza.append(f"  {meses:2d} meses: RECHAZADO ({str(e)[:95]})")
            m = re.search(r"no puede ser superior a\s+(\d+)\s*mes", str(e), re.I)
            if m:
                lim = int(m.group(1))
                traza.append(f"  -> el propio servidor dice el limite: {lim} meses")
                return lim
            time.sleep(PAUSA)
            continue
        fechas = sorted(x.get("fecha", "") for x in d if x.get("fecha"))
        if not fechas:
            traza.append(f"  {meses:2d} meses: aceptado pero sin datos")
            time.sleep(PAUSA)
            continue
        cubre = fechas[0][:7] <= f"{ini:%Y-%m}"
        traza.append(f"  {meses:2d} meses: OK, {len(d):,} dias, "
                     f"{fechas[0][:10]} .. {fechas[-1][:10]}"
                     f"{'' if cubre else '   <- NO cubre el inicio pedido'}")
        if cubre:
            return meses
        time.sleep(PAUSA)
    traza.append("  ninguno de los rangos probados vale; se usara 1 mes")
    return 1


# ---------------------------------------------------------------------------

def explorar(k, max_est=20):
    """Reconocimiento. Tarda varios minutos y va IMPRIMIENDO segun avanza.

    La primera version lo acumulaba todo y lo escribia al final: desde fuera era
    indistinguible de un cuelgue, porque son del orden de cien peticiones con
    pausa obligada entre ellas para no pasarse del limite de la API.
    """
    L = []

    def p(*a):
        t = " ".join(str(x) for x in a)
        print(t, flush=True)
        L.append(t)

    p(f"AEMET OpenData - reconocimiento {datetime.now():%Y-%m-%d %H:%M}")
    cad = caducidad(k)
    p(f"clave: ...{k[-12:]}   caduca {cad or 'desconocido'}"
      + (f"  ({(cad - date.today()).days} dias)" if cad else ""))
    p("")
    p("Esto tarda entre cinco y diez minutos: la API admite 40 peticiones por")
    p("minuto y hay que esperar entre una y otra. Va imprimiendo segun avanza.")
    p("")

    # OJO al orden: esto tiene que leerse ANTES de volver a escribir el
    # inventario. En la primera version se leia despues, y como el inventario
    # recien bajado no trae el campo `desde`, la cache salia siempre vacia y
    # volvia a sondear las 58. Un fallo de orden, no de logica, y por eso
    # silencioso: el script funcionaba, solo que tiraba media hora cada vez.
    previo = {}
    ruta_prev = os.path.join(BASE, "aemet_estaciones.json")
    if os.path.exists(ruta_prev):
        try:
            for x in json.load(open(ruta_prev, encoding="utf-8")):
                if x.get("desde"):
                    previo[x["idema"]] = x["desde"]
        except Exception:  # noqa: BLE001
            pass

    p("--- observatorios en Galicia ---")
    try:
        inv = inventario(k)
    except ErrorAemet as e:
        p(f"  ERROR: {e}")
        escribe(L)
        return
    inv.sort(key=lambda e: (e["provincia"], e["nombre"]))
    p(f"  {len(inv)} estaciones")
    p(f"  {'idema':7s} {'nombre':32s} {'prov':11s} {'alt':>5s} "
      f"{'lat':>9s} {'lon':>9s}")
    for e in inv:
        p(f"  {e['idema']:7s} {e['nombre'][:32]:32s} "
          f"{e['provincia'][:11]:11s} {str(e['altitud'] or '?'):>5s} "
          f"{e['lat']:>9} {e['lon']:>9}")
    for e in inv:                      # no perder lo ya sondeado al reescribir
        if e["idema"] in previo:
            e["desde"] = previo[e["idema"]]
    json.dump(inv, open(ruta_prev, "w"), ensure_ascii=False, indent=1)
    if previo:
        p(f"  ({len(previo)} traian ya su anio de inicio de una pasada anterior)")
    p("")

    time.sleep(PAUSA)
    p("--- rango maximo por peticion, medido contra el servidor ---")
    p("  (la documentacion no lo fija y las fuentes de terceros discrepan)")
    ref = inv[0]["idema"] if inv else None
    if ref:
        p(f"  estacion de prueba: {ref}")
        traza = []
        lim = mide_limite(k, ref, traza)
        for t in traza:
            p(t)
        p(f"  -> se usaran bloques de {lim} MESES")
    p("")

    p("--- hasta donde llega hacia atras cada serie ---")
    ESCALA = (1940, 1960, 1980, 2000, 2015)
    # Lo ya sondeado en ejecuciones anteriores se conserva: repetir --explorar
    # con mas estaciones no debe volver a gastar cien peticiones en las que ya
    # se conocen.
    n = min(len(inv), max_est)
    faltan = [e for e in inv[:n] if e["idema"] not in previo]
    p(f"  {n} estaciones, {len(previo)} ya sondeadas antes, {len(faltan)} por sondear")
    p(f"  hasta {len(faltan) * len(ESCALA)} peticiones, unos "
      f"{len(faltan) * len(ESCALA) * PAUSA / 60:.0f} minutos. Se pide una decena")
    p("  de dias por sondeo, no un anio entero: solo interesa si HAY datos.")
    for i, e in enumerate(inv[:n], 1):
        if e["idema"] in previo:
            e["desde"] = previo[e["idema"]]
        else:
            prim = None
            for anio in ESCALA:
                try:
                    if diarios(k, e["idema"], date(anio, 1, 1), date(anio, 1, 10)):
                        prim = anio
                        break
                except ErrorAemet:
                    pass
                time.sleep(PAUSA)
            e["desde"] = prim
        p(f"  [{i}/{n}] {e['idema']:7s} {e['nombre'][:30]:30s} "
          f"{'datos ya en ' + str(e['desde']) if e['desde'] else 'nada antes de 2015'}"
          f"{'   (ya se sabia)' if e['idema'] in previo else ''}")
    json.dump(inv, open(ruta_prev, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    largas = sorted((e for e in inv if e.get("desde") and e["desde"] <= 1980),
                    key=lambda e: e["desde"])
    if largas:
        p("")
        p("--- las que sirven para la tendencia (serie de 45 anios o mas) ---")
        for e in largas:
            anios = 2025 - e["desde"] + 1
            p(f"  {e['idema']:7s} {e['nombre'][:30]:30s} desde {e['desde']}  "
              f"~{anios} anios  ({anios * 2} peticiones, "
              f"{anios * 2 * PAUSA / 60:.0f} min)")
        p("")
        p("  Para descargarlas SIN --desde: con el, todas arrancarian en el anio")
        p("  mas antiguo de la lista y las que empiezan tarde gastarian cientos")
        p("  de peticiones vacias. Sin el, cada una arranca en su propio anio.")
        p(f"    python 12_aemet.py --descargar "
          f"--estaciones {','.join(e['idema'] for e in largas)}")
        pet = sum((2025 - e["desde"] + 1) * 2 for e in largas)
        p(f"    ({pet:,} peticiones, ~{pet * (PAUSA + 1.5) / 3600:.1f} h)")
    todas = sum((2025 - (e.get("desde") or 1950) + 1) * 2 for e in inv)
    p("")
    p(f"  Y para bajarlas TODAS ({len(inv)} estaciones), que es lo que hace falta")
    p("  para validar el modelo en los cabos:")
    p("    python 12_aemet.py --descargar")
    p(f"    ({todas:,} peticiones, ~{todas * (PAUSA + 1.5) / 3600:.1f} h)")
    escribe(L)


def escribe(L):
    texto = "\n".join(L)
    ruta = os.path.join(BASE, "aemet_exploracion.txt")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    print(f"\nEscrito {ruta}")
    print("Subelo al repositorio y con el inventario real decidimos que bajar.")


def descargar(k, desde, hasta, meses, solo=None):
    os.makedirs(DIR, exist_ok=True)
    ruta_inv = os.path.join(BASE, "aemet_estaciones.json")
    if not os.path.exists(ruta_inv):
        sys.exit("Falta aemet_estaciones.json. Ejecuta antes --explorar")
    inv = json.load(open(ruta_inv, encoding="utf-8"))
    if solo:
        pedidas = {x.strip().upper() for x in solo.split(",")}
        inv = [e for e in inv if e["idema"].upper() in pedidas]
        if not inv:
            sys.exit(f"Ninguna estacion de {sorted(pedidas)} esta en el inventario")

    # Cada estacion arranca donde arranca. Pedir 1940 para una que empieza en
    # 2000 son 120 peticiones que devuelven vacio: casi una hora tirada. El
    # sondeo de --explorar ya dejo anotado el inicio de cada una.
    fin = date(hasta, 12, 31)
    plan = {}
    for e in inv:
        ini = desde if desde else (e.get("desde") or 1950)
        f, bl = date(max(ini, 1900), 1, 1), []
        while f <= fin:
            g = min(suma_meses(f, meses) - timedelta(days=1), fin)
            bl.append((f, g))
            f = g + timedelta(days=1)
        plan[e["idema"]] = bl

    # Las de serie mas larga primero. Son 4-5 horas: si se corta a mitad,
    # conviene que lo descargado sea lo mas valioso, no lo alfabeticamente
    # anterior.
    inv.sort(key=lambda e: (e.get("desde") or 9999, e["nombre"]))

    total = sum(len(b) for b in plan.values())
    seg = total * (PAUSA + 1.5)
    print(f"{len(inv)} estaciones, bloques de {meses} meses, "
          f"{total:,} peticiones en total")
    for e in inv:
        ini = desde if desde else (e.get("desde") or 1950)
        print(f"    {e['idema']:6s} {e['nombre'][:24]:24s} desde {ini}  "
              f"{len(plan[e['idema']]):4d} peticiones")
    print(f"\nTiempo estimado: {seg / 3600:.1f} horas "
          f"({PAUSA:.1f} s de pausa obligada + ~1,5 s de respuesta por peticion).")
    print("Es reanudable: puedes cortarlo y relanzarlo cuando quieras; lo ya")
    print("descargado se salta sin gastar peticion.\n")

    n, pendientes = 0, []
    for e in inv:
        vivos = 0
        for a, b in plan[e["idema"]]:
            n += 1
            destino = os.path.join(DIR, f"{e['idema']}_{a:%Y%m}_{b:%Y%m}.json")
            # `> 0`, no `> 2`: un periodo sin datos se guarda como `[]`, que son
            # exactamente 2 bytes. Con el umbral en 2 se volvia a pedir en cada
            # ejecucion, y una estacion que empieza en 1990 son decenas de
            # peticiones tiradas cada vez, para siempre.
            if os.path.exists(destino) and os.path.getsize(destino) > 0:
                continue
            aviso = ""
            try:
                d = diarios(k, e["idema"], a, b)
            except ErrorAemet as ex:
                # el servidor dice que no hay datos: es definitivo, se marca con
                # un fichero vacio para no volver a pedirlo nunca
                d = []
                aviso = "  " + str(ex)[:60]
            except ErrorRed as ex:
                # la red ha fallado: NO se sabe si hay datos. No se escribe
                # nada, para que al relanzar se vuelva a intentar.
                pendientes.append((e["idema"], f"{a:%Y-%m}", str(ex)[:60]))
                print(f"  [{n:,}/{total:,}] {e['idema']:6s} {a:%Y-%m}..{b:%Y-%m}"
                      f"  SIN RED, queda pendiente", flush=True)
                if len(pendientes) >= 25:
                    print("\n25 fallos de red seguidos: se para para no seguir a"
                          " ciegas.\nRelanza el mismo comando cuando vuelva la"
                          " conexion; lo descargado se conserva.")
                    return
                time.sleep(15)
                continue
            tmp = destino + ".parcial"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            os.replace(tmp, destino)
            vivos += len(d)
            print(f"  [{n:,}/{total:,}] {e['idema']:6s} {e['nombre'][:20]:20s} "
                  f"{a:%Y-%m}..{b:%Y-%m}  {len(d):4d} dias{aviso}", flush=True)
            time.sleep(PAUSA)
        if vivos:
            print(f"  -> {e['nombre']}: {vivos:,} dias en total", flush=True)
    if pendientes:
        print(f"\n{len(pendientes)} bloques quedaron sin descargar por fallos de red.")
        print("NO se han marcado como vacios: relanza el mismo comando y se")
        print("reintentaran solos. Los primeros:")
        for i, f, por in pendientes[:5]:
            print(f"  {i} {f}: {por}")
    else:
        print("\nSiguiente:  python 12_aemet.py --analizar")


# ---------------------------------------------------------------------------

def sen(x, y):
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 5:
        return None
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx != 0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def analizar(ventana=15):
    import glob
    import numpy as np
    import pandas as pd

    ficheros = sorted(glob.glob(os.path.join(DIR, "*.json")))
    if not ficheros:
        sys.exit("No hay nada en aemet/. Ejecuta antes --descargar")
    filas = []
    for f in ficheros:
        for r in json.load(open(f, encoding="utf-8")):
            filas.append({"idema": r.get("indicativo"), "fecha": r.get("fecha"),
                          "tmax": num(r.get("tmax")), "tmin": num(r.get("tmin")),
                          "tmed": num(r.get("tmed"))})
    d = pd.DataFrame(filas).dropna(subset=["fecha"])
    d["fecha"] = pd.to_datetime(d.fecha, errors="coerce")
    d = d.dropna(subset=["fecha", "tmax"]).drop_duplicates(["idema", "fecha"])
    d["anio"] = d.fecha.dt.year
    print(f"{len(d):,} dias, {d.idema.nunique()} estaciones, "
          f"{d.anio.min()}-{d.anio.max()}")

    inv = {e["idema"]: e for e in
           json.load(open(os.path.join(BASE, "aemet_estaciones.json"), encoding="utf-8"))}

    # AEMET no rellena huecos: si un dia no paso el control de calidad, o el
    # sensor fallo, o no llego la comunicacion, ese dia simplemente no existe.
    # Contar dias del anio entero no basta: a un anio le pueden faltar 34 dias
    # y pasar el filtro, y si esos 34 caen en julio los indices de calor salen
    # falseados sin que nada lo indique. Se exige ademas el verano completo.
    MIN_DIAS, MIN_VERANO = 330, 87          # de 365 y de 92
    anual, descartados = [], []
    for (est, a), g in d.groupby(["idema", "anio"]):
        n_verano = int(g.fecha.dt.month.isin([6, 7, 8]).sum())
        if len(g) < MIN_DIAS or n_verano < MIN_VERANO:
            descartados.append({"idema": est, "anio": a, "dias": len(g),
                                "verano": n_verano})
            continue
        v = g.tmax.values
        anual.append({"idema": est, "anio": a, "n": len(g),
                      "tx_p99": float(np.nanpercentile(v, 99)),
                      "tx_max": float(np.nanmax(v)),
                      "d_tx30": float((v >= 30).sum()),
                      "d_tx32": float((v >= 32).sum()),
                      "n_verano": n_verano,
                      "tx_verano": float(np.nanmean(
                          v[g.fecha.dt.month.isin([6, 7, 8]).values])),
                      "tmed": float(np.nanmean(g.tmed.dropna()))
                      if g.tmed.notna().any() else np.nan})
    A = pd.DataFrame(anual)
    A["nombre"] = A.idema.map(lambda i: inv.get(i, {}).get("nombre", i))
    A.to_csv(os.path.join(BASE, "aemet_series.csv"), index=False, encoding="utf-8")

    L = []

    def p(*a):
        print(*a)
        L.append(" ".join(str(x) for x in a))

    p(f"Series anuales completas: {len(A):,} anios-estacion, "
      f"{A.idema.nunique()} estaciones")
    if descartados:
        D = pd.DataFrame(descartados)
        p(f"Descartados por incompletos: {len(D):,} anios-estacion "
          f"(exigido: {MIN_DIAS} dias y {MIN_VERANO} de verano)")
        solo_verano = D[(D.dias >= MIN_DIAS) & (D.verano < MIN_VERANO)]
        if len(solo_verano):
            p(f"  de ellos, {len(solo_verano)} tenian el anio casi completo pero")
            p(f"  el verano no: son los peligrosos, los que habrian pasado un")
            p(f"  filtro que solo mirara el total. Por ejemplo:")
            for _, r in solo_verano.head(4).iterrows():
                p(f"    {r.idema} {r.anio}: {r.dias} dias del anio pero solo "
                  f"{r.verano} de verano")
        D.to_csv(os.path.join(BASE, "aemet_anios_descartados.csv"),
                 index=False, encoding="utf-8")
    p(f"\n{'estacion':26s} {'periodo':12s} {'anios':>5s}  "
      f"{'Sen tx_verano':>13s} {'Sen d_tx30':>11s}")
    largas = []
    for est, g in A.groupby("idema"):
        g = g.sort_values("anio")
        if len(g) < 30:
            continue
        largas.append(est)
        p(f"{inv.get(est, {}).get('nombre', est)[:26]:26s} "
          f"{g.anio.min()}-{g.anio.max():<7} {len(g):5d}  "
          f"{(sen(g.anio, g.tx_verano) or 0) * 10:+13.2f} "
          f"{(sen(g.anio, g.d_tx30) or 0) * 10:+11.2f}")

    if not largas:
        p("\nNinguna serie llega a 30 anios: no se puede hacer el contraste.")
    else:
        # --- el nucleo del paso: cuanto miente una ventana de 15 anios -------
        p(f"\n--- lo que exagera una ventana de {ventana} anios ---")
        p("Para cada estacion larga se calcula la pendiente sobre la serie")
        p("completa y sobre TODAS las ventanas moviles de "
          f"{ventana} anios. Si las")
        p("ventanas cortas se reparten simetricamente alrededor de la larga, la")
        p("nuestra no tiene por que estar sesgada; si estan sistematicamente por")
        p("encima, nuestro +1,31 C/decada es un artefacto de la ventana.")
        p(f"\n{'estacion':26s} {'larga':>7s} {'ventanas':>9s} "
          f"{'mediana':>8s} {'p10':>7s} {'p90':>7s} {'>larga':>7s}")
        todas_r = []
        for est in largas:
            g = A[A.idema == est].sort_values("anio")
            larga = sen(g.anio, g.tx_verano)
            if larga is None:
                continue
            cortas = []
            for i in range(len(g) - ventana + 1):
                w = g.iloc[i:i + ventana]
                s = sen(w.anio, w.tx_verano)
                if s is not None:
                    cortas.append(s)
            if len(cortas) < 5:
                continue
            c = np.array(cortas) * 10
            lg = larga * 10
            todas_r += list(c - lg)
            p(f"{inv.get(est, {}).get('nombre', est)[:26]:26s} {lg:+7.2f} "
              f"{len(c):9d} {np.median(c):+8.2f} {np.percentile(c, 10):+7.2f} "
              f"{np.percentile(c, 90):+7.2f} {(c > lg).mean():6.0%}")
        if todas_r:
            r = np.array(todas_r)
            p(f"\nDiferencia ventana corta menos serie completa, en conjunto:")
            p(f"  mediana {np.median(r):+.2f} C/decada, "
              f"rango tipico {np.percentile(r, 10):+.2f} a {np.percentile(r, 90):+.2f}")
            p(f"  el {(r > 0).mean():.0%} de las ventanas de {ventana} anios da una")
            p(f"  pendiente MAYOR que la de la serie completa.")
            p("")
            if abs(np.median(r)) < 0.15:
                p("Lectura: esa mediana es practicamente cero, asi que una ventana")
                p("de 15 anios NO esta sesgada por ser corta. Si la nuestra sale")
                p("alta no es por el metodo: es que el periodo reciente se ha")
                p("calentado de verdad mas deprisa. Lo que si dice el rango es")
                p("cuanta imprecision tiene una ventana suelta.")
            elif np.median(r) > 0:
                p("Lectura: las ventanas cortas salen sistematicamente por encima,")
                p(f"asi que hay que descontar del orden de {np.median(r):+.2f} C/decada")
                p("a cualquier tendencia estimada sobre 15 anios.")
            else:
                p("Lectura: las ventanas cortas salen por DEBAJO de la serie larga,")
                p("asi que una tendencia de 15 anios, si acaso, se queda corta.")

        # --- la comparacion que de verdad zanja el asunto -------------------
        # Calcular la MISMA ventana que usamos nosotros, 2011-2025, en las
        # estaciones. Si coincide con lo que dio ERA5-Land, nuestro numero era
        # correcto y el problema no era el dato sino su interpretacion.
        w = []
        for est, g in A.groupby("idema"):
            v = g[(g.anio >= 2011) & (g.anio <= 2025)].sort_values("anio")
            if len(v) >= 13:
                s15 = sen(v.anio, v.tx_verano)
                if s15 is not None and np.isfinite(s15):
                    w.append(s15 * 10)
        if len(w) >= 5:
            w = np.array(w)
            p(f"\n--- la misma ventana que usamos nosotros: 2011-2025 ---")
            p(f"  {len(w)} estaciones con la ventana completa")
            p(f"  mediana {np.median(w):+.2f} C/decada  "
              f"(p10 {np.percentile(w, 10):+.2f}, p90 {np.percentile(w, 90):+.2f})")
            p("  Compara con lo que dio ERA5-Land para ese mismo periodo. Si")
            p("  coinciden, el dato era bueno y lo que fallaba era llamarlo")
            p("  'ritmo de calentamiento' en vez de 'lo que hizo ese periodo'.")

    with open(os.path.join(BASE, "resumen_aemet.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\nDatos: AEMET (opendata.aemet.es)\n")
    print("\nEscritos aemet_series.csv y resumen_aemet.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--descargar", action="store_true")
    ap.add_argument("--analizar", action="store_true")
    ap.add_argument("--desde", type=int, default=None,
                    help="anio inicial. Por defecto, el inicio real de cada\nestacion segun el sondeo de --explorar")
    ap.add_argument("--hasta", type=int, default=date.today().year - 1)
    ap.add_argument("--meses", type=int, default=MESES_POR_PETICION,
                    help="meses por peticion (el servidor admite 6)")
    ap.add_argument("--estaciones", default=None,
                    help="lista de idemas separados por comas; por defecto, todas")
    ap.add_argument("--max-estaciones", type=int, default=20,
                    help="cuantas estaciones sondear en --explorar")
    ap.add_argument("--ventana", type=int, default=15,
                    help="longitud de la ventana corta con la que comparar")
    args = ap.parse_args()

    if args.analizar:
        analizar(args.ventana)
        return
    k = clave()
    cad = caducidad(k)
    if cad:
        quedan = (cad - date.today()).days
        print(f"clave valida hasta {cad} ({quedan} dias)")
        if quedan < 15:
            print("  AVISO: caduca pronto; pide otra en opendata.aemet.es")
    if args.explorar:
        explorar(k, args.max_estaciones)
    elif args.descargar:
        descargar(k, args.desde, args.hasta, args.meses, args.estaciones)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
