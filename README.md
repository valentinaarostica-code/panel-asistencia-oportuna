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

Todavía no hay login; los roles se agregarán más adelante.

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

# 4. Levantar el servidor
uvicorn app.main:app --reload
```

Luego abrir <http://127.0.0.1:8000> (registro diario) o <http://127.0.0.1:8000/panel> (panel del jardín).

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

Volver a generar **borra** la base y la crea de nuevo (se pierde lo registrado a mano).

Con la semilla por defecto, los tres primeros jardines muestran situaciones distintas: *Rayito de Sol* (las ausencias bajan durante el año), *Semillitas* (suben) y *Pequeños Pasos* (buen promedio con 4 niños en rojo escondidos).

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
  db.py            SQLite: tablas, guardado y consultas
  main.py          Rutas web (FastAPI)
  templates/       Pantallas (Jinja2): base.html, registro.html, panel.html
  static/          estilos.css
scripts/
  generar_datos.py Genera los datos ficticios
  resumen_datos.py Resumen por jardín en la terminal
tests/             Pruebas (unittest)
docs/reglas.md     Reglas del semáforo explicadas sin código
data/              Aquí se crea asistencia.db (no se sube a git)
```

## Tecnología

- Python con la librería estándar para la lógica y los datos (`sqlite3`, `unittest`).
- FastAPI, Uvicorn y Jinja2 para las pantallas web; `python-multipart` para leer formularios; `httpx` solo para las pruebas.
