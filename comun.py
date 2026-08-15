"""Utilidades compartidas: indices termicos y de extremos de calor.

Todas las funciones trabajan con temperaturas en grados Celsius.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Humedad
# ---------------------------------------------------------------------------


def presion_vapor(td_c):
    """Presion de vapor (hPa) a partir del punto de rocio, formula de Magnus."""
    td = np.asarray(td_c, dtype=float)
    return 6.112 * np.exp((17.67 * td) / (td + 243.5))


def humedad_relativa(t_c, td_c):
    """Humedad relativa (%) a partir de temperatura y punto de rocio."""
    return np.clip(100.0 * presion_vapor(td_c) / presion_vapor(t_c), 0, 100)


def rh_a_porcentaje(rh, unidades=None):
    """Normaliza humedad relativa a % (0-100), venga como venga.

    El WRF de MeteoGalicia declara `rh` con units="1", es decir fraccion 0-1, no
    porcentaje. Si eso se cuela sin convertir, `clip(0.62, 1, 100)` da 1 %: el
    humidex sale igual que la temperatura seca y toda la componente de bochorno
    desaparece sin ningun aviso. Es un error silencioso y grave, asi que se
    decide mirando los datos, que es mas fiable que fiarse del atributo.
    """
    a = np.asarray(rh, dtype=float)
    finitos = a[np.isfinite(a)]
    if finitos.size:
        mx = np.nanmax(finitos)
        if mx <= 1.5:                      # claramente fraccion
            return np.clip(a * 100.0, 0, 100)
        if mx > 1.5:                       # claramente porcentaje
            return np.clip(a, 0, 100)
    if str(unidades).strip() in ("1", "", "-", "fraction", "None"):
        return np.clip(a * 100.0, 0, 100)
    return np.clip(a, 0, 100)


def humidex(t_c, td_c):
    """Humidex canadiense. Combina temperatura y humedad en una sensacion termica.

    Umbrales de referencia (Environment Canada):
      < 30      sin molestia
      30 - 39   molestia notable
      40 - 45   fuerte malestar, evitar esfuerzo
      > 45      peligro, riesgo de golpe de calor
    """
    t = np.asarray(t_c, dtype=float)
    e = presion_vapor(td_c)
    hx = t + 0.5555 * (e - 10.0)
    # Con aire muy seco la correccion es negativa y el humidex caeria por debajo
    # de la temperatura real. Por convenio se limita a la temperatura seca: el
    # indice mide el agravamiento por humedad, nunca un alivio.
    return np.maximum(hx, t)


def bulbo_humedo(t_c, rh):
    """Temperatura de bulbo humedo (Stull 2011), en grados Celsius.

    Es la temperatura a la que se enfria el aire al saturarlo por evaporacion,
    y por tanto **el limite fisico del enfriamiento del cuerpo humano**: por
    encima de unos 35 C de bulbo humedo, sudar deja de servir de nada por mucha
    sombra, agua o ventilador que haya.

    En un clima humedo como el gallego dice cosas que la temperatura seca no
    dice: 30 C con el aire saturado son mas peligrosos que 36 C secos.

    La aproximacion de Stull es valida para humedades entre el 5 % y el 99 % y
    temperaturas de -20 a 50 C, con un error tipico por debajo de 1 C. Fuera de
    ese rango degrada, asi que la humedad se acota.
    """
    t = np.asarray(t_c, dtype=float)
    r = np.clip(np.asarray(rh, dtype=float), 5.0, 99.0)
    return (t * np.arctan(0.151977 * np.sqrt(r + 8.313659))
            + np.arctan(t + r)
            - np.arctan(r - 1.676331)
            + 0.00391838 * r ** 1.5 * np.arctan(0.023101 * r)
            - 4.686035)


def temp_aparente(t_c, td_c, viento_ms):
    """Temperatura aparente de Steadman (version del Bureau of Meteorology).

        AT = T + 0.33*e - 0.70*ws - 4.00

    con `e` la presion de vapor en hPa y `ws` el viento a 10 m en m/s.

    A diferencia del humidex, esta si puede quedar por debajo de la temperatura
    real, porque incorpora el efecto refrescante del viento. En Galicia eso
    importa mucho: es la razon por la que la costa norte con brisa del nordeste
    se lleva bien un dia que en el interior es insoportable, aunque el
    termometro marque algo parecido.
    """
    t = np.asarray(t_c, dtype=float)
    e = presion_vapor(td_c)
    ws = np.clip(np.asarray(viento_ms, dtype=float), 0, None)
    return t + 0.33 * e - 0.70 * ws - 4.00


def heat_index(t_c, rh):
    """Heat Index de la NOAA (Rothfusz), en grados Celsius.

    Solo es valido para T >= 26.7 C; por debajo devuelve la temperatura seca.
    """
    t = np.asarray(t_c, dtype=float)
    r = np.asarray(rh, dtype=float)
    tf = t * 9.0 / 5.0 + 32.0
    hi = (
        -42.379
        + 2.04901523 * tf
        + 10.14333127 * r
        - 0.22475541 * tf * r
        - 6.83783e-3 * tf**2
        - 5.481717e-2 * r**2
        + 1.22874e-3 * tf**2 * r
        + 8.5282e-4 * tf * r**2
        - 1.99e-6 * tf**2 * r**2
    )
    hi_c = (hi - 32.0) * 5.0 / 9.0
    return np.where(t >= 26.7, hi_c, t)


# ---------------------------------------------------------------------------
# Indices de extremos
# ---------------------------------------------------------------------------


def percentil_calendario(fechas, valores, ventana=15, q=95):
    """Percentil movil del calendario (metodo ETCCDI).

    Para cada dia del anio, toma todos los valores del periodo dentro de una
    ventana de +/- `ventana` dias y calcula el percentil `q`. Es la base de la
    definicion de ola de calor relativa al clima local.

    Devuelve una serie alineada con `fechas`.
    """
    fechas = pd.DatetimeIndex(fechas)
    valores = np.asarray(valores, dtype=float)
    doy = fechas.dayofyear.values
    umbral_doy = np.full(367, np.nan)
    for d in range(1, 367):
        dif = np.abs(doy - d)
        dif = np.minimum(dif, 365 - dif)
        sel = dif <= ventana
        if sel.sum() >= 30:
            umbral_doy[d] = np.nanpercentile(valores[sel], q)
    return pd.Series(umbral_doy[doy], index=fechas)


def rachas(mascara, min_len=3):
    """Dada una mascara booleana, devuelve (n_episodios, n_dias_en_episodios).

    Solo cuentan las rachas de al menos `min_len` dias consecutivos.
    """
    m = np.asarray(mascara, dtype=bool)
    if m.size == 0:
        return 0, 0
    d = np.diff(np.concatenate(([0], m.view(np.int8), [0])))
    ini = np.flatnonzero(d == 1)
    fin = np.flatnonzero(d == -1)
    largos = fin - ini
    largos = largos[largos >= min_len]
    return int(largos.size), int(largos.sum())


def indices_punto(df, anio_ini=None, anio_fin=None):
    """Calcula todos los indices para una serie diaria de un punto.

    `df` debe tener indice de fechas y columnas: tmax, tmin, tmean, td (opcional).
    Devuelve un dict de escalares.
    """
    df = df.sort_index()
    if anio_ini is not None:
        df = df[df.index.year >= anio_ini]
    if anio_fin is not None:
        df = df[df.index.year <= anio_fin]
    if len(df) < 365:
        return {}

    n_anios = df.index.year.nunique()
    out = {"n_anios": n_anios, "n_dias": len(df)}

    tmax, tmin = df["tmax"].values, df["tmin"].values

    # --- calor extremo, umbrales absolutos ---------------------------------
    for u in (28, 30, 32, 35, 38):
        out[f"d_tx{u}"] = float(np.nansum(tmax >= u)) / n_anios
    out["tx_p99"] = float(np.nanpercentile(tmax, 99))
    out["tx_p999"] = float(np.nanpercentile(tmax, 99.9))
    out["tx_max"] = float(np.nanmax(tmax))
    out["tx_verano"] = float(np.nanmean(tmax[df.index.month.isin([6, 7, 8])]))

    # --- noches calidas ----------------------------------------------------
    out["noches_trop"] = float(np.nansum(tmin >= 20)) / n_anios
    out["noches_18"] = float(np.nansum(tmin >= 18)) / n_anios
    out["tn_p99"] = float(np.nanpercentile(tmin, 99))

    # --- olas de calor (relativas al clima local) --------------------------
    umbral = percentil_calendario(df.index, tmax, ventana=15, q=95).values
    ola = tmax > umbral
    n_ep, n_dias = rachas(ola, min_len=3)
    out["olas_n"] = n_ep / n_anios
    out["olas_dias"] = n_dias / n_anios
    n_ep5, n_dias5 = rachas(ola, min_len=5)
    out["olas_largas_n"] = n_ep5 / n_anios

    # --- confort real: indices ya calculados hora a hora --------------------
    # Si venimos de datos horarios, `at_max` y `hx_max` ya son el maximo diario
    # del indice calculado en cada hora, que es lo correcto. Si solo tenemos
    # datos diarios, mas abajo se aproximan desde tmax y el rocio medio.
    if "at_max" in df.columns and df["at_max"].notna().any():
        at = df["at_max"].values
        out["at_p99"] = float(np.nanpercentile(at, 99))
        out["at_max"] = float(np.nanmax(at))
        for u in (27, 30, 32, 35):
            out[f"d_at{u}"] = float(np.nansum(at >= u)) / n_anios
        out["at_verano"] = float(np.nanmean(at[df.index.month.isin([6, 7, 8])]))
    if "hx_max" in df.columns and df["hx_max"].notna().any():
        hx = df["hx_max"].values
        out["hx_p99"] = float(np.nanpercentile(hx, 99))
        out["hx_max"] = float(np.nanmax(hx))
        for u in (30, 35, 40):
            out[f"d_hx{u}"] = float(np.nansum(hx >= u)) / n_anios
    if "tmin_noche" in df.columns and df["tmin_noche"].notna().any():
        tn = df["tmin_noche"].values
        out["noches_trop"] = float(np.nansum(tn >= 20)) / n_anios
        out["noches_18"] = float(np.nansum(tn >= 18)) / n_anios
    if "wb_max" in df.columns and df["wb_max"].notna().any():
        wb = df["wb_max"].values
        out["wb_p99"] = float(np.nanpercentile(wb, 99))
        out["wb_max"] = float(np.nanmax(wb))
        # 26 C de bulbo humedo ya es esfuerzo serio; 28 es el umbral que la
        # literatura de salud laboral usa para suspender trabajo al aire libre
        for u in (24, 26, 28):
            out[f"d_wb{u}"] = float(np.nansum(wb >= u)) / n_anios

    if "viento" in df.columns and df["viento"].notna().any():
        v = df["viento"].values
        out["viento_medio"] = float(np.nanmean(v))
        out["viento_verano"] = float(np.nanmean(v[df.index.month.isin([6, 7, 8])]))
        # el viento cuando mas falta hace: media en los dias de calor extremo
        calidos = tmax >= np.nanpercentile(tmax, 99)
        if calidos.sum() >= 5:
            out["viento_dias_calidos"] = float(np.nanmean(v[calidos]))

    # --- confort real: derivados del punto de rocio -------------------------
    if "td" in df.columns and df["td"].notna().any():
        td = df["td"].values
        rh = humedad_relativa(tmax, td)
        hi = heat_index(tmax, rh)
        out["hi_p99"] = float(np.nanpercentile(hi, 99))
        out["d_hi32"] = float(np.nansum(hi >= 32)) / n_anios
        out["hr_verano"] = float(np.nanmean(rh[df.index.month.isin([6, 7, 8])]))
        # bochorno nocturno: noche calida y aire practicamente saturado
        tn_ref = df["tmin_noche"].values if "tmin_noche" in df else tmin
        out["noches_bochorno"] = float(
            np.nansum((tn_ref >= 18)
                      & (humedad_relativa(tn_ref, np.minimum(td, tn_ref)) >= 90))
        ) / n_anios
        # solo si no llego ya calculado hora a hora, que es mas fiable
        if "hx_p99" not in out:
            hx = humidex(tmax, td)
            out["hx_p99"] = float(np.nanpercentile(hx, 99))
            out["hx_max"] = float(np.nanmax(hx))
            for u in (30, 35, 40):
                out[f"d_hx{u}"] = float(np.nansum(hx >= u)) / n_anios

    # --- suavidad general ---------------------------------------------------
    out["tmean"] = float(np.nanmean(df["tmean"].values if "tmean" in df else (tmax + tmin) / 2))
    out["amplitud"] = float(np.nanmean(tmax - tmin))
    out["d_helada"] = float(np.nansum(tmin <= 0)) / n_anios
    out["tn_p01"] = float(np.nanpercentile(tmin, 1))
    out["rango_anual"] = float(
        df.groupby(df.index.month)["tmax"].mean().max()
        - df.groupby(df.index.month)["tmin"].mean().min()
    )
    return out


def tendencia(df, metrica_fn):
    """Pendiente por decada de una metrica anual, mas el salto reciente.

    `metrica_fn` recibe el sub-DataFrame de un anio y devuelve un escalar.
    """
    anios, vals = [], []
    for a, sub in df.groupby(df.index.year):
        if len(sub) < 300:
            continue
        anios.append(a)
        vals.append(metrica_fn(sub))
    anios, vals = np.array(anios, float), np.array(vals, float)
    ok = np.isfinite(vals)
    if ok.sum() < 10:
        return {}
    pend = np.polyfit(anios[ok], vals[ok], 1)[0] * 10.0
    reciente = anios >= 2021
    previo = (anios >= 1996) & (anios <= 2020)
    salto = np.nan
    if reciente.sum() >= 3 and previo.sum() >= 10:
        salto = float(np.nanmean(vals[reciente]) - np.nanmean(vals[previo]))
    return {"pendiente_decada": float(pend), "salto_2021_2025": salto}
