# Dónde situar la vivienda en Galicia

Análisis de calor extremo y confort térmico con datos abiertos, para decidir dónde
situar una vivienda habitual con temperaturas suaves y evitando los episodios
extremos.

Documentación completa: qué se mide, de dónde sale, cómo se ejecuta, qué significa
cada variable y en qué punto está el trabajo.

---

## Índice

1. [Estado actual](#1-estado-actual)
2. [La pregunta y cómo se traduce en números](#2-la-pregunta-y-cómo-se-traduce-en-números)
3. [Glosario: qué significa cada índice](#3-glosario-qué-significa-cada-índice)
4. [Las fuentes de datos y el papel de cada una](#4-las-fuentes-de-datos-y-el-papel-de-cada-una)
5. [Puesta en marcha](#5-puesta-en-marcha)
6. [Ejecución paso a paso](#6-ejecución-paso-a-paso)
7. [Métodos estadísticos](#7-métodos-estadísticos)
8. [Hallazgos hasta la fecha](#8-hallazgos-hasta-la-fecha)
9. [Límites honestos](#9-límites-honestos)
10. [Ficheros del kit](#10-ficheros-del-kit)

---

## 1. Estado actual

| Paso | Qué hace | Estado |
|---|---|---|
| 0 | Comprobación del entorno y credenciales | ✅ hecho |
| 1 | Descarga ERA5-Land horario 1996-2025 | 🔄 **en curso** (camino crítico) |
| 2 | Agregación a diario, índices y ranking a 9 km | ⏸ espera al paso 1 |
| 3 | Red de estaciones de MeteoGalicia | ✅ 153 estaciones, 134 con serie útil |
| 4 | Afinado por altitud con Open-Meteo | ⏸ opcional |
| 5 | WRF de MeteoGalicia a 1 km | ✅ **catálogo resuelto**, listo para descargar |
| 6 | Fusión de escalas 9 km + 1 km | ⏸ depende del 5 |
| 7 | Evolución año a año de cada estación | ✅ hecho |
| 8 | Periodos de retorno y extremos no estacionarios | ✅ hecho sobre estaciones |
| 9 | Proyecciones climáticas de AdapteCCa | 🔍 catálogo reconocido, falta implementar la descarga |

**Lo que bloquea:** nada, salvo el tiempo de cola del Copernicus.

**El servidor de MeteoGalicia se ha movido, y su índice está roto.** El
histórico `mandeo.meteogalicia.es` devuelve HTTP 502; el servicio vivo es
`thredds.meteogalicia.gal`. Pero el `catalog.xml` de su raíz es una copia del
índice del servidor viejo: los 29 títulos son correctos y **los 29 enlaces dan
404**, porque apuntan a `/thredds/catalogos/...`, ruta que en este servidor ya no
existe. Lo que sí existe cuelga de `/thredds/catalog/modelos/...`, y su nodo
intermedio `modelos` tampoco es un fichero. Es decir: desde la raíz y por XML no
se llega a ningún sitio, aunque los datos estén ahí.

El kit lo resuelve por tres vías simultáneas, sin escribir rutas a mano:

1. prueba los dos hosts y usa el que responda (`GAL_THREDDS=<url>` fuerza uno);
2. si un `catalog.xml` falla o es ilegible, reintenta con el `catalog.html`
   hermano, que lo genera el propio TDS y sí trae los enlaces vivos — y del que
   se sacan los `urlPath` de los ficheros leyendo la query `?dataset=`;
3. descarta los conjuntos que el índice lista pero no se pueden abrir. Esto no
   es cosmético: uno de los muertos (`WRF_1km_HIST`) puntúa **más alto** que el
   bueno en la elección automática, así que sin este filtro el paso 5 se iría a
   un conjunto inexistente.

### Inventario del archivo WRF, ya verificado contra el servidor

| Conjunto | Malla | Cobertura | Archivo | Sirve |
|---|---|---|---|---|
| `modelos/WRF_ARW_1KM_HIST` (d02) | 1 km, 360×360 | 41,35-44,64 N / -10,29 a -5,75 | 1.789 días, **2021-09-03 → 2026-07-27** | ✅ **el elegido** |
| `modelos/WRF_ARW_1KM_HIST` (d01) | 5 km | igual | igual | resolución peor |
| `modelos/WRF_HIST` (d01) | 36 km, 104×118 | -49 a +19 / 24-60 N | desde **2008** | continental, inútil aquí |
| `modelos/WRF_ARW_1.3KM_HIST` (d04) | 1,3 km, 72×81 | -9,17 a -7,75 / 43,09-44,01 | desde 2011 | **solo el norte**; ellos lo marcan DEPRECATED |
| `wrf_*km/fmrc`, `latest.xml` | — | — | solo la pasada actual | no es archivo |

`WRF_1km_HIST` y `WRF_ARW_1KM_HIST` son **el mismo conjunto** con dos nombres.

Cada día publica **dos dominios en la misma carpeta**: `d02` (1 km) y `d01`
(5 km). El catálogo no garantiza el orden, así que el dominio se pide por
nombre (`--dominio d02`, que es el valor por defecto).

Variables disponibles: 45, entre ellas `temp` (K), `rh`, `mod` y `dir` (viento),
`prec`, `mslp`, `topo`, `land_use`. Eje temporal de 96 pasos horarios: la pasada
entera. Nos quedamos con las 24 h del propio día, que además son las de menor
alcance de predicción y por tanto las mejores.

**La malla del WRF incluye el océano y los embalses, y hay que quitarlos.**
Un tercio de los 60.690 puntos es agua. Sin separarla pasan dos cosas: la
obvia, que los veinte «sitios más frescos de Galicia» salen siendo el Atlántico
a la altura de Fisterra (19,6 °C de Tmax p90) y algún embalse de Ourense; y la
que no se ve, que al promediar el entorno de 9 km de un punto de costa entra mar
frío, con lo que **toda la franja costera aparece con una anomalía positiva que
es un artefacto del método, no un rasgo del terreno**. Las anomalías de −8 °C
tierra adentro eran embalses, no valles.

Se resuelve con una petición más (`05_wrf_dias_calidos.py --estaticos`), que baja
`topo` y `land_use`. La categoría de agua se deduce de los datos —es la que
domina donde la altitud es cero— en vez de codificar el 16 de USGS o el 17 de
MODIS, que el fichero no dice cuál usa. Después el suavizado a 9 km promedia
solo tierra y normaliza por cuántos vecinos válidos había, que es lo correcto
porque el término de comparación, ERA5-Land, también es solo tierra.

De regalo, `topo` da la **altitud** de cada punto de 1 km, que hacía falta de
todos modos: sin ella no se distingue «fresco porque está a 900 m» de «fresco
porque le entra la brisa», y solo la segunda es un sitio donde vivir.

**Cinco veranos, no quince — y no importa.** Del WRF solo se extrae el patrón
espacial, no la tendencia; para eso 200-250 días cálidos sobran. La serie larga
la pone ERA5-Land.

**`rh` viene en fracción, no en porcentaje.** El fichero declara `units="1"` y
los valores van de 0 a 1. Usarlo tal cual como porcentaje hace que
`clip(0,62, 1, 100)` dé 1 %, con lo que el humidex se queda igual que la
temperatura seca y **el bochorno desaparece sin producir ningún error**. Para
34 °C con 60 % de humedad, humidex real 46,2 frente a 34,0 mal calculado: doce
grados de diferencia, en silencio. `rh_a_porcentaje()` lo decide mirando los
datos, no el atributo, porque el atributo también puede mentir.

**Dónde estaba el enlace que faltaba.** El índice de la raíz (`/thredds/catalog.xml`)
trae los `href` en relativo (`catalogos/WRF/...`), que resueltos contra la raíz
dan `/thredds/catalogos/...` → 404. El **mismo** índice servido desde
`/thredds/catalog/catalog.xml` los resuelve a `/thredds/catalog/catalogos/...`,
que sí existe. Un prefijo de diferencia, y desbloquea el árbol entero.

**Cada fichero pesa 743 MB.** Es la salida d02 de 1 km, con todas las variables
y la pasada entera (96 h). Bajarlos enteros son 150 GB para 200 días, así que
descartado. El recorte —dos variables, la caja de Galicia y las 24 h del propio
día— deja eso en unos 15-25 MB por día, del orden de 4 GB en total.

**El `id` de un dataset NO es su `urlPath`.** Aquí el id es
`WRF_ARW_1KM_HIST/20260727/wrf_...nc4` y la ruta real de los servicios es
`modelos/WRF_ARW_1KM_HIST/20260727/wrf_...nc4`. En el `catalog.xml` viene el
`urlPath` bueno; en el `catalog.html` solo está el id, en la query `?dataset=`.
Por eso, cuando una página HTML lista ficheros, se consulta el XML hermano y se
usa lo que diga él. Con el id, tanto NCSS como OPeNDAP dan 404.

**Hay dos vías de descarga y el paso 5 usa la que funcione** (`--via auto`, o
`ncss` / `opendap` a mano). Las dos hacen lo mismo —pedir un trozo en lugar del
fichero entero— pero por caminos distintos: el NCSS entiende de latitud y
longitud y devuelve el recorte en una sola petición; OPeNDAP solo entiende de
índices, hay que traducirle la caja a filas y columnas, y hace muchas peticiones
pequeñas: es más lento, pero mucho más difícil de que lo rechacen por tamaño.

**Y la ruta del NetcdfSubset no se adivina: se lee.** Cada catálogo declara sus
`<service>` con su `base` — NCSS, OPeNDAP y descarga directa. TDS 4.x publica el
NCSS en `/thredds/ncss/` y 5.x en `/thredds/ncss/grid/`, y cada instalación puede
cambiarlo, así que probar las dos habituales es una apuesta. Además la
descripción de un dataset está en `<endpoint>/dataset.xml`: pedir el endpoint
pelado devuelve el **formulario HTML**, que no es un error HTTP — si el código no
lo distingue, cree que ha descrito el fichero sin haber descrito nada. Ambas
cosas eran fallos míos y están corregidas y cubiertas por pruebas.

**Sobre el volumen del archivo WRF.** El catálogo tiene un fichero por día y por
dominio desde que arrancó el archivo: son cientos de gigas y no se descargan.
El paso 5 baja **solo los 40 días más cálidos de cada verano**, recortados a
Galicia y con dos variables (`temp` y `rh`), porque para una pregunta sobre
episodios de calor extremo los demás días no aportan información. Son unos 600
ficheros pequeños en vez de 5.500 grandes. Y del WRF no se usa la serie temporal
—que no es homogénea, ver §7— sino solo el **patrón espacial**, así que ni
siquiera hace falta que su archivo cubra los 30 años: le basta con cubrir
suficientes episodios cálidos para que ese patrón sea estable.

**El paso 5 ya no espera al Copernicus.** Elegía los días cálidos a partir de
`diarios_galicia.nc`, que no existirá hasta que acaben los pasos 1 y 2. Pero ahí
no se está midiendo nada, solo *ordenando* los días para quedarse con los más
calurosos, y para eso las 155 estaciones de MeteoGalicia —ya descargadas— valen
igual: una ola de calor lo es en toda Galicia a la vez. Sobre datos simulados las
dos fuentes eligen el 92 % de los mismos días. `--fuente auto` usa la malla si
existe y las estaciones si no.

**Lo siguiente:** que termine el paso 1, luego el paso 2, y con la malla completa
repetir los pasos 7 y 8 sobre ella para contrastarlos con las estaciones. En
paralelo, `python 05_wrf_dias_calidos.py --explorar` contra el servidor nuevo:
el informe dice ahora **hasta dónde llega hacia atrás cada conjunto**, que es lo
que decide si se usa la malla de 1 km o la de 4 km.

---

## 2. La pregunta y cómo se traduce en números

El criterio no es «temperatura media baja»: eso premiaría sitios fríos y
desapacibles. Se miden dos cosas, con el peso acordado:

- **Picos de calor extremo — 60 %.** No la media, sino la cola de la distribución.
- **Confort real — 40 %.** Temperatura combinada con humedad y viento, no el
  termómetro seco.

Y aparecieron dos cosas por el camino que no estaban en el planteamiento inicial:

**El índice de suavidad.** Aplicando el criterio tal cual, los puestos 2 y 3 de
Galicia los ocupan Manzaneda y A Veiga, a 1.760 m: cero días por encima de 32 °C
y **109 días de helada al año**. Son frescos, no suaves. El índice de suavidad
añade una penalización por frío invernal (45 % calor, 30 % bochorno, 25 % frío)
para separar ambas cosas. Los dos índices se conservan y se reportan por separado.

**La no estacionariedad.** Ajustar una distribución de probabilidad a datos de un
clima que está cambiando es engañoso: el resultado es un promedio de los climas
pasados, no el de hoy. El paso 8 lo trata explícitamente (ver §7).

---

## 3. Glosario: qué significa cada índice

### 3.1 Los dos índices de confort que hay que entender

**Humidex** (`hx_max`, `hx_p99`, `d_hx30/35/40`)

Índice canadiense que responde a: *¿a qué temperatura seca equivaldría esto que
estoy sintiendo?* El sudor enfría al evaporarse, y cuanto más húmedo está el aire
menos se evapora. Con aire muy húmedo, 30 °C se llevan como 40 secos.

    Humidex = T + 0,5555 · (e − 10)

donde `e` es la presión de vapor de agua en hectopascales, que se calcula desde el
punto de rocío. Se expresa en grados, pero **no es una temperatura**: es una escala
de sensación. Umbrales de Environment Canada:

| Humidex | Significado |
|---|---|
| < 30 | sin molestia |
| 30 – 39 | molestia notable |
| 40 – 45 | fuerte malestar, evitar el esfuerzo |
| > 45 | peligro, riesgo de golpe de calor |

Por convenio se limita para que nunca baje de la temperatura real: mide el
agravamiento por humedad, nunca un alivio. **No incorpora el viento.**

*Ejemplo del análisis:* Arteixo tiene 1,1 días al año con humidex por encima de 35;
Pontevedra, a la misma distancia del mar, tiene 75. El termómetro seco no ve esa
diferencia.

**Temperatura de bulbo húmedo** (`wb_max`, `wb_p99`, `d_wb24/26/28`)

Cosa distinta y más fundamental. Es **la temperatura que marcaría un termómetro
envuelto en un paño mojado y ventilado**: el aire se enfría al saturarse de
humedad, y esa es la temperatura más baja alcanzable por evaporación en ese aire.

Su importancia es fisiológica, no de confort. El cuerpo humano se refrigera
sudando, es decir, por evaporación. **Por encima de unos 35 °C de bulbo húmedo el
cuerpo no puede disipar calor por mucha sombra, agua o ventilador que haya**, y
una persona sana en reposo muere en unas horas. Es un límite físico, no una
molestia.

Con aire seco, el bulbo húmedo queda muy por debajo de la temperatura real: a
40 °C con 20 % de humedad son 22,7 °C, perfectamente tolerable. Con aire saturado,
coincide con ella. Por eso 45 °C en el desierto son supervivibles y 35 °C con
humedad extrema no lo son.

Aquí se calcula con la aproximación de Stull (2011), válida entre −20 y 50 °C y
entre el 5 % y el 99 % de humedad, con error típico por debajo de 1 °C.

| Bulbo húmedo | Significado |
|---|---|
| < 24 °C | sin restricción |
| 24 – 26 °C | esfuerzo físico prolongado desaconsejado |
| 26 – 28 °C | umbral de suspensión de trabajo al aire libre (salud laboral) |
| > 31 °C | peligro grave incluso en reposo |
| > 35 °C | límite de supervivencia |

**En Galicia ningún sitio se acerca a 35 °C de bulbo húmedo.** Se incluye porque
su *tendencia* es informativa: mide si el clima se mueve hacia el calor húmedo
peligroso o hacia el calor seco tolerable, que son riesgos distintos.

**En resumen:** el humidex responde «cuánto se sufre», el bulbo húmedo responde
«a partir de dónde la fisiología deja de funcionar».

### 3.2 Los demás índices

**Calor extremo (peso 60 %)**

| Código | Definición |
|---|---|
| `d_tx28/30/32/35/38` | Días al año con temperatura máxima ≥ ese umbral |
| `tx_p99` | Percentil 99 de la máxima diaria: el 1 % de días más cálidos |
| `tx_p999` | Percentil 99,9: aproximadamente el día más cálido del año |
| `tx_max` | Máxima absoluta de todo el periodo |
| `tx_verano` | Máxima media de junio a agosto |
| `olas_n` | Episodios al año de ≥3 días consecutivos por encima del percentil 95 **local** |
| `olas_dias` | Días al año dentro de esos episodios |
| `olas_largas_n` | Ídem con ≥5 días consecutivos |
| `noches_trop` | Noches al año con mínima ≥ 20 °C, medida entre las 21 y las 9 hora local |
| `noches_18` | Ídem con umbral de 18 °C |
| `tn_p99` | Percentil 99 de la mínima diaria |

**Por qué dos tipos de umbral.** `d_tx35` mide **calor absoluto**: 35 °C son 35 °C
en Ourense y en Camariñas. `olas_dias` mide **anomalía local**, porque el percentil
95 se calcula sobre el clima de cada sitio. Los dos entran en el índice porque
miden cosas distintas: el calor absoluto es el que hace daño fisiológico, y la
anomalía es la que rompe la vida cotidiana, porque las casas y las costumbres
están adaptadas al clima habitual del lugar.

El percentil 95 se calcula con ventana móvil de calendario de ±15 días (método
ETCCDI), no como un único valor anual: así el umbral de julio no contamina al de
abril.

**Confort real (peso 40 %)**

| Código | Definición |
|---|---|
| `at_p99`, `at_max`, `d_at27/30/32/35` | **Temperatura aparente** de Steadman |
| `hx_*` | Humidex (ver §3.1) |
| `wb_*` | Bulbo húmedo (ver §3.1) |
| `hi_p99`, `d_hi32` | **Heat Index** de la NOAA, como segunda opinión |
| `noches_bochorno` | Noches con mínima ≥ 18 °C y aire prácticamente saturado |
| `hr_verano` | Humedad relativa media de junio a agosto |
| `viento_medio`, `viento_verano` | Velocidad media del viento a 10 m |
| `viento_dias_calidos` | Viento medio **los días de más calor**, que es cuando importa |

**Temperatura aparente de Steadman:**

    AT = T + 0,33 · e − 0,70 · v − 4,00

con `e` la presión de vapor en hPa y `v` el viento a 10 m en m/s. A diferencia del
humidex, **sí puede quedar por debajo de la temperatura real**, porque incorpora
el efecto refrescante del viento. En Galicia eso importa mucho: es lo que separa
la costa norte ventilada del interior encalmado aunque el termómetro marque lo
mismo. En las pruebas con datos sintéticos, el alivio por viento sale de +3,3 °C
en la costa frente a +0,7 °C en el interior.

*Nota:* la temperatura aparente solo está disponible en la malla de ERA5-Land, no
en las estaciones, porque el servicio de MeteoGalicia no publica viento junto a la
temperatura en el mismo endpoint.

**Contexto — no puntúa, pero se guarda**

| Código | Definición |
|---|---|
| `tmean` | Temperatura media diaria |
| `amplitud` | Diferencia media entre máxima y mínima del mismo día |
| `rango_anual` | Diferencia entre el mes más cálido y el más frío |
| `d_helada` | Días al año con mínima ≤ 0 °C |
| `tn_p01` | Percentil 1 de la mínima: el frío extremo |
| `alt` | Altitud en metros |
| `dist_costa_km` | Distancia al mar en línea recta |

La distancia a la costa se calcula por **relleno por inundación desde el
Atlántico**, no como «distancia a lo que no es tierra». Sin eso, los valles del
Miño y del Sil salían artificialmente marítimos porque el río cuenta como agua.

**Índices compuestos**

| Código | Definición |
|---|---|
| `score_calor` | Media ponderada de los percentiles de `d_tx32` (30 %), `d_tx35` (25 %), `tx_p99` (20 %), `olas_dias` (15 %) y `noches_trop` (10 %) |
| `score_confort` | Ídem con `at_p99` (30 %), `d_at30` (25 %), `hx_p99` (20 %), `d_hx35` (15 %) y `noches_bochorno` (10 %) |
| `indice_calor` | 0,6 · calor + 0,4 · confort. **El criterio pedido** |
| `suavidad` | 0,45 · calor + 0,30 · confort + 0,25 · frío invernal |

Ambos van de **0 (el punto más llevadero de Galicia) a 100 (el más castigado)**.
Son **rankings relativos dentro de Galicia**: un 0 no significa «fresco en términos
absolutos», significa «lo más fresco que hay aquí».

**Índices de tendencia y extremos** (pasos 7 y 8)

| Código | Definición |
|---|---|
| `*_sen_dec` | Pendiente de Sen por década (ver §7.1) |
| `*_p` | p-valor del test de Mann-Kendall |
| `*_salto` | Diferencia entre la segunda y la primera mitad del registro |
| `retorno_5a/10a/20a/50a` | Temperatura esperable una vez cada N años |
| `retorno_20a_p5/p95` | Intervalo del 90 % por bootstrap |
| `ns_tendencia_dec` | Tendencia del modelo **no estacionario**, °C/década |
| `ns_retorno_20a_2026/2045` | Nivel a 20 años evaluado en ese año concreto |
| `sesgo_estacionario` | Cuánto subestima el modelo de clima quieto el riesgo actual |
| `p_superar_max_30a` | Probabilidad de batir el récord actual entre 2026 y 2055 |

---

## 4. Las fuentes de datos y el papel de cada una

| Fuente | Resolución | Periodo | Papel | Clave |
|---|---|---|---|---|
| **ERA5-Land horario** (Copernicus CDS) | 9 km, 1 h | 1996-2025 | climatología y tendencia | cuenta gratuita |
| **Red de MeteoGalicia** | ~150 puntos | 2010-2026 | observación real, validación | no |
| **WRF de MeteoGalicia** | 1-4 km | días cálidos | patrón espacial fino | no |
| **AdapteCCa** (AEMET / MITECO) | 5 km | 1971-2100 | proyecciones futuras | no |
| **Open-Meteo** | ERA5-Land + MDT 90 m | 1996-2025 | afinado por altitud | no |

**El reparto no es arbitrario.** ERA5-Land es un reanálisis homogéneo: la misma
versión del modelo durante 30 años, así que sus tendencias son creíbles. El WRF de
MeteoGalicia es un archivo *operativo* de predicción cuya configuración ha cambiado
varias veces, de modo que su serie temporal **no** es homogénea y usarla para
tendencias mezclaría cambio climático con cambios de versión del modelo — pero a
1-4 km ve lo que ERA5-Land no puede ver. Por eso el paso 6 usa el WRF solo como
**patrón espacial**: la diferencia entre cada punto de 1 km y su entorno de 9 km,
que al ser una resta interna cancela el sesgo del modelo.

### 4.1 Por qué ERA5-Land horario y no el producto diario

El conjunto `derived-era5-land-daily-statistics` trae los estadísticos diarios ya
calculados. Pero **solo admite un año y un mes por petición** — en el formulario
web, año y mes son botones de radio, no casillas — lo que daría unas 1.800
peticiones. `reanalysis-era5-land` acepta listas, y al venir hora a hora permite
además calcular humidex, temperatura aparente y bulbo húmedo **en cada hora**
quedándose con el máximo del día, definir la noche como es debido, e incorporar el
viento.

**El límite de tamaño de petición.** La documentación del CDS dice 12.000 campos;
el servidor real rechaza 8.928 y acepta 5.952. El script lleva el límite calibrado
a 6.000, **medido contra el servidor y no leído del manual**, y si aun así se queja
reduce el troceado solo. El error de tamaño llega como HTTP 403, el mismo código
que usa el servidor cuando faltan los términos de uso, así que el manejo de errores
mira el texto antes que el código.

### 4.2 Qué aporta AdapteCCa y qué no

[AdapteCCa](https://escenarios.adaptecca.es/) es el visor de escenarios del Plan
Nacional de Adaptación al Cambio Climático (AEMET y MITECO). Publica proyecciones
regionalizadas para España **a 5 km — más fino que nuestros 9 km** — vía servidor
THREDDS, con 47 simulaciones de EURO-CORDEX (RCP4.5 y 8.5) y 24 regionalizaciones
estadísticas de CMIP6 (SSP1-2.6, 2-4.5, 3-7.0 y 5-8.5), en tres periodos futuros:
2011-2040, 2041-2070 y 2071-2100.

**Lo que sí responde.** Sus índices coinciden casi uno a uno con los nuestros:
`T5` son las noches tropicales, `T4` los días de helada, `T8` la duración máxima
de ola de calor, `T9` los grados-día de refrigeración. Y da el **abanico de
modelos**, no un único número: eso es justo lo que le falta a extrapolar una
tendencia observada.

**Lo que no responde, y son tres cosas:**

1. **Sus índices de calor son relativos, no absolutos.** `T7` cuenta los días cuya
   máxima supera *el percentil 90 del propio lugar*, y `T8` define ola de calor
   igual. El percentil 90 de Ourense ronda los 34 °C y el de Camariñas los 24, así
   que esos índices **pueden dar cifras parecidas en los dos sitios midiendo
   realidades separadas por diez grados**. Para «dónde hace menos calor en términos
   absolutos» no sirven. Sí sirven `tasmax`, `tasmaxp99` y `tasmaxmax`, que están
   confirmados en la rejilla observacional y probablemente también en las
   proyecciones.
2. **No hay ningún índice de confort con humedad.** Ni humidex, ni temperatura
   aparente, ni bulbo húmedo. Tiene humedad relativa (`H1`) y viento (`V1`) como
   variables sueltas, pero no los combina. Eso era el 40 % del criterio.
3. **Es un visor, no un análisis.** Pinta una variable cada vez sobre un mapa. No
   construye índices compuestos, no ordena emplazamientos y **no distingue «fresco
   por costero» de «fresco por estar a 1.700 metros»** — que resultó ser el
   hallazgo central de este trabajo.

Además su periodo histórico de referencia es 1971-2000, un clima que ya no existe.

**Cómo se va a usar.** No como sustituto sino tomándole la **señal de cambio** —la
anomalía de cada índice respecto a 1971-2000, por celda de 5 km y escenario— para
sumarla a nuestra climatología observada actual. Es el mismo método delta que se
usa con el WRF, aplicado en el tiempo en vez de en el espacio.

**Nota técnica:** el reconocimiento del catálogo dio error de OPeNDAP, pero el
fichero probado era de estaciones, cuya estructura suele atragantar al cliente.
Hay que reintentarlo sobre uno de rejilla antes de descartarlo; y si no funciona,
los ficheros anuales de índices no son grandes y pueden bajarse enteros.

### 4.3 Fuentes descartadas y por qué

- **`derived-utci-historical`** (ERA5-HEAT, el UTCI ya calculado): llega a hoy,
  pero está a **0,25° (~28 km)**. Galicia entera son diez píxeles y los costeros se
  mezclan con el mar. No distingue Fisterra de Carballo.
- **CERRA** (5 km, el mejor reanálisis regional europeo): se corta en junio de 2021.
- **Iberia01** (0,1°): termina en 2015.
- **CHELSA / WorldClim** (1 km): normales climáticas 1970-2000, demasiado antiguas.
- **earthkit de ECMWF**: su fuente `cds` es literalmente un envoltorio de `cdsapi`
  (mismo límite, misma cola) y su módulo `meteo` **no implementa humidex, UTCI,
  heat index ni temperatura aparente**. Exige Python ≥ 3.10, lo que además excluye
  la Raspberry. Sí se le tomó la idea del análisis de valores extremos.

---

## 5. Puesta en marcha

```bash
python 00_configura.py
```

Comprueba la versión de Python, instala dependencias, mira el espacio en disco,
deja la credencial del Copernicus en su sitio y lanza las **cinco suites de
pruebas**. No descarga ningún dato.

Cuenta gratuita del Copernicus, una sola vez:

1. Regístrate en <https://cds.climate.copernicus.eu/>
2. Entra en [reanalysis-era5-land](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land),
   pestaña *Download*, y **acepta los términos de uso** al final de la página.
   Sin esto las descargas fallan con un 403 poco informativo.
3. Copia el token de <https://cds.climate.copernicus.eu/how-to-api> a `~/.cdsapirc`
   (en Windows, `C:\Users\TuUsuario\.cdsapirc`).

La pestaña *Download* **no** da el token: sirve para construir peticiones. El token
está en `/how-to-api`, en un bloque de dos líneas con `url:` y `key:`.

### 5.1 Llevarse la descarga a una Raspberry Pi

El paso 1 es el único del kit que **no necesita numpy, pandas ni netCDF4**: solo
`cdsapi`, que es Python puro. Corre en una Raspberry modesta sin compilar nada, y
como son dos o tres días de espera en cola con 1,1 GB de disco, es el trabajo ideal
para dejarlo enchufado.

```bash
python3 -m pip install --user cdsapi     # ojo: python3, no python
mkdir -p ~/clima-galicia && cd ~/clima-galicia
# copiar aquí 01_descarga_cds.py, la carpeta descargas/ y ~/.cdsapirc
tmux new -s cds
python3 01_descarga_cds.py
# Ctrl+B y luego D para salir dejándolo corriendo; `tmux attach -t cds` para volver
```

- **No lo ejecutes con `sudo`**: `~` pasaría a ser `/root` y no encontraría la
  credencial.
- **No lances la descarga en dos máquinas a la vez**: el CDS limita las peticiones
  simultáneas por usuario y se encolarían entre sí.
- **El paso 2 no cabe en una Raspberry de 1 GB.** Cuando termine la descarga,
  copia `descargas/` de vuelta al PC.

---

## 6. Ejecución paso a paso

```bash
python 01_descarga_cds.py            # 180 peticiones, 2-3 días de cola, ~1,1 GB
python 01_descarga_cds.py --verificar  # audita lo descargado sin tocar el servidor
python 02_indices.py                 # ~15 min, sin red
python 03_estaciones_meteogalicia.py --desde 2010   # 30-60 min
python 07_evolucion_estaciones.py    # 2 min, reutiliza lo del paso 3
python 08_periodos_retorno.py        # 5 min
python 05_wrf_dias_calidos.py --explorar   # reconocimiento, no descarga nada
python 09_proyecciones.py --explorar       # ídem para AdapteCCa
```

Los pasos 1 y 5 son **reanudables**. Cada fichero se baja a un temporal y se
renombra al final, así que una interrupción nunca deja un `.nc` a medias; y se
comprueba la firma NetCDF de cada uno, de modo que un fichero truncado por un corte
de luz se detecta y se vuelve a pedir.

### 6.1 El WRF: solo los días que importan

Bajar los 15 años completos del archivo WRF son cientos de gigas. Pero como el
criterio es *evitar episodios de calor extremo*, **los días cálidos son los únicos
que aportan información**. El paso 5 elige los 40 días más cálidos de cada verano
según ERA5-Land y baja solo esos: 600 días en vez de 5.500, entre un 5 % y un 10 %
del volumen. Cuenta con 20-60 GB y varias horas.

---

## 7. Métodos estadísticos

### 7.1 Tendencias: pendiente de Sen y Mann-Kendall

Con 17 o 30 puntos, un solo verano extremo inclina una recta de mínimos cuadrados
de forma desproporcionada. La **pendiente de Sen** —la mediana de las pendientes
entre todos los pares de puntos— no se mueve por un valor anómalo. `test_evolucion.py`
lo verifica: con un atípico inyectado, Sen se queda en 0,500 y los mínimos
cuadrados se desvían visiblemente.

El **test de Mann-Kendall** dice si la tendencia se distingue del ruido. No exige
normalidad ni linealidad, solo monotonía.

### 7.2 Periodos de retorno: distribución de Gumbel

Contar días por encima de 32 °C responde a «con qué frecuencia». Para una casa que
se va a habitar treinta años, la pregunta útil es otra: **cuál es la máxima que
toca una vez cada 10, 20 o 50 años**. Eso es un periodo de retorno.

Se ajusta una **distribución de Gumbel** (valores extremos tipo I) a la serie de
máximas anuales, por **momentos-L**:

    sigma = l2 / ln(2)
    mu    = l1 − 0,5772 · sigma
    x(T)  = mu − sigma · ln(−ln(1 − 1/T))

**Nota honesta sobre esa elección.** Se repite habitualmente que los momentos-L
baten a la máxima verosimilitud con series cortas. `test_retorno.py` lo comprueba y
resulta **falso** para una Gumbel de dos parámetros: con n=17 la máxima
verosimilitud da 1,60 °C de error frente a 1,77 de los momentos-L. Esa ventaja es
real para la GEV de tres parámetros, donde el parámetro de forma es difícil, y aquí
no aplica. Se usan igualmente porque **son cerrados y no iterativos** —el bootstrap
hace cientos de miles de ajustes y no pueden fallar en converger— y porque aguantan
mejor un valor anómalo. La pérdida (0,2 °C) es pequeña al lado de la incertidumbre
real del intervalo, que ronda los 2 °C.

La incertidumbre se estima por **bootstrap**: 500 remuestreos y percentiles 5 y 95.

### 7.3 El problema de la estacionariedad

**Ajustar una distribución de probabilidad a datos de un clima que está cambiando
es engañoso.** Cada año pesa igual, así que lo que se obtiene no es la distribución
de hoy sino un promedio de los climas de todo el registro. Como el pasado era más
frío, **subestima sistemáticamente el riesgo actual**. Es un error con historia: en
2008 Milly y otros publicaron en *Science* «La estacionariedad ha muerto»,
precisamente porque la ingeniería hidráulica llevaba décadas dimensionando presas
con periodos de retorno de un clima que ya no existía.

El paso 8 lo trata dejando que la posición de la distribución dependa del tiempo:

    μ(t) = μ₀ + μ₁ · (t − t_ref)

ajustado por **máxima verosimilitud** — aquí sí, porque los momentos-L no tienen
versión no estacionaria y hace falta la verosimilitud para contrastar los dos
modelos con una **prueba de razón de verosimilitud**. Entonces el nivel de retorno
deja de ser un número y pasa a ser una curva: se puede pedir el extremo a 20 años
*evaluado en 2026* o *en 2045*.

Y se reporta además **la probabilidad de superar un umbral al menos una vez entre
2026 y 2055**, que es la cifra que corresponde a una decisión de vivienda. «Una vez
cada 50 años» suena raro, pero incluso con clima estable la probabilidad de verlo
alguna vez en 30 años de ocupación es del 45 %.

### 7.4 Por qué la tendencia hay que agruparla

`test_retorno.py` mide algo importante: con 30 máximas anuales y dispersión típica
de 2 °C, el contraste **solo detecta una tendencia de +0,5 °C/década en uno de cada
cuatro puntos**. El estimador es insesgado —recupera +0,545 de media— y la tasa de
falsos positivos es correcta (4 %), pero su ruido (0,40) casi iguala a la señal
(0,50).

Eso significa que **por estación no se puede afirmar casi nada** sobre la tendencia
de los extremos. No es un defecto del método: es el límite de información del dato.

La salida es agrupar. Galicia entera se calienta a la vez, así que el error típico
de la media regional cae con la raíz del número de puntos. La prueba lo confirma:
con un punto la estimación es inútil; con 100 puntos sale **+0,486 ± 0,048**, con
intervalo del 95 % entre +0,393 y +0,580, que ya excluye el cero limpiamente.

**Conclusión práctica:** usar la tendencia regional para proyectar, y las
individuales solo como indicación de si un sitio se desvía del conjunto.

---

## 8. Hallazgos hasta la fecha

Con las 134 estaciones de MeteoGalicia con serie útil (2010-2026):

**El gradiente es enorme.** De **0,06 a 57 días al año por encima de 32 °C**:
Camariñas frente a Leiro, separados por 150 km. Las máximas absolutas van de 29 a
44 °C.

**Hay dos maneras de ser fresco y solo una es suave.** La costa atlántica noroeste
(Camariñas, Arteixo, Malpica, A Coruña) tiene cero o casi cero días por encima de
32 °C **y cero heladas**. Manzaneda y A Veiga, a 1.760 m, tienen los mismos cero
días de calor y **109 días de helada**.

**La humedad parte la costa en dos.** Arteixo y Camariñas tienen 1 y 3 días al año
de humidex por encima de 35; Pontevedra, a la misma distancia del mar, tiene 75.

**Las noches tropicales son cosa de las Rías Baixas, no de Ourense.** Vigo registra
11,4 noches al año por encima de 20 °C y Ourense capital 5,1. El mar impide que la
noche refresque; el interior seco se desploma de madrugada.

**Dentro de un mismo concello hay diferencias enormes.** Chantada tiene una
estación a 391 m con índice 71 y otra a 842 m con índice 30. Vigo va de 30 a 53.
Esto es exactamente lo que una malla de 9 km no puede ver, y la razón de ser del
paso 5.

**Un caso interesante:** ladera costera elevada. Burela tiene una estación a 421 m
a 3,7 km del mar con **0,4 días de helada al año**: se lleva el enfriamiento de la
altitud sin pagar el invierno, porque el mar sostiene las noches.

**Tendencias (2010-2026).** Temperatura media **+0,83 °C/década**, significativa en
el 83 % de las estaciones. Días con humidex > 35: **+8,6 al año por década**. Días
de helada: −3,4 por década. Tendencia regional de las máximas anuales:
**+1,0 °C/década (IC 95 %: +0,83 a +1,20)**, significativa por estación solo en el
19 % de los casos, tal como predijo el análisis de potencia.

> ⚠️ Ese +1,0 °C/década conviene tomarlo como **cota superior**. Son 16 años que
> empiezan en 2010 (fresco) y terminan en años cálidos, y una ventana corta infla
> las pendientes. Es aproximadamente el doble del ritmo europeo típico. Los 30 años
> de ERA5-Land lo contrastarán.

---

## 9. Límites honestos

- **9 km no ve el fondo de valle.** ERA5-Land suaviza el relieve. Un fondo de valle
  cerrado puede estar 3-4 °C por encima de su celda en una ola de calor. Para eso
  están los pasos 4 y 5.
- **La fusión de escalas no arregla un sesgo estructurado.** Si el WRF calienta de
  más de forma uniforme, la resta lo elimina; si lo hace con un patrón, se cuela.
  Por eso el paso 3 no es opcional: es el único contraste independiente.
- **Las estaciones no son una malla.** Cubren donde MeteoGalicia decidió medir, y
  su emplazamiento importa (algunas son agrometeorológicas, en campo abierto).
- **Series de 16 años en las estaciones**, frente a los 30 de ERA5-Land. Y tienen
  inhomogeneidades —cambios de sensor, reubicaciones— que pueden inventar
  tendencias. ERA5-Land no las tiene por construcción.
- **El `indice_calor` es relativo a Galicia**, no una escala absoluta.
- **Hora local fija (UTC+1)**, sin horario de verano. Irrelevante para máximas y
  mínimas; desplaza una hora el corte de la noche en verano.
- **El bulbo húmedo usa la aproximación de Stull**, con error típico bajo 1 °C.
- **Extrapolar más allá de 2 o 3 veces la longitud del registro es especulativo.**
  Con 16 años, el nivel a 20 años es sólido y el de 50 orientativo.

---

## 10. Ficheros del kit

```
00_configura.py                 comprobación del entorno y credenciales
comun.py                        índices térmicos y de extremos
thredds.py                      cliente de servidores THREDDS
celdas_galicia.csv              las 368 celdas ERA5-Land de Galicia

01_descarga_cds.py              ERA5-Land horario 1996-2025
02_indices.py                   agregación horaria a diaria, índices y ranking
03_estaciones_meteogalicia.py   red de observación real
04_afina_openmeteo.py           altitud MDT 90 m + afinado de la lista corta
05_wrf_dias_calidos.py          WRF 1-4 km, solo los días cálidos
06_alta_resolucion.py           fusión de escalas
07_evolucion_estaciones.py      evolución año a año y tendencias
08_periodos_retorno.py          Gumbel, periodos de retorno, no estacionariedad
09_proyecciones.py              proyecciones de AdapteCCa (reconocimiento)

test_indices.py                 índices térmicos y de extremos
test_malla.py                   paso 2 de extremo a extremo
test_wrf.py                     catálogo THREDDS y fusión de escalas
test_evolucion.py               pendiente de Sen y Mann-Kendall
test_retorno.py                 Gumbel, bulbo húmedo y no estacionariedad
```

Las pruebas trabajan en un directorio temporal propio (variable `GAL_BASE`), así
que **nunca borran descargas reales**.

### Qué subir al repositorio

| Momento | Ficheros |
|---|---|
| Tras el paso 2 | `indices_galicia.csv`, `tendencias_galicia.csv`, `resumen.txt` |
| Tras el paso 3 | `indices_estaciones.csv`, `estaciones_lista.csv` |
| Tras el paso 7 | `evolucion_estaciones.csv`, `tendencias_estaciones.csv`, `resumen_evolucion.txt` |
| Tras el paso 8 | `retorno_estaciones.csv`, `resumen_retorno.txt` |
| Tras el paso 6 | `alta_resolucion.csv.gz`, `resumen_alta_resolucion.txt` |
| Reconocimientos | `wrf_exploracion.txt`, `adaptecca_exploracion.txt` |

**Nunca**: las carpetas `descargas/` y `wrf/` (gigas de datos brutos, regenerables)
ni el fichero `.cdsapirc`. El límite de subida por el navegador de GitHub es de
**25 MiB por fichero**.
