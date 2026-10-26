# Panel de Asistencia Oportuna

Prototipo académico de Sistema de Información para el seguimiento oportuno de la asistencia en jardines infantiles de Hogar de Cristo. UCN, Desafío SI.

> **Datos ficticios con fines académicos.** Los jardines, niños y registros de asistencia se generan automáticamente; nada corresponde a personas reales. Los niños se identifican solo con un código seudónimo (por ejemplo `J03-N008`), sin nombre ni RUT.

## El problema

Hoy la asistencia se mira como **promedio del jardín, cada 4 meses**. Un promedio alto puede esconder niños con ausentismo grave que nadie ve a tiempo.

Ejemplo con los datos de demostración: el jardín *Pequeños Pasos (ficticio)* tiene **92,5% de asistencia promedio**, pero **4 de sus 25 niños (16%) están en rojo**. El panel muestra ambos números juntos para que esos casos no pasen desapercibidos.

## Pantallas

| Pantalla | Ruta | Para qué sirve |
|---|---|---|
| **Registro diario** | `/` | Elegir jardín, sala y fecha; marcar a cada niño presente o ausente (con motivo) y guardar. Muestra el semáforo de cada niño, que se actualiza al guardar. |
| **Panel del jardín** | `/panel` | Lo que usa la directora para decidir a quién llamar o visitar esta semana: asistencia promedio y niños en rojo lado a lado, conteos por color y la lista de niños ordenada por prioridad (rojo → racha → amarillo → verde → sin datos), con filtros por sala, color y "solo con alerta". |
| **Panel de la Subdirección** | `/subdireccion` | Todos los jardines juntos, para decidir en cuáles reforzar el apoyo antes de que termine el cuatrimestre: tabla con promedio, conteos por color, % en rojo, % en riesgo y fila de totales; **puesto por promedio** y **puesto por % en rojo** lado a lado, y la señal *"Promedio que oculta casos graves"*. Se puede ordenar por columna y filtrar por región. |
| **Seguimiento de casos** | `/casos` | La vista del Comité de Asistencia (reunión mensual): niños en rojo sin caso (con "Abrir caso"), casos abiertos con su estado, y un formulario para registrar cada revisión con las acciones realizadas. |

Todas las pantallas muestran el aviso de datos ficticios, el menú entre pantallas y la fecha de los datos ("Datos al"). Los colores y estados siempre llevan texto, no solo color. Todavía no hay login; los roles se agregarán más adelante.

## Semáforo

Resumen de las reglas (el detalle está en [docs/reglas.md](docs/reglas.md)):

| Color | % de faltas | Qué se hace |
|---|---|---|
| Verde | menos de 10% | Nada especial |
| Amarillo | desde 10% hasta menos de 20% | La directora lo revisa |
| Rojo | 20% o más | Se abre un caso de seguimiento |
| Sin datos | menos de 10 días de clases | Se espera |

Alertas: **racha** (3 o más faltas seguidas hasta hoy), **riesgo amarillo**, **riesgo rojo** y **tendencia** (va bien en el año, pero faltó 10% o más en los últimos 20 días de clases).

Los umbrales son una propuesta del equipo (supuesto [S]) y se cambian en un solo lugar: [app/config.py](app/config.py).

## Seguimiento de casos

Un niño en rojo es candidato a caso. El Comité abre el caso y registra una revisión cada mes con las acciones realizadas (del catálogo: llamado a la familia, visita al hogar, reunión con la familia, apoyo de traslado o transporte, derivación a red de apoyo).

En cada revisión se guarda el **% de faltas de los últimos 20 días de clases**, calculado solo con la asistencia hasta la fecha de esa revisión (corregir días posteriores no cambia lo ya revisado). Luego:

| Resultado de la revisión | Cuándo |
|---|---|
| **Mejora** | Las faltas recientes bajaron 5 puntos o más respecto de la revisión anterior (o de la apertura, si es la primera) |
| **Sin mejora** | En cualquier otro caso |

| Estado del caso | Cuándo |
|---|---|
| **Sugerir cierre** | El niño ya no está en rojo. Solo entonces aparece el botón "Cerrar caso" |
| **Escalar** | 2 o más revisiones seguidas sin mejora (una mejora reinicia la cuenta) |
| **En seguimiento** | En cualquier otro caso |

Un niño no puede tener dos casos abiertos a la vez, y solo se abre un caso si está en rojo. Los casos no se borran. La observación de cada revisión es opcional y corta: **no se deben escribir nombres ni datos de salud o personales**, solo el código del niño (el sistema rechaza textos que parecen un RUT).

## Supuestos del equipo [S]

Todos están en [app/config.py](app/config.py):

| Constante | Valor | Para qué |
|---|---|---|
| `UMBRAL_AMARILLO_PCT` / `UMBRAL_ROJO_PCT` | 10 / 20 | Colores del semáforo |
| `MIN_DIAS_LECTIVOS` | 10 | Días mínimos antes de pintar el semáforo |
| `FALTAS_SEGUIDAS_ALERTA` / `VENTANA_RECIENTE_DIAS` | 3 / 20 | Alertas de racha y de tendencia |
| `UMBRAL_PROMEDIO_ALTO_PCT` / `MIN_ROJOS_ALERTA_JARDIN` | 90 / 3 | Señal "Promedio que oculta casos graves" (y la advertencia del panel del jardín, que aparece desde el primer niño en rojo) |
| `MEJORA_MIN_PUNTOS` / `REVISIONES_SIN_MEJORA_ESCALA` | 5 / 2 | Mejora de un caso y cuándo se escala |

## Cómo ejecutarlo (Windows, PowerShell)

Requisito: Python 3.10 o superior (probado con 3.13).

```powershell
# 1. Crear y activar el entorno virtual (solo la primera vez se crea)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Generar los datos ficticios (crea data\asistencia.db)
python scripts\generar_datos.py

# 4. Crear los casos de seguimiento de ejemplo
python scripts\sembrar_casos.py

# 5. Levantar el servidor
uvicorn app.main:app --reload
```

Luego abrir en el navegador:

- <http://127.0.0.1:8000> — Registro diario
- <http://127.0.0.1:8000/panel> — Panel del jardín
- <http://127.0.0.1:8000/subdireccion> — Panel de la Subdirección
- <http://127.0.0.1:8000/casos> — Seguimiento de casos

Si PowerShell no deja ejecutar `Activate.ps1`, correr una vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

En macOS o Linux, el paso de activación es `source .venv/bin/activate`.

### Datos ficticios

`generar_datos.py` usa una semilla fija (2026), así que todos ven exactamente los mismos datos. Algunas opciones:

```powershell
python scripts\generar_datos.py --semilla 7
python scripts\generar_datos.py --jardines 5 --ninos-por-jardin 20
python scripts\resumen_datos.py          # semáforo de cada jardín en la terminal
```

Volver a generar **borra** la base y la crea de nuevo: se pierde lo registrado a mano, incluidos los casos. Después hay que volver a correr `sembrar_casos.py`.

Con la semilla por defecto, los tres primeros jardines muestran situaciones distintas: *Rayito de Sol* (las ausencias bajan durante el año), *Semillitas* (suben) y *Pequeños Pasos* (buen promedio con 4 niños en rojo escondidos). En la Subdirección, Pequeños Pasos queda **1º por asistencia promedio y 9º por % en rojo**: es el único jardín con la señal "Promedio que oculta casos graves".

### Casos de ejemplo

`sembrar_casos.py` usa los 4 niños en rojo de Pequeños Pasos y deja:

- un caso con una revisión que **mejora**;
- un caso con 2 revisiones **sin mejora** (estado *Escalar*);
- un caso **recién abierto**, sin revisiones;
- un niño en rojo **sin caso**, para probar el botón "Abrir caso".

Las fechas no están escritas a mano: el script las busca en los datos generados (revisiones separadas por cerca de un mes, en meses anteriores) para que den cada resultado. Si ya hay casos guardados no hace nada, para no borrar los creados desde la pantalla:

```powershell
python scripts\sembrar_casos.py --reiniciar   # borra TODOS los casos y crea los ejemplos de nuevo
```

## Pruebas

```powershell
python -m unittest discover -s tests -t .
```

Las pruebas usan bases temporales: no tocan `data\asistencia.db`.

## Estructura

```
app/
  config.py        Umbrales, motivos de ausencia y textos (lo único que se ajusta)
  rules.py         Cálculos del semáforo y alertas (no sabe de base de datos ni pantallas)
  models.py        Fichas de datos y reglas de calidad (p. ej. un niño presente no lleva motivo)
  seguimiento.py   Regla de mejora y estado de los casos, y abrir/revisar/cerrar con sus validaciones
  db.py            SQLite: tablas, guardado y consultas
  main.py          Rutas web (FastAPI)
  templates/       Pantallas (Jinja2): base.html (aviso y menú), registro.html, panel.html,
                   subdireccion.html, casos.html
  static/          estilos.css
scripts/
  generar_datos.py Genera los datos ficticios
  sembrar_casos.py Crea los casos de seguimiento de ejemplo
  resumen_datos.py Resumen por jardín en la terminal
tests/             Pruebas (unittest); base_demo.py prepara la base de demostración
docs/reglas.md     Reglas del semáforo explicadas sin código
data/              Aquí se crea asistencia.db (no se sube a git)
```

## Tecnología

- Python con la librería estándar para la lógica y los datos (`sqlite3`, `unittest`).
- FastAPI, Uvicorn y Jinja2 para las pantallas web; `python-multipart` para leer formularios; `httpx` solo para las pruebas.
