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

def extremos(col, n=4, arriba=True, separacion=12.0):
    """Los n extremos, obligando a que esten en sitios DISTINTOS.

    Sin la separacion salian cuatro puntos del mismo kilometro cuadrado: tres de
    los cuatro mas calurosos eran Larouco, y en el mapa se tapaban unos a otros.
    """
    z = al[al.gal].sort_values(col, ascending=not arriba)
    sel = []
    for _, r in z.iterrows():
        if all(np.hypot(r.lat - q.lat, (r.lon - q.lon) * k) * 111 > separacion for q in sel):
            sel.append(r)
        if len(sel) == n:
            break
    return [{"lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
             "alt": round(float(r.altitud)), "tx": round(float(r.tx), 1),
             "d32": int(r.wrf_n_ge32), "cerca": titulo(r.cerca), "km": float(r.km)}
            for r in sel]
O["extremos"] = {"frescos": extremos("tx", 15, False), "calidos": extremos("tx", 15, True)}
# Donde esta la frontera: los cuartiles del propio territorio. Sin esto, decir
# "de los mas frescos" no significa nada -- no se sabe respecto a que.
_v = al.loc[al.gal & (al.altitud < 400), "tx"].dropna().values
O["reparto"] = {"n": int(_v.size),
                "p": {str(q): round(float(np.percentile(_v, q)), 1)
                      for q in (1, 5, 10, 25, 50, 75, 90, 95, 99)},
                "hist": np.histogram(_v, bins=28, range=(26, 40))[0].tolist(),
                "hlo": 26.0, "hhi": 40.0}
O["mascara"] = {"dentro": int(al.gal.sum()), "total": int(len(al))}
# Los 20 peores, para poder pintarlos en el mapa junto a los 20 mejores. Misma
# regla que el ranking: solo Galicia y por debajo de 400 m, para comparar peras
# con peras (un punto a 1.500 m es fresco por otra razon).
_bajo = al[al.gal & (al.altitud < 400)].dropna(subset=["tx"])
O["peores"] = [{"puesto": i + 1, "lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
                "altitud": round(float(r.altitud)), "cerca": titulo(r.cerca),
                "km": float(r.km), "tx_p99_1km": round(float(r.tx_p99_1km), 2),
                "hx_p99_1km": round(float(r.hx_p99_1km), 2),
                "wrf_n_ge32": int(r.wrf_n_ge32)}
               for i, (_, r) in enumerate(_bajo.nlargest(20, "tx").iterrows())]
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
