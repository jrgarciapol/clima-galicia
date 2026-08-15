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
   · [4.3 AEMET OpenData](#43-aemet-opendata-qué-añadiría-y-qué-no)
5. [Puesta en marcha](#5-puesta-en-marcha)
6. [Ejecución paso a paso](#6-ejecución-paso-a-paso)
7. [Métodos estadísticos](#7-métodos-estadísticos)
8. [Hallazgos hasta la fecha](#8-hallazgos-hasta-la-fecha)
   · [8.6 Errores propios](#86-errores-propios-que-conviene-no-repetir)
9. [Límites honestos](#9-límites-honestos)
10. [Ficheros del kit](#10-ficheros-del-kit)

---

## 1. Estado actual

| Paso | Qué hace | Estado |
|---|---|---|
| 0 | Comprobación del entorno y credenciales | ✅ hecho |
| 1 | Descarga ERA5-Land horario **2011-2025** | ✅ hecho (90 peticiones) |
| 2 | Agregación a diario, índices y ranking a 9 km | ✅ 328 celdas |
| 3 | Red de estaciones de MeteoGalicia | ✅ 153 estaciones, 134 con serie útil |
| 4 | Afinado por altitud con Open-Meteo | ⏸ opcional |
| 5 | WRF de MeteoGalicia a 1 km | ✅ 251 días descargados |
| 6 | Fusión de escalas 9 km + 1 km | ✅ 60.690 puntos |
| 7 | Evolución año a año de cada estación | ✅ hecho |
| 8 | Periodos de retorno y extremos no estacionarios | ✅ hecho sobre estaciones |
| 9 | Proyecciones climáticas de AdapteCCa | 🔄 descarga escrita, falta ejecutarla |
| 10 | Validación contra las 153 estaciones | ✅ hecho |
| 11 | Mapa interactivo de estaciones | ✅ hecho |
| 12 | Series largas de AEMET para la tendencia | ✅ 58 estaciones, 1.108 años |
| 13 | **ROCIO_IBEB**: 72 años de observación en rejilla de 5 km | ✅ hecho |

**Lo que bloquea:** nada. La cadena está completa de extremo a extremo.

**Corrección importante sobre el periodo.** Durante buena parte del proyecto la
documentación decía «30 años». Es falso: la descarga se lanzó con
`--desde 2011 --hasta 2025`, o sea **15 años (2011-2025)**, que son las 90
peticiones del paso 1. Para *ordenar* sitios entre sí quince años sobran; para
*cuantificar una tendencia* se quedan cortos (ver §8). Extenderla a 1996-2010
son otras 90 peticiones y dos o tres días de cola.

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
siquiera hace falta que su archivo cubra la serie entera: le basta con cubrir
suficientes episodios cálidos para que ese patrón sea estable.

**El paso 5 ya no espera al Copernicus.** Elegía los días cálidos a partir de
`diarios_galicia.nc`, que no existirá hasta que acaben los pasos 1 y 2. Pero ahí
no se está midiendo nada, solo *ordenando* los días para quedarse con los más
calurosos, y para eso las 155 estaciones de MeteoGalicia —ya descargadas— valen
igual: una ola de calor lo es en toda Galicia a la vez. Sobre datos simulados las
dos fuentes eligen el 92 % de los mismos días. `--fuente auto` usa la malla si
existe y las estaciones si no.

**Lo siguiente**, por orden de valor:

1. **Serie larga para la tendencia.** Es el único hueco real. Dos caminos, y son
   complementarios: ampliar ERA5-Land a 1996-2010, o traer las estaciones
   históricas de AEMET, que llegan mucho más atrás (§4.3).
2. Implementar la descarga de las proyecciones de AdapteCCa (paso 9).
3. Superponer al mapa de estaciones los puntos del modelo de 1 km, para ver
   medida y modelo a la vez.

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
| **ERA5-Land horario** (Copernicus CDS) | 9 km, 1 h | **2011-2025 descargado** (disponible desde 1950) | climatología y tendencia | cuenta gratuita |
| **Red de MeteoGalicia** | ~150 puntos | 2010-2026 | observación real, validación | no |
| **WRF de MeteoGalicia** | 1-4 km | días cálidos | patrón espacial fino | no |
| **AdapteCCa** (AEMET / MITECO) | 5 km | 1971-2100 | proyecciones futuras | no |
| **Open-Meteo** | ERA5-Land + MDT 90 m | desde 1950 | afinado por altitud | no |

**El reparto no es arbitrario.** ERA5-Land es un reanálisis homogéneo: la misma
versión del modelo durante toda la serie, así que sus tendencias son creíbles. El WRF de
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

**El primer sondeo no sirvió, y conviene entender por qué.** Recorrió el catálogo
por anchura hasta profundidad 5, agotó su tope de 250 peticiones dentro de las
ramas de observaciones y **no llegó a abrir ni una sola de proyecciones**. Los
117 ficheros del inventario son todos observacionales. El fichero que probó por
OPeNDAP —y que falló— también lo era, así que ese error no dice nada sobre lo que
de verdad queremos bajar.

El catálogo es demasiado ancho para recorrerlo entero, así que ahora se recorre
**por prioridad en vez de por anchura**: las ramas de proyecciones primero,
rejilla antes que estaciones, CMIP6 antes que CMIP5, y Canarias y Andorra ni se
visitan. Con `--prof 8 --tope 600`, y avisando por pantalla de cada petición para
que no parezca colgado.

**El segundo sondeo sí funcionó:** 2.585 ficheros, **2.439 de proyecciones**, y
**OPeNDAP responde**, así que se recorta a Galicia sin bajar España entera.

Lo aprovechable está en `Proyecciones_CMIP6_en_rejilla/Climatologia`, y su
estructura es mejor de lo esperado: **cada fichero trae dentro los cuatro
periodos y los doce modelos**, no hay que bajar uno por periodo. Un fichero
`climatology_CMIP6_ESD-RegBA_<variable>_<escenario>.nc` tiene dimensiones
`member=12, time_filter=17, period=4, lat=251, lon=400`, y **tres variables
dentro: el valor absoluto, la anomalía y la anomalía relativa** — o sea, la
señal de cambio ya calculada, que es exactamente lo que pide el método delta.

Las siete que responden a nuestra pregunta, todas bajo `Temperatura/`:

| variable | qué es | para qué |
|---|---|---|
| `tasmaxp99` | percentil 99 de la máxima | **es literalmente nuestro `tx_p99`** |
| `tasmaxmax` | máxima absoluta | el pico |
| `tasmaxhwdmax` | duración máxima de ola de calor | persistencia |
| `tasmax` | máxima media | confort medio |
| `tasminNa20` | noches por encima de 20 °C | noches tropicales, **absolutas** |
| `cdd` | grados-día de refrigeración | cuánto aire acondicionado |
| `tmean` | media | contraste con la climatología observada |

Son absolutas, no relativas al percentil del propio lugar: se libra así el
problema del punto 1 de más arriba, que era el que amenazaba con hacer inútil
toda esta fuente. Siete variables × cuatro escenarios = **28 ficheros**.

### 4.3 AEMET OpenData: qué añadiría y qué no

Investigado en julio de 2026. Conclusión corta: **sirve, pero no para lo que
parece.** No aporta densidad espacial; aporta la única cosa que aquí falta, que
es **serie larga**.

**Qué es.** El portal de datos abiertos de la Agencia Estatal de Meteorología.
Clave de API gratuita, se pide por correo desde `opendata.aemet.es`, se confirma
por un enlace que caduca a los 5 días y luego **no expira**. Límite de **40
peticiones por minuto**. La licencia obliga a citar a AEMET como autor.

**Cómo funciona.** Dos saltos, no uno: la petición no devuelve los datos sino un
JSON con dos URL, `datos` y `metadatos`, que hay que descargar aparte. Los
endpoints relevantes:

```
/api/valores/climatologicos/inventarioestaciones/todasestaciones/
/api/valores/climatologicos/diarios/datos/fechaini/{ini}/fechafin/{fin}/estacion/{idema}/
```

**Ventajas reales:**

- **Series de décadas.** Es lo que no tenemos. MeteoGalicia da 17 años y
  ERA5-Land, tal como se descargó, 15. Los observatorios principales de AEMET en
  Galicia —A Coruña, Santiago Aeropuerto, Vigo Aeropuerto, Ourense, Lugo— tienen
  series diarias que arrancan entre los años cuarenta y los setenta. Con eso la
  tendencia de §8.5 deja de ser una cota superior y pasa a ser un número
  defendible.
- **Datos validados**, no la salida cruda de la red automática.
- **Tercera opinión independiente** sobre el orden de los sitios.

**Limitaciones, y son serias:**

- **Muy pocas estaciones en Galicia** con serie larga: del orden de diez o
  quince, frente a las 147 de MeteoGalicia. Para el mapa no aporta nada.
- **Están en aeropuertos y ciudades.** Un aeropuerto tiene su propio microclima
  (pista, campo abierto) y un observatorio urbano arrastra isla de calor. No son
  representativos de «un sitio donde vivir».
- **Sin humedad garantizada.** El registro diario trae `tmax`, `tmin`, `tmed`,
  precipitación, viento medio, racha, insolación y presión. La humedad relativa
  no está en todas las estaciones ni en todos los periodos, así que **el humidex
  puede no ser calculable**, y el humidex es el 40 % del criterio.
- **Inhomogeneidad.** Ochenta años dan para varios traslados y cambios de
  instrumento, y cada uno mete un salto artificial en la serie. Un trabajo
  climatológico serio homogeneiza antes de calcular tendencias; nosotros no
  vamos a hacerlo, así que hay que mirar las series a ojo antes de fiarse.
- **Los números vienen con coma decimal** en cadenas de texto (`"23,4"`). Es la
  clase de detalle que rompe una carga silenciosamente.

**Sobre el límite de fechas por petición hay contradicción**: la documentación no
lo fija, y las fuentes de terceros dan cifras distintas —10 días para
`todasestaciones`, bastante más para una estación suelta—. Es exactamente lo que
pasó con el límite de coste del CDS, donde la documentación decía 12.000 campos y
el servidor real rechazaba a partir de ~6.000. **El plan es el mismo: medirlo
contra el servidor en vez de creérselo**, empezando por un rango amplio y
partiéndolo cuando lo rechace.

**Recomendación, ya implementada como paso 12.** Objetivo acotado: traer las
series largas de Galicia y usarlas **solo para la pregunta de la tendencia**, no
para el ranking de sitios.

Y con un giro que hace el paso mucho más útil de lo que parecía: en vez de
limitarse a dar «la tendencia buena», **mide cuánto miente una ventana corta**.
Para cada serie larga calcula la pendiente sobre el periodo completo y sobre
*todas* las ventanas móviles de 15 años, y compara. Si las ventanas cortas se
reparten simétricamente alrededor de la larga, nuestra ventana no tiene por qué
estar sesgada; si están sistemáticamente por encima, el +1,31 °C/década es un
artefacto de haber empezado a mirar en 2011. Eso convierte una advertencia
cualitativa en un número que se puede restar.

```
python 12_aemet.py --explorar      # clave, estaciones y límite real de la API
python 12_aemet.py --descargar --desde 1950
python 12_aemet.py --analizar
```

La clave **no se escribe en ningún fichero del proyecto**: sale de la variable de
entorno `AEMET_API_KEY` o de `~/.aemetrc`, igual que `.cdsapirc`. Las dos están en
`.gitignore`, y la carpeta `aemet/` también.

Dos detalles que el propio código comprueba: la clave es un **JWT y lleva dentro
su fecha de caducidad** —las que emite el portal duran 100 días, no son
indefinidas como dicen las FAQ—, y el **límite de rango por petición se mide
contra el servidor**, probando de 10 años hacia abajo hasta que uno funciona *y*
la respuesta cubre de verdad el rango pedido. Un servidor que acepta la petición
y devuelve solo un trozo es peor que uno que falla, porque no avisa.

### 4.4 ROCIO_IBEB, la fuente que apareció tarde

Rejilla de observaciones diarias de AEMET: **0,05° (~5 km), 1951-2022**, Tmax,
Tmin y precipitación, por interpolación óptima sobre la España peninsular.
Descarga directa por HTTP, sin clave ni cola. Es mejor que ERA5-Land en las tres
cosas que importan aquí: más larga (72 años frente a 15), más fina (5 km frente
a 9) y **observacional** en vez de reanálisis.

No lo sustituye, sin embargo: **ROCIO no trae humedad**, así que no da humidex, y
el humidex es el 40 % del criterio. Sirve para la tendencia y para contrastar la
climatología de extremos, no para el ranking de confort.

Detalles del formato, sacados del README del propio conjunto:

- Rejilla de 280×240 en **polo rotado**, pero los ficheros incluyen `lat(rlat,rlon)`
  y `lon(rlat,rlon)` en 2D, así que no hace falta hacer la conversión.
- Variable `maxtemp` / `mintemp`, en grados Celsius, ausencias como **-9999**.
- Un fichero por año, unos **99 MB**. Los 72 años de las dos variables son ~14 GB;
  el paso 13 recorta a Galicia y borra el original, y quedan unos 300 MB.
- **Trampa:** los ficheros de tmax y de tmin **se llaman igual**
  (`sfcanYYYY0101aYYYY1231_rot_mask.nc`) y solo los distingue la carpeta de la que
  cuelgan. Extraerlos al mismo sitio deja mínimas etiquetadas como máximas sin
  ningún aviso. El paso 13 comprueba la variable de dentro, no el nombre.

**Y una advertencia sobre la homogeneidad que corrige lo que se dijo antes.** El
cribado por «homogeneidad y completitud» que menciona la web es de la rejilla de
**precipitación**. El README de temperatura dice lo contrario con todas las
letras: se generó *«using all available observations at AEMET Banco Nacional de
Datos, not only a selected group as in precipitation version 1»*. Es decir, en
temperatura **no hubo cribado**. La red que alimenta la interpolación cambia con
los años, y un cambio de densidad puede meter una tendencia que no es clima. Hay
que medirlo, no suponerlo.

### 4.5 Fuentes descartadas y por qué

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

python 09_proyecciones.py --explorar       # catálogo de AdapteCCa (~15 min)
python 09_proyecciones.py --describe       # etiquetas de los ejes (1 min)
python 09_proyecciones.py --descargar      # 28 recortes de Galicia (~15 min)
python 09_proyecciones.py --analizar       # 1 min, sin red
```

Los pasos 1, 5 y 9 son **reanudables**. Cada fichero se baja a un temporal y se
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

### 8.1 La respuesta, en una línea

**El noroeste costero, de Camariñas a Ferrol.** Lo dicen por separado el modelo
de 1 km y los termómetros, que es lo más sólido que ha producido este trabajo.

### 8.2 Lo que dicen los termómetros (17 años, sin modelo)

Sobre las 30 estaciones a menos de 8 km del **océano** y por debajo de 300 m:

| | altitud | Tmax p99 | días > 30 °C/año | humidex p99 | días humidex > 30 |
|---|---|---|---|---|---|
| **Arteixo** | 5 m | **24,7** | **0,4** | **32,3** | **9** |
| **Camariñas** | 5 m | 26,0 | 0,3 | 34,5 | 14 |
| **A Coruña** | 5 m | 26,5 | 0,5 | 35,5 | 25 |
| **Malpica** | 161 m | 26,8 | 0,7 | 36,5 | 28 |
| Ribadeo | 51 m | 27,7 | 1,2 | 38,2 | 49 |
| Viveiro | 59 m | 28,8 | 1,6 | 40,3 | 70 |
| Vigo | 25 m | 30,7 | 5,4 | 40,2 | 52 |
| Pontevedra | 52 m | 34,1 | 19,5 | 47,4 | 113 |
| **Leiro** (Ourense) | 105 m | **40,0** | **79,8** | **59,3** | **153** |

**Arteixo tiene 0,4 días al año por encima de 30 °C; Leiro tiene 80.**

Dos matices que rompen la simplificación «la costa es fresca»:

- **Las Rías Baixas no están en el grupo bueno.** Vigo 5,4 días, Pontevedra 19,5,
  O Rosal 24. Se parecen más a Ourense que a A Coruña.
- **La costa cantábrica es fresca pero bochornosa.** Ribadeo y Viveiro tienen una
  Tmax parecida a la de Camariñas y **49 y 70 días** de humidex sobre 30, frente
  a 14. Si el criterio pesa el confort, quedan fuera.

### 8.3 Lo que aporta bajar a 1 km

Dentro de **una sola celda de ERA5-Land** de 9 km hay **3,9 °C** entre el
percentil 1 y el 99 del detalle fino. Más que el calentamiento acumulado de
varias décadas: elegir con la malla gruesa habría sido elegir a ciegas.

Y ese detalle es física, no ruido. Ajustando la anomalía térmica contra la
anomalía topográfica sale un gradiente de **−6,46 °C por cada 1.000 m**, cuando
el gradiente vertical del aire libre es −6,5. Nadie metió ese número: sale de
restar el WRF consigo mismo suavizado. El relieve explica el **34 %** de la
variación fina (correlación −0,583); el **0,47 °C** restante es brisa, inversión
de valle y cercanía al mar a igualdad de altura, que es justo lo que ERA5-Land
no puede ver.

### 8.4 Qué tal se porta el campo fusionado (paso 10)

Contrastado contra 145 estaciones con al menos 8 años:

| | error absoluto | correlación | rangos |
|---|---|---|---|
| ERA5-Land 9 km | 2,90 °C | 0,780 | 0,777 |
| **Fusión 1 km** | **2,67 °C** | **0,856** | **0,838** |

- **Sesgo frío de −2,74 °C** a igualdad de altitud. Es lo esperable: una celda de
  reanálisis es una media de área y las medias no alcanzan los extremos de un
  punto. Los valores del campo **no son lecturas de termómetro**; con la
  corrección y descontando el desajuste de altitud modelo-garita, el error
  absoluto baja a **1,37 °C**.
- De las 15 estaciones realmente más frescas, el campo acierta 9; de las 15 más
  calurosas, 12.
- **El sesgo es mayor donde más aprieta**: los doce peores errores están todos en
  sitios calurosos (O Rosal −7,6, Tui −7,2, Leiro −6,2, Ourense −5,9). La
  diferencia real entre la costa y el valle del Miño es **mayor** que la que
  sale en el mapa, no menor.
- **Y el punto débil coincide con la cabeza del ranking.** ERA5-Land solo tiene
  celdas sobre tierra, y a 9 km los cabos son casi todo mar: allí la
  climatología no se interpola, se toma prestada de la celda de tierra más
  cercana. El error sube de 2,67 a 3,24 °C, y **13 de los 15 primeros** son de
  esos. Restringiendo el ranking a puntos con base interpolada sobreviven **4 de
  los 30 primeros**. La zona no cambia; el orden dentro de ella, sí.

### 8.5 Tendencias: lo que dicen 72 años de observación

`resumen.txt`, con 15 años de ERA5-Land, daba **+1,31 °C/década** en la máxima
de verano. La rejilla ROCIO_IBEB de AEMET, con **72 años (1951-2022)** y 1.174
celdas de Galicia, dice esto:

| | tendencia 1951-2022 |
|---|---|
| máxima **media** de verano | **+0,200 °C/década** |
| **percentil 99** de la máxima | **+0,336 °C/década** |
| días por encima de 30 °C | +0,86 días/década |
| días por encima de 32 °C | +0,26 días/década |

Nuestro +1,31 era **seis veces** el ritmo largo.

**Pero la explicación no es la que se dio al principio.** La hipótesis era que
una ventana de 15 años exagera *por ser corta*. Los datos la refutan: la mediana
de las 58 ventanas móviles de 15 años es **+0,219**, contra +0,200 de la serie
completa. Una ventana corta **no está sesgada**; solo es imprecisa, con un rango
de −0,84 a +1,44.

Lo que ocurre es distinto y más relevante: **todas las ventanas recientes están
altas**, y de forma creciente.

| ventana | tx_verano | tx_p99 |
|---|---|---|
| 2002-2016 | +0,46 | +0,53 |
| 2005-2019 | +0,33 | +0,83 |
| 2008-2022 | **+0,85** | **+1,61** |

Eso no es ruido: es **aceleración real**. La serie de 72 años promedia unos años
cincuenta y sesenta planos con cuatro décadas rápidas, y esa media diluye el
ritmo actual. Ni el +0,20 ni el +1,31 son «la respuesta»: el primero es el
promedio histórico y el segundo describe un periodo concreto que no se puede
extrapolar cuarenta años.

**La cola se calienta un 68 % más rápido que la media** (+0,336 frente a +0,200).
Como el criterio pesa los extremos al 60 %, el problema crece más deprisa que el
verano medio.

#### La brecha se abre, poco pero de forma consistente

Correlación entre lo caluroso que es un sitio y lo rápido que se calienta:
**+0,792**. No es sutil.

| | climatología | tendencia |
|---|---|---|
| cuarto más fresco de Galicia | 21,3 °C | **+0,124 °C/década** |
| cuarto más caluroso | 26,1 °C | **+0,263 °C/década** |

Los sitios calurosos se calientan **el doble de rápido**. En cuarenta años son
**0,56 °C más de diferencia**: sobre los 4,8 °C que separan hoy a los dos
cuartos, un 12 % más de brecha.

Coincide con lo que predice la física —el mar amortigua la costa por su inercia
térmica, y el suelo seco del interior deja de evaporar en verano y se calienta
más— así que no parece un artefacto de la interpolación.

**Para la decisión, refuerza el resultado por partida doble:** los sitios frescos
no solo son más frescos hoy, sino que además se están calentando más despacio. El
orden entre sitios debería aguantar, y la ventaja de la costa noroeste crece con
el tiempo en vez de encogerse.

#### Los termómetros de AEMET lo confirman sin modelo por medio (paso 12)

58 estaciones, 1.108 años-estación, series diarias descargadas una a una de
AEMET OpenData. Nada de reanálisis ni de interpolación: termómetro y libro de
registro.

**La prueba que importaba** era medir la *misma ventana* que la nuestra. 18
estaciones tienen 2011-2025 completo:

| | tx_verano |
|---|---|
| mediana de las 18 estaciones | **+1,13 °C/década** |
| rango p10-p90 | +0,25 a +2,86 |
| nuestro ERA5-Land, misma ventana | +1,31 |
| ROCIO, 1951-2022 | +0,20 |

**Nuestro +1,31 no era un artefacto.** Los termómetros, por su cuenta y con otro
método, dan +1,13 para el mismo periodo. La diferencia entre +1,3 y +0,2 no
estaba en el modelo: estaba en el periodo.

**Y confirman que las ventanas cortas no engañan.** En las 6 estaciones con más
de 40 años, la mediana de todas sus ventanas de 15 años menos su tendencia larga
es **−0,06 °C/década**. Prácticamente cero, igual que en ROCIO (+0,02). Una
ventana de 15 años es imprecisa, no tramposa.

**Comparación justa, mismo periodo 1980-2025 para todas:**

| estación | tx_verano | tx_p99 | días >30 °C |
|---|---|---|---|
| A Coruña | +0,38 | +0,33 | **+0,00** /década |
| A Coruña Aeropuerto | +0,26 | +0,18 | +0,28 |
| Santiago Aeropuerto | +0,37 | +0,28 | +0,83 |
| Vigo Aeropuerto | +0,60 | +0,58 | +2,50 |
| **Ourense** | +0,57 | +0,50 | **+7,41** |

Es la brecha de ROCIO, medida con termómetros y sin ninguna cadena de proceso
por medio. En temperatura media la diferencia parece modesta —+0,26 frente a
+0,57—, pero en **lo que decide la habitabilidad** es abismal: A Coruña gana
**cero** días de más de 30 °C por década y Ourense gana **siete y medio**. En
los 45 años de la serie, eso son 33 días de verano que Ourense ha ganado y A
Coruña no.

### 8.6 Errores propios que conviene no repetir

Van aquí porque todos eran silenciosos —ninguno producía una excepción— y
cualquiera habría envenenado el resultado:

| Qué pasaba | Cómo se detectó |
|---|---|
| `rh` en fracción tratada como porcentaje: el humidex se quedaba igual que la temperatura seca | mirando las unidades del fichero, `units="1"` |
| El océano y los embalses en el ranking, y el mar contaminando la media de 9 km de toda la costa | los 20 «sitios más frescos» estaban a −9,45 de longitud |
| Píxeles 8 °C más fríos que su entorno sin relieve que lo explique | la prueba topográfica: 271 puntos, el 0,68 % |
| «Distancia a la costa» medida a cualquier agua: Castrelo de Miño, en un embalse a 59 km del mar, contaba como estación costera | un ranking de litoral lleno de estaciones de Ourense |
| El `id` de un dataset usado como `urlPath` | 404 en todas las peticiones |
| Afirmar que unas coordenadas eran embalses sin comprobarlo | Rafa las miró en un mapa |

## 9. Límites honestos

- **9 km no ve el fondo de valle.** ERA5-Land suaviza el relieve. Un fondo de valle
  cerrado puede estar 3-4 °C por encima de su celda en una ola de calor. Para eso
  están los pasos 4 y 5.
- **La fusión de escalas no arregla un sesgo estructurado.** Si el WRF calienta de
  más de forma uniforme, la resta lo elimina; si lo hace con un patrón, se cuela.
  Por eso el paso 3 no es opcional: es el único contraste independiente.
- **Las estaciones no son una malla.** Cubren donde MeteoGalicia decidió medir, y
  su emplazamiento importa (algunas son agrometeorológicas, en campo abierto).
- **La serie larga ya está, y cambió la conclusión sobre la tendencia** (§8.5).
  Lo que sigue sin estar es el futuro: todo esto describe el pasado. Ver §9 bis.
  Las estaciones además tienen inhomogeneidades —cambios de sensor,
  reubicaciones— que pueden inventar tendencias; ERA5-Land no, por construcción.
- **El campo fusionado va 2,74 °C frío** y su error absoluto es de 1,37 °C tras
  corregirlo. Ordena mucho mejor de lo que acierta el valor: correlación de
  rangos 0,83 frente a un sesgo de casi tres grados.
- **Los cabos son extrapolación.** Donde ERA5-Land no tiene tierra alrededor, la
  climatología se toma prestada de la celda más cercana. Es el 26 % de los puntos
  de tierra y el 41 % de los 400 mejores del ranking. La zona ganadora no
  depende de eso; el orden dentro de la zona, sí.
- **El WRF aporta cinco veranos, no quince.** Suficiente para un patrón espacial,
  que es lo único que se le pide, pero su archivo de 1 km empieza en septiembre
  de 2021 y no hay forma de alargarlo hacia atrás.
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

01_descarga_cds.py              ERA5-Land horario (se descargó 2011-2025)
02_indices.py                   agregación horaria a diaria, índices y ranking
03_estaciones_meteogalicia.py   red de observación real
04_afina_openmeteo.py           altitud MDT 90 m + afinado de la lista corta
05_wrf_dias_calidos.py          WRF 1 km, solo los días cálidos (+ --estaticos)
06_alta_resolucion.py           fusión de escalas
07_evolucion_estaciones.py      evolución año a año y tendencias
08_periodos_retorno.py          Gumbel, periodos de retorno, no estacionariedad
09_proyecciones.py              proyecciones de AdapteCCa (CMIP6 a 5 km)
10_validacion.py                contraste del campo contra las estaciones reales
11_mapa_estaciones.py           mapa interactivo de las 147 estaciones
plantilla_est.html              plantilla del mapa (la usa el paso 11)
12_aemet.py                     series largas de AEMET y sesgo de ventana corta
13_rocio.py                     rejilla ROCIO_IBEB de 5 km, 1951-2022

sincroniza.py                   pull / instalar kit / push, sin subir datos brutos
.gitignore                      la primera red: qué no llega nunca a GitHub

test_indices.py                 índices térmicos y de extremos
test_malla.py                   paso 2 de extremo a extremo
test_wrf.py                     catálogo THREDDS y fusión de escalas
test_evolucion.py               pendiente de Sen y Mann-Kendall
test_retorno.py                 Gumbel, bulbo húmedo y no estacionariedad
test_aemet.py                   formato de AEMET y sesgo de ventana corta
test_rocio.py                   recorte de la rejilla y tendencia larga
test_sincroniza.py              que aborta antes de subir datos o credenciales
test_proyecciones.py            seleccion de ejes de AdapteCCa y brecha
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
| Tras el paso 6 | `alta_resolucion.csv.gz`, `resumen_alta_resolucion.txt`, `ranking_60_40.csv` |
| Tras el paso 10 | `validacion_estaciones.csv`, `resumen_validacion.txt` |
| Tras el paso 11 | `estaciones_galicia.html` |
| Tras el paso 12 | `aemet_series.csv`, `resumen_aemet.txt`, `aemet_exploracion.txt` |
| Tras el paso 13 | `resumen_rocio.txt`, `rocio_tendencias.csv` |
| Tras el paso 9 | `resumen_proyecciones.txt`, `proyecciones_galicia.csv.gz`, `ranking_con_proyeccion.csv` |
| Reconocimientos | `wrf_exploracion.txt`, `adaptecca_exploracion.txt`, `wrf_fallos.txt` |

**Nunca**: las carpetas `descargas/`, `wrf/`, `aemet/` y `rocio/` (datos brutos,
regenerables) ni los ficheros `.cdsapirc` y `.aemetrc`. El límite de subida por
el navegador de GitHub es de **25 MiB por fichero**.

### Trabajar con git en vez de subir a mano

Subir ficheros uno a uno por el navegador funciona, pero cansa. Con el
repositorio clonado en el disco duro, `git pull` trae los scripts nuevos y
`git push` sube las salidas, sin tocar el navegador.

**Lo que protege el repositorio es `.gitignore`**, que está en la raíz del kit y
tiene que estar *commiteado* antes de la primera subida. Excluye:

```
descargas/   wrf/   aemet/   rocio/     # datos brutos, decenas de GB
*.nc  *.tar.gz  *.grib                  # cualquier fichero de datos suelto
.cdsapirc  .aemetrc                     # credenciales
__pycache__/  _pruebas*/                # basura de Python y de los tests
```

Con eso, aunque el clon esté en la misma carpeta donde se descargan los datos,
`git status` no ve las carpetas pesadas y **no hay forma de subirlas por
descuido**. Un `git add .` es seguro.

Primera vez, en la carpeta del proyecto (Windows o Raspberry, da igual):

```bash
git clone https://github.com/jrgarciapol/clima-galicia.git
```

Si la carpeta ya existe con datos dentro y no se quiere mover nada:

```bash
cd carpeta-del-proyecto
git init
git remote add origin https://github.com/jrgarciapol/clima-galicia.git
git fetch origin
git checkout -t origin/main -f      # el .gitignore llega en este paso
```

#### `sincroniza.py`: el ciclo en un comando

Se ejecuta **dentro de la carpeta del proyecto**, la que tiene el `.git`. Da
igual desde qué subcarpeta: busca la raíz él solo.

```bash
python sincroniza.py                       # traer lo último (git pull)
python sincroniza.py clima-galicia.zip     # instalar un kit nuevo y subirlo
python sincroniza.py --subir               # subir las salidas generadas
python sincroniza.py --revisar             # solo comprobar, sin subir nada
```

Un ciclo completo queda así. En el PC, tras recibir un kit:

```bash
python sincroniza.py clima-galicia.zip
```

En la Raspberry, antes de ejecutar un paso:

```bash
python sincroniza.py
python 12_aemet.py --analizar
python sincroniza.py --subir -m "salidas del paso 12"
```

**Lo que aporta no es ahorrar comandos, es la comprobación previa.** Antes de
cada subida lista lo que va a subir con su tamaño y **aborta** si encuentra:

| Qué caza | Ejemplo |
|---|---|
| carpetas de datos brutos, a cualquier profundidad | `salidas/wrf/d02.nc` |
| extensiones de datos | `.nc`, `.grib`, `.tar.gz`, `.parcial` |
| credenciales | `.aemetrc`, `.cdsapirc` |
| **cualquier fichero de más de 20 MB**, aunque sea `.csv` | `salida_enorme.csv` |

El último es el que de verdad hace falta: el `.gitignore` cubre lo previsible,
y esta comprobación cubre lo que no se le ocurrió a nadie. Son dos redes
independientes, y `test_sincroniza.py` comprueba las dos por separado —monta un
repositorio de git real y le mete un `.nc`, una credencial y un CSV de 23 MB—.

Importa porque **subir un fichero grande no se deshace**: aunque se borre
después, sigue en el historial de git y GitHub lo sirve igual. Hay que
arreglarlo *antes* del push, con `git rm --cached -r <ruta>` (que lo saca del
índice sin borrarlo del disco). Y si lo que se cuela es una credencial, no basta
con borrarla: hay que darla por comprometida y regenerarla.
