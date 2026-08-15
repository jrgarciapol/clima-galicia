import os
import json, numpy as np, pandas as pd
R = os.environ.get("GAL_DATOS") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
O = {}

# ---- puntos del ranking, con nombre por la estacion mas proxima -------------
r = pd.read_csv(f"{R}/ranking_con_proyeccion.csv")
est = pd.read_csv(f"{R}/estaciones_lista.csv")
k = np.cos(np.radians(43.0))
dist = np.hypot(r.lat.values[:,None]-est.lat.values[None,:],
                (r.lon.values[:,None]-est.lon.values[None,:])*k)*111
i = dist.argmin(1)
r["cerca"] = est.concello.values[i]
r["km"] = dist[np.arange(len(r)), i].round(1)
r = r.sort_values("tx_p99_1km").reset_index(drop=True)
r["puesto"] = r.index + 1
cols = ["puesto","lat","lon","altitud","cerca","km","tx_p99_1km","hx_p99_1km",
        "tx_verano_1km","wrf_n_ge32","d_ssp126","d_ssp245","d_ssp370","d_ssp585"]
cols = cols + []
O["puntos"] = json.loads(r[cols].round(3).to_json(orient="records"))
print(f"puntos: {len(r)}")

# ---- los extremos, para los mapas pequenios de contexto --------------------
al = pd.read_csv(f"{R}/alta_resolucion.csv.gz")
al = al[al.tierra == 1].copy()
al["tx"] = al.tx_p99_1km + 2.74
dist = np.hypot(al.lat.values[:, None] - est.lat.values[None, :],
                (al.lon.values[:, None] - est.lon.values[None, :]) * k) * 111
ii = dist.argmin(1)
al["cerca"] = est.concello.values[ii]
al["km"] = dist[np.arange(len(al)), ii].round(1)
# El dominio del modelo de 1 km es un rectangulo: incluye franjas de Portugal,
# Asturias, Leon y Zamora. Para una lista titulada "los extremos DE GALICIA" hay
# que quitarlas, o el segundo sitio mas fresco acaba estando en Caminha.
# Como no hay contorno administrativo a mano, se usa la envolvente convexa de la
# red de MeteoGalicia -- que solo tiene estaciones en Galicia -- dilatada 0,08
# grados. Deja fuera el 100 % de Portugal y de Asturias; en el limite con Leon,
# por Valdeorras, la separacion es borrosa y algo se cuela.
from scipy.spatial import ConvexHull
from matplotlib.path import Path as _Path
_h = ConvexHull(est[["lon", "lat"]].values)
GALICIA = _Path(est[["lon", "lat"]].values[_h.vertices])
al["gal"] = GALICIA.contains_points(al[["lon", "lat"]].values, radius=0.08)
print(f"  mascara de Galicia: {int(al.gal.sum())} de {len(al)} puntos ({al.gal.mean():.0%})")

def titulo(n):
    menores = {"de", "do", "da", "dos", "das", "e", "a", "o"}
    ps = str(n).lower().split()
    return " ".join(w if (i and w in menores) else w.capitalize() for i, w in enumerate(ps))

# EL INDICE. Estaba descrito en el informe y no se usaba en ninguna parte: las
# listas se ordenaban por temperatura a secas. Se calcula aqui una vez, sobre
# Galicia y por debajo de 400 m, y de el salen todas las clasificaciones.
_base = al[al.gal & (al.altitud < 400)].dropna(subset=["tx_p99_1km", "hx_p99_1km"])
_zt = (_base.tx_p99_1km - _base.tx_p99_1km.mean()) / _base.tx_p99_1km.std()
_zh = (_base.hx_p99_1km - _base.hx_p99_1km.mean()) / _base.hx_p99_1km.std()
_nota = 0.6 * _zt + 0.4 * _zh
# A escala 0-100 legible: 100 el mejor punto de Galicia, 0 el peor. La nota
# cruda es un compuesto de puntuaciones tipicas y no significa nada para nadie.
_ind = 100 * (_nota.max() - _nota) / (_nota.max() - _nota.min())
al["indice"] = np.nan
al.loc[_base.index, "indice"] = _ind
print(f"  indice 60/40: {len(_base)} puntos, de {_ind.min():.1f} a {_ind.max():.1f}")


def extremos(col, n=4, arriba=True, separacion=12.0):
    """Los n extremos, obligando a que esten en sitios DISTINTOS.

    Sin la separacion salian cuatro puntos del mismo kilometro cuadrado: tres de
    los cuatro mas calurosos eran Larouco, y en el mapa se tapaban unos a otros.
    """
    z = al[al.gal & al.indice.notna()].sort_values(col, ascending=not arriba)
    sel = []
    for _, r in z.iterrows():
        if all(np.hypot(r.lat - q.lat, (r.lon - q.lon) * k) * 111 > separacion for q in sel):
            sel.append(r)
        if len(sel) == n:
            break
    return [{"lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
             "alt": round(float(r.altitud)), "tx": round(float(r.tx), 1),
             "hx": round(float(r.hx_p99_1km), 1), "ind": round(float(r.indice), 1),
             "d32": int(r.wrf_n_ge32), "cerca": titulo(r.cerca), "km": float(r.km)}
            for r in sel]
O["extremos"] = {"frescos": extremos("indice", 15, True),
                 "calidos": extremos("indice", 15, False)}
# Donde esta la frontera: los cuartiles del propio territorio. Sin esto, decir
# "de los mas frescos" no significa nada -- no se sabe respecto a que.
_v = al.loc[al.gal & (al.altitud < 400), "tx"].dropna().values
O["compresion"] = {}
for _et, _f in [("ourense", (al.lat.between(42.31, 42.39)) & (al.lon.between(-7.92, -7.82))),
                ("coruna_interior", (al.lat.between(43.0, 43.25)) & (al.lon.between(-8.6, -8.2))),
                ("costa_morte", (al.lat.between(42.85, 43.25)) & (al.lon < -9.05))]:
    _z = al[_f & al.gal]
    O["compresion"][_et] = {"n": int(len(_z)), "tx": round(float(_z.tx.mean()), 1),
                            "hx": round(float(_z.hx_p99_1km.mean()), 1)}
O["reparto"] = {"n": int(_v.size),
                "p": {str(q): round(float(np.percentile(_v, q)), 1)
                      for q in (1, 5, 10, 25, 50, 75, 90, 95, 99)},
                "hist": np.histogram(_v, bins=28, range=(26, 40))[0].tolist(),
                "hlo": 26.0, "hhi": 40.0}
O["mascara"] = {"dentro": int(al.gal.sum()), "total": int(len(al))}
# Los 20 peores, para poder pintarlos en el mapa junto a los 20 mejores. Misma
# regla que el ranking: solo Galicia y por debajo de 400 m, para comparar peras
# con peras (un punto a 1.500 m es fresco por otra razon).
_bajo = al[al.indice.notna()]
O["peores"] = [{"puesto": i + 1, "lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
                "altitud": round(float(r.altitud)), "cerca": titulo(r.cerca),
                "km": float(r.km), "tx_p99_1km": round(float(r.tx_p99_1km), 2),
                "hx_p99_1km": round(float(r.hx_p99_1km), 2), "indice": round(float(r.indice), 1),
                "wrf_n_ge32": int(r.wrf_n_ge32)}
               for i, (_, r) in enumerate(_bajo.nsmallest(20, "indice").iterrows())]
print(f"peores: {O['peores'][0]['cerca']} ({O['peores'][0]['tx_p99_1km'] + 2.74:.1f} C)")
print(f"extremos: {O['extremos']['frescos'][0]['cerca']} ... {O['extremos']['calidos'][0]['cerca']}")

# ---- concellos con coordenadas: para decir donde esta el raton en el mapa ---
O["lugares"] = [{"n": titulo(r.concello), "la": round(float(r.lat), 3),
                 "lo": round(float(r.lon), 3)}
                for _, r in est.drop_duplicates("concello").iterrows()]
print(f"lugares: {len(O['lugares'])}")

# ---- estaciones de MeteoGalicia --------------------------------------------
ie = pd.read_csv(f"{R}/indices_estaciones.csv")
te = pd.read_csv(f"{R}/tendencias_estaciones.csv")
ie = ie.merge(te[["estacion","d_tx30_sen_dec","tx_p99_sen_dec","tx_verano_sen_dec"]],
              left_on="id", right_on="estacion", how="left")
c = ["id","concello","provincia","lat","lon","alt","n_anios","d_tx30","d_tx32",
     "tx_p99","tx_max","tx_verano","noches_trop","hx_p99","d_hx35","hr_verano",
     "d_tx30_sen_dec","tx_p99_sen_dec"]
O["estaciones"] = json.loads(ie[c].round(3).to_json(orient="records"))
print(f"estaciones: {len(ie)}")

# ---- AEMET: comparacion justa 1980-2025 y ventana 2011-2025 ----------------
d = pd.read_csv(f"{R}/aemet_series.csv")
def sen(x,y):
    x=np.asarray(x,float); y=np.asarray(y,float)
    m=np.isfinite(x)&np.isfinite(y); x,y=x[m],y[m]
    if len(x)<8: return np.nan
    return float(np.median([(y[j]-y[i])/(x[j]-x[i]) for i in range(len(x))
                            for j in range(i+1,len(x)) if x[j]!=x[i]])*10)
largas, ventana = [], []
for kk,g in d.groupby("idema"):
    nom = str(g.nombre.iloc[0])
    gl = g[(g.anio>=1980)&(g.anio<=2025)]
    if len(gl)>=40:
        largas.append({"nombre":nom,"ini":int(gl.anio.min()),"fin":int(gl.anio.max()),
            "n":len(gl),"tx_verano":round(sen(gl.anio,gl.tx_verano),3),
            "tx_p99":round(sen(gl.anio,gl.tx_p99),3),"d_tx30":round(sen(gl.anio,gl.d_tx30),3),
            "serie":[[int(a),round(float(v),2)] for a,v in zip(gl.anio,gl.tx_verano) if np.isfinite(v)]})
    gv = g[(g.anio>=2011)&(g.anio<=2025)]
    if len(gv)>=13:
        t = sen(gv.anio,gv.tx_verano)
        if np.isfinite(t): ventana.append({"nombre":nom,"tend":round(t,3)})
O["aemet_largas"] = sorted(largas, key=lambda x:x["d_tx30"])
O["aemet_ventana"] = sorted(ventana, key=lambda x:-x["tend"])
print(f"aemet: {len(largas)} largas, {len(ventana)} en ventana")

# ---- las 153 estaciones, con su proyeccion a 2041-2070 ---------------------
# El delta se toma de la celda de AdapteCCa mas parecida en climatologia, que es
# como se hace en la tabla de los cuatro sitios. No es un calculo por celda
# geografica: es una correspondencia por nivel termico, y conviene decirlo.
_pr = pd.read_csv(f"{R}/proyecciones_galicia.csv.gz")
_jja = _pr[(_pr.tipo == "anom") & (_pr.filtro == "JJA") & (_pr.variable == "tasmaxp99")
           & (_pr.periodo == "medium_future") & (_pr.escenario == "ssp245")]
_ab = _pr[(_pr.tipo == "abs") & (_pr.filtro == "JJA") & (_pr.variable == "tasmaxp99")
          & (_pr.periodo == "reference") & (_pr.escenario == "ssp245")]
_par = pd.concat({"c": _ab.set_index(["lat", "lon"]).valor,
                  "d": _jja.set_index(["lat", "lon"]).valor}, axis=1).dropna()
_cl, _de = _par.c.values, _par.d.values
_fut = []
for _, r in ie.iterrows():
    if not np.isfinite(r.tx_p99):
        continue
    _delta = float(_de[np.abs(_cl - r.tx_p99).argmin()])
    _fut.append({"id": int(r.id), "n": titulo(r.concello), "prov": str(r.provincia),
                 "lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
                 "alt": round(float(r.alt)), "hoy": round(float(r.tx_p99), 1),
                 "fut": round(float(r.tx_p99) + _delta, 1), "d": round(_delta, 2),
                 "hx": round(float(r.hx_p99), 1) if np.isfinite(r.hx_p99) else None,
                 "d30": round(float(r.d_tx30), 1) if np.isfinite(r.d_tx30) else None})
O["estaciones_futuro"] = sorted(_fut, key=lambda x: x["hoy"])
print(f"estaciones con proyeccion: {len(_fut)}  "
      f"delta de {min(x['d'] for x in _fut):+.2f} a {max(x['d'] for x in _fut):+.2f}")

# ---- paso 15: los seis factores medidos y el confort proyectado ------------
_rc = f"{R}/confort_estaciones.csv"
if os.path.exists(_rc):
    cf = pd.read_csv(_rc)
    _h = cf[cf.periodo == "hoy"].copy()
    # Se limita a 400 m, como el IVL de la malla: por encima "fresco" significa
    # otra cosa. Sin este corte, las cinco estaciones mas llevaderas de Galicia
    # son cumbres de 1.200-1.700 m y la lista deja de responder a la pregunta.
    _b = _h[_h.alt < 400].copy()
    _z = lambda x: (x - x.mean()) / x.std()
    _nota = 0.6 * _z(_b.tx_p99) + 0.4 * _z(_b.hx_p99)
    _b["ivl"] = 100 * (_nota.max() - _nota) / (_nota.max() - _nota.min())
    SEIS = ["tx_p99", "hx_p99", "d_hx35", "cdd", "ola_max", "noches_trop"]
    _seis = sum(_z(_b[c]) for c in SEIS) / 6
    _b["ivl6"] = 100 * (_seis.max() - _seis) / (_seis.max() - _seis.min())
    _b = _b.sort_values("ivl", ascending=False)
    O["confort"] = {
        "n": int(len(_b)), "n_total": int(len(_h)),
        "est": json.loads(_b[["id", "concello", "provincia", "lat", "lon", "alt", "n_anios",
                              "ivl", "ivl6"] + SEIS].round(2).to_json(orient="records")),
        # cuanto cambia el orden al meter los cuatro factores extra
        "rho_ivl6": round(float(np.corrcoef(_b.ivl.rank(), _b.ivl6.rank())[0, 1]), 3),
        "comunes10": int(len(set(_b.nlargest(10, "ivl").id) & set(_b.nlargest(10, "ivl6").id))),
        "corr": {c: {c2: round(float(np.corrcoef(_b[c], _b[c2])[0, 1]), 2)
                     for c2 in SEIS} for c in SEIS},
    }
    # --- el confort proyectado, las dos hipotesis ---
    _fut = {}
    for hip in ("rocio_fijo", "hr_fija"):
        f = cf[(cf.periodo == "medium_future") & (cf.escenario == "ssp245")
               & (cf.hipotesis == hip)].set_index("id")
        j = f.join(_b.set_index("id")[["ivl", "alt", "concello"]], how="inner", rsuffix="_h")
        _fut[hip] = json.loads(j.reset_index()[["id", "concello", "hx_p99", "d_hx35",
                                                "tx_p99", "cdd", "noches_trop", "d_tx"]]
                               .round(2).to_json(orient="records"))
    O["confort"]["futuro"] = _fut
    # los que mas y menos suben de temperatura
    _dt = cf[(cf.periodo == "medium_future") & (cf.escenario == "ssp245")
             & (cf.hipotesis == "rocio_fijo")]
    _dt = _dt[_dt.id.isin(_b.id)].sort_values("d_tx")
    O["confort"]["suben"] = {
        "menos": json.loads(_dt.head(6)[["concello", "provincia", "alt", "d_tx"]]
                            .round(2).to_json(orient="records")),
        "mas": json.loads(_dt.tail(6).iloc[::-1][["concello", "provincia", "alt", "d_tx"]]
                          .round(2).to_json(orient="records"))}
    print(f"confort: {len(_b)} estaciones bajo 400 m de {len(_h)}; "
          f"rho IVL vs seis factores {O['confort']['rho_ivl6']}")
else:
    print("AVISO: falta confort_estaciones.csv (paso 15)")

# ---- ROCIO: clima vs tendencia ---------------------------------------------
ro = pd.read_csv(f"{R}/rocio_tendencias.csv")
O["rocio"] = [[round(x,2),round(y,3)] for x,y in
              zip(ro.tx_verano_clim, ro.tx_verano_tend) if np.isfinite(x) and np.isfinite(y)]
print(f"rocio: {len(O['rocio'])} celdas")

# ---- proyecciones: tabla por variable/escenario/periodo --------------------
p = pd.read_csv(f"{R}/proyecciones_galicia.csv.gz")
jja = p[(p.tipo=="anom")&(p.filtro=="JJA")]
tabla={}
for v in sorted(jja.variable.unique()):
    tabla[v]={}
    for e in sorted(jja.escenario.unique()):
        tabla[v][e]={}
        for per in ["near_future","medium_future","far_future"]:
            g=jja[(jja.variable==v)&(jja.escenario==e)&(jja.periodo==per)]
            if len(g): tabla[v][e][per]=[round(g.valor.median(),2),
                                         round(g.p10.median(),2), round(g.p90.median(),2)]
O["escenarios"]=tabla

# brecha en las proyecciones: clim de referencia vs anomalia 2041-2070
ab = p[(p.tipo=="abs")&(p.filtro=="JJA")&(p.variable=="tasmaxp99")&(p.periodo=="reference")]
O["brecha_proy"]={}
for e in ["ssp245","ssp585"]:
    b = ab[ab.escenario==e].set_index(["lat","lon"]).valor
    aa = jja[(jja.variable=="tasmaxp99")&(jja.escenario==e)&(jja.periodo=="medium_future")]\
            .set_index(["lat","lon"]).valor
    j = pd.concat({"c":b,"d":aa},axis=1).dropna()
    O["brecha_proy"][e]=[[round(x,2),round(y,3)] for x,y in zip(j.c,j.d)]
print(f"brecha_proy: {[len(v) for v in O['brecha_proy'].values()]}")

# brecha en AEMET: climatologia vs tendencia por estacion (periodo comun)
bb=[]
for kk,g in d.groupby("idema"):
    g2=g[(g.anio>=1980)&(g.anio<=2025)]
    if len(g2)>=25:
        t=sen(g2.anio,g2.d_tx30)
        if np.isfinite(t): bb.append([round(float(g2.tx_verano.mean()),2),round(t,3),
                                      str(g.nombre.iloc[0]), round(float(g2.d_tx30.mean()),1)])
O["brecha_aemet"]=bb
print(f"brecha_aemet: {len(bb)}")
json.dump(O, open("datos_informe.json","w"), separators=(",",":"))
import os; print("datos_informe.json", round(os.path.getsize("datos_informe.json")/1e6,2), "MB")
