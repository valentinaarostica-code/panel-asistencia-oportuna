"""Configuración del Panel de Asistencia Oportuna.

Aquí viven los números y las listas que se pueden cambiar sin tocar el resto
del código. Si el equipo decide otro umbral u otro motivo de ausencia, se
cambia SOLO en este archivo.

IMPORTANTE: todos los datos de este proyecto son FICTICIOS y se generan
automáticamente. Los umbrales son una propuesta del equipo (supuesto [S]),
basada en la definición de ausentismo crónico (faltar 10% o más de los días).
"""

from pathlib import Path

# --- Identidad del sistema -------------------------------------------------
NOMBRE_SISTEMA = "Panel de Asistencia Oportuna"
AVISO_DATOS_FICTICIOS = "Datos ficticios con fines académicos (UCN, Desafío SI)."

# --- Dónde se guarda la base de datos ---------------------------------------
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
RUTA_BD = RAIZ_PROYECTO / "data" / "asistencia.db"

# --- Estados posibles de un niño en un día ---------------------------------
PRESENTE = "presente"
AUSENTE = "ausente"
ESTADOS = (PRESENTE, AUSENTE)

# --- Motivos de ausencia (lo que elige quien registra) -----------------------
SALUD = "Salud"
TRASLADO = "Traslado o transporte"
FAMILIAR = "Situación familiar"
CLIMA = "Clima"
SIN_INFORMACION = "Sin información"
MOTIVOS = (SALUD, TRASLADO, FAMILIAR, CLIMA, SIN_INFORMACION)

# --- Semáforo ---------------------------------------------------------------
# Se expresan en porcentaje (números enteros) para que las comparaciones sean
# exactas y no tengan errores de decimales.
UMBRAL_AMARILLO_PCT = 10  # desde 10% de faltas: amarillo
UMBRAL_ROJO_PCT = 20      # desde 20% de faltas: rojo

VERDE = "verde"
AMARILLO = "amarillo"
ROJO = "rojo"
SIN_DATOS = "sin_datos"
NIVELES = (VERDE, AMARILLO, ROJO, SIN_DATOS)

# Con muy pocos días de clases, una sola falta da un porcentaje enorme.
# Antes de este mínimo no se pinta el semáforo (queda "sin_datos").
MIN_DIAS_LECTIVOS = 10

# --- Alertas ----------------------------------------------------------------
FALTAS_SEGUIDAS_ALERTA = 3   # 3 o más faltas seguidas hasta hoy
VENTANA_RECIENTE_DIAS = 20   # para detectar niños que empeoran hace poco

# --- Estructura de los jardines (para los datos ficticios) --------------------
NIVELES_SALA = ("Sala cuna", "Medio menor", "Medio mayor")
