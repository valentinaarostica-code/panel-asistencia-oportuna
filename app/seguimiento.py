"""Seguimiento de casos del Comité de Asistencia.

Un niño en rojo es candidato a caso. El Comité abre el caso y registra una
revisión cada mes con las acciones que se hicieron. En cada revisión se mira el
porcentaje de faltas de los últimos días de clases (pct_reciente de
rules.evaluar_nino) y se compara con la revisión anterior:

- "mejora": bajó al menos cfg.MEJORA_MIN_PUNTOS puntos;
- "sin mejora": si no.

Con cfg.REVISIONES_SIN_MEJORA_ESCALA revisiones seguidas sin mejora, el caso se
escala. Si el niño ya no está en rojo, se sugiere cerrarlo.

Este archivo tiene dos partes:
1. La regla, en funciones puras (sin base de datos), fáciles de probar.
2. Las operaciones (abrir, revisar, cerrar) que validan y guardan con app.db.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from typing import Iterable, Optional, Sequence

from app import config as cfg
from app import db
from app.rules import ResultadoNino, evaluar_nino

# Resultado de una revisión
MEJORA = "mejora"
SIN_MEJORA = "sin_mejora"
ETIQUETA_RESULTADO = {MEJORA: "Mejora", SIN_MEJORA: "Sin mejora", None: "Sin revisiones"}

# Estado de un caso abierto
EN_SEGUIMIENTO = "en_seguimiento"
ESCALAR = "escalar"
SUGERIR_CIERRE = "sugerir_cierre"
ETIQUETA_ESTADO = {
    EN_SEGUIMIENTO: "En seguimiento",
    ESCALAR: "Escalar",
    SUGERIR_CIERRE: "Sugerir cierre",
}

MAX_OBSERVACION = 300
# Un RUT chileno escrito con guion (12.345.678-9 o 12345678-K): no debe guardarse.
_PATRON_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")


# --- 1. La regla (funciones puras) ----------------------------------------------

def resultado_revision(pct_anterior: float, pct_actual: float) -> str:
    """Devuelve MEJORA si las faltas recientes bajaron al menos MEJORA_MIN_PUNTOS puntos.

    Se redondea la diferencia para que una baja de justo 5 puntos (por ejemplo
    de 30% a 25%) cuente como mejora aunque haya errores de decimales.
    """
    baja = pct_anterior - pct_actual
    return MEJORA if round(baja, 6) >= cfg.MEJORA_MIN_PUNTOS else SIN_MEJORA


def resultados_del_caso(pct_apertura: float, pcts_revisiones: Sequence[float]) -> list[str]:
    """Resultado de cada revisión: la primera se compara con la apertura; las demás, con la anterior."""
    resultados = []
    anterior = pct_apertura
    for pct in pcts_revisiones:
        resultados.append(resultado_revision(anterior, pct))
        anterior = pct
    return resultados


def sin_mejora_seguidas(resultados: Sequence[str]) -> int:
    """Cuántas revisiones seguidas sin mejora hay al final. Una mejora reinicia la cuenta."""
    cuenta = 0
    for resultado in reversed(resultados):
        if resultado != SIN_MEJORA:
            break
        cuenta += 1
    return cuenta


def estado_caso(resultados: Sequence[str], nivel_actual: str) -> str:
    """Estado de un caso abierto.

    - "Sugerir cierre" si el niño ya no está en rojo (tiene prioridad: si salió
      del rojo, lo útil es poder cerrar el caso);
    - "Escalar" si lleva REVISIONES_SIN_MEJORA_ESCALA o más revisiones seguidas sin mejora;
    - "En seguimiento" en cualquier otro caso.
    """
    if nivel_actual != cfg.ROJO:
        return SUGERIR_CIERRE
    if sin_mejora_seguidas(resultados) >= cfg.REVISIONES_SIN_MEJORA_ESCALA:
        return ESCALAR
    return EN_SEGUIMIENTO


# --- 2. Operaciones con la base de datos ------------------------------------------
# No hacen commit: quien las llama decide cuándo confirmar (por ejemplo con "with conn:").

class ErrorSeguimiento(ValueError):
    """Un dato no cumple las reglas del seguimiento. El mensaje es para mostrar en pantalla."""


def evaluar_al(conn: sqlite3.Connection, nino_id: int, fecha: Optional[date] = None) -> ResultadoNino:
    """Evalúa al niño con su historial hasta una fecha (incluida). Sin fecha, con todo."""
    return evaluar_nino(db.estados_de_nino(conn, nino_id, hasta=fecha))


def abrir_caso(
    conn: sqlite3.Connection, nino_id: int, fecha: date, hoy: Optional[date] = None
) -> int:
    """Abre un caso para un niño que está en rojo en esa fecha. Devuelve el id del caso."""
    hoy = hoy or date.today()
    nino = db.obtener_nino(conn, nino_id)
    if nino is None:
        raise ErrorSeguimiento("El niño no existe.")
    if fecha > hoy:
        raise ErrorSeguimiento("No se puede abrir un caso con fecha futura.")
    if db.caso_abierto_de_nino(conn, nino_id) is not None:
        raise ErrorSeguimiento(f"{nino['codigo']} ya tiene un caso abierto.")
    resultado = evaluar_al(conn, nino_id, fecha)
    if resultado.nivel != cfg.ROJO:
        raise ErrorSeguimiento(
            f"{nino['codigo']} no está en rojo al {fecha.strftime('%d-%m-%Y')}: "
            "solo se abren casos para niños en rojo."
        )
    return db.insertar_caso(conn, nino_id, fecha, resultado.pct_reciente)


def _limpiar_acciones(acciones: Iterable[str]) -> list[str]:
    elegidas = set(acciones)
    desconocidas = elegidas - set(cfg.ACCIONES_SEGUIMIENTO)
    if desconocidas:
        raise ErrorSeguimiento(
            "Acción desconocida: " + ", ".join(sorted(desconocidas)) + ". Usa las del catálogo."
        )
    if not elegidas:
        raise ErrorSeguimiento("Marca al menos una acción realizada.")
    return [a for a in cfg.ACCIONES_SEGUIMIENTO if a in elegidas]  # en el orden del catálogo


def _limpiar_observacion(observacion: Optional[str]) -> Optional[str]:
    texto = (observacion or "").strip()
    if not texto:
        return None
    if len(texto) > MAX_OBSERVACION:
        raise ErrorSeguimiento(f"La observación debe tener {MAX_OBSERVACION} caracteres o menos.")
    if _PATRON_RUT.search(texto):
        raise ErrorSeguimiento(
            "La observación parece tener un RUT. No escribas datos personales: usa solo el código del niño."
        )
    return texto


def registrar_revision(
    conn: sqlite3.Connection,
    caso_id: int,
    fecha: date,
    acciones: Iterable[str],
    observacion: Optional[str] = None,
    hoy: Optional[date] = None,
) -> int:
    """Registra la revisión mensual de un caso abierto. Devuelve el id de la revisión.

    El pct_reciente se calcula con el historial del niño SOLO hasta la fecha de la
    revisión, para que corregir asistencias posteriores no cambie lo ya revisado.
    """
    hoy = hoy or date.today()
    caso = db.obtener_caso(conn, caso_id)
    if caso is None:
        raise ErrorSeguimiento("El caso no existe.")
    if caso["estado"] != "abierto":
        raise ErrorSeguimiento("El caso está cerrado: no se pueden agregar revisiones.")
    if fecha > hoy:
        raise ErrorSeguimiento("La revisión no puede tener fecha futura.")
    if fecha <= date.fromisoformat(caso["fecha_apertura"]):
        raise ErrorSeguimiento("La revisión debe ser posterior a la apertura del caso.")
    revisiones = db.revisiones_de_caso(conn, caso_id)
    if revisiones and fecha <= date.fromisoformat(revisiones[-1]["fecha"]):
        raise ErrorSeguimiento("La revisión debe ser posterior a la última revisión del caso.")

    acciones_ok = _limpiar_acciones(acciones)
    observacion_ok = _limpiar_observacion(observacion)
    pct = evaluar_al(conn, caso["nino_id"], fecha).pct_reciente
    return db.insertar_revision(conn, caso_id, fecha, pct, acciones_ok, observacion_ok)


def resumen_caso(conn: sqlite3.Connection, caso: sqlite3.Row) -> dict:
    """Todo lo que se muestra de un caso: revisiones, resultados y estado."""
    revisiones = db.revisiones_de_caso(conn, caso["id"])
    resultados = resultados_del_caso(
        caso["pct_reciente_apertura"], [r["pct_reciente"] for r in revisiones]
    )
    for revision, resultado in zip(revisiones, resultados):
        revision["resultado"] = resultado
    actual = evaluar_al(conn, caso["nino_id"])
    ultimo = resultados[-1] if resultados else None
    estado = estado_caso(resultados, actual.nivel)
    return {
        "caso": caso,
        "revisiones": revisiones,
        "resultados": resultados,
        "ultimo_resultado": ultimo,
        "sin_mejora_seguidas": sin_mejora_seguidas(resultados),
        "nivel_actual": actual.nivel,
        "pct_actual": actual.pct_inasistencia,
        "pct_reciente_actual": actual.pct_reciente,
        "estado": estado,
    }


def cerrar_caso(conn: sqlite3.Connection, caso_id: int, hoy: Optional[date] = None) -> None:
    """Cierra un caso. Solo se puede cuando el estado es "Sugerir cierre"."""
    hoy = hoy or date.today()
    caso = db.obtener_caso(conn, caso_id)
    if caso is None:
        raise ErrorSeguimiento("El caso no existe.")
    if caso["estado"] != "abierto":
        raise ErrorSeguimiento("El caso ya está cerrado.")
    if resumen_caso(conn, caso)["estado"] != SUGERIR_CIERRE:
        raise ErrorSeguimiento(
            f"Solo se puede cerrar el caso de {caso['codigo']} cuando ya no está en rojo."
        )
    db.cerrar_caso(conn, caso_id, hoy)
