"""Reglas del semáforo y de las alertas.

Este archivo solo hace cálculos: no sabe nada de la base de datos ni de las
pantallas. Recibe la lista de estados de un niño (día por día, del más antiguo
al más nuevo) y responde: cuánto faltó, de qué color está y qué alertas tiene.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from app import config as cfg

# Códigos de alerta
ALERTA_RACHA = "RACHA"
ALERTA_TENDENCIA = "TENDENCIA"
ALERTA_AMARILLO = "RIESGO_AMARILLO"
ALERTA_ROJO = "RIESGO_ROJO"

DESCRIPCION_ALERTA = {
    ALERTA_RACHA: f"{cfg.FALTAS_SEGUIDAS_ALERTA} o más faltas seguidas hasta hoy",
    ALERTA_TENDENCIA: (
        f"Va bien en el año, pero en los últimos {cfg.VENTANA_RECIENTE_DIAS} "
        f"días de clases faltó {cfg.UMBRAL_AMARILLO_PCT}% o más"
    ),
    ALERTA_AMARILLO: (
        f"Ha faltado entre {cfg.UMBRAL_AMARILLO_PCT}% y {cfg.UMBRAL_ROJO_PCT}% "
        "de los días"
    ),
    ALERTA_ROJO: f"Ha faltado {cfg.UMBRAL_ROJO_PCT}% o más de los días",
}


@dataclass(frozen=True)
class ResultadoNino:
    dias_lectivos: int
    ausencias: int
    pct_inasistencia: float      # 0 a 100, sobre todo lo que va del año
    nivel: str                   # verde / amarillo / rojo / sin_datos
    racha_actual: int            # faltas seguidas hasta el último día
    pct_reciente: float          # 0 a 100, sobre los últimos días
    alertas: tuple[str, ...]

    @property
    def tiene_alerta(self) -> bool:
        return len(self.alertas) > 0


@dataclass(frozen=True)
class ResumenJardin:
    ninos: int
    asistencia_promedio_pct: Optional[float]  # None si no hay datos
    ninos_verde: int
    ninos_amarillo: int
    ninos_rojo: int
    ninos_sin_datos: int
    pct_ninos_rojo: float        # sobre los niños que ya tienen semáforo
    pct_ninos_en_riesgo: float   # amarillo + rojo, sobre los que tienen semáforo
    ninos_con_alerta: int


def porcentaje_inasistencia(ausencias: int, dias_lectivos: int) -> float:
    """Porcentaje de días faltados (0 a 100). Sin días de clases, es 0."""
    if dias_lectivos <= 0:
        return 0.0
    return ausencias / dias_lectivos * 100


def calcular_nivel(ausencias: int, dias_lectivos: int) -> str:
    """Color del semáforo según las faltas y los días de clases.

    Se compara con enteros (ausencias * 100 >= umbral * días) para que 2 faltas
    en 20 días sea exactamente 10% y caiga en amarillo, sin errores de decimales.
    """
    if dias_lectivos < cfg.MIN_DIAS_LECTIVOS:
        return cfg.SIN_DATOS
    if ausencias * 100 >= cfg.UMBRAL_ROJO_PCT * dias_lectivos:
        return cfg.ROJO
    if ausencias * 100 >= cfg.UMBRAL_AMARILLO_PCT * dias_lectivos:
        return cfg.AMARILLO
    return cfg.VERDE


def _validar_estados(estados: Sequence[str]) -> None:
    for estado in estados:
        if estado not in cfg.ESTADOS:
            raise ValueError(f"Estado desconocido: {estado!r}. Usa {cfg.ESTADOS}.")


def _contar_ausencias(estados: Sequence[str]) -> int:
    return sum(1 for e in estados if e == cfg.AUSENTE)


def racha_actual(estados: Sequence[str]) -> int:
    """Cuántas faltas seguidas lleva el niño hasta el último día registrado."""
    racha = 0
    for estado in reversed(estados):
        if estado == cfg.AUSENTE:
            racha += 1
        else:
            break
    return racha


def evaluar_nino(estados: Sequence[str]) -> ResultadoNino:
    """Evalúa a un niño a partir de sus estados diarios (del más antiguo al más nuevo)."""
    _validar_estados(estados)

    dias = len(estados)
    ausencias = _contar_ausencias(estados)
    nivel = calcular_nivel(ausencias, dias)
    racha = racha_actual(estados)

    reciente = estados[-cfg.VENTANA_RECIENTE_DIAS:]
    ausencias_recientes = _contar_ausencias(reciente)
    pct_reciente = porcentaje_inasistencia(ausencias_recientes, len(reciente))

    alertas: list[str] = []
    if racha >= cfg.FALTAS_SEGUIDAS_ALERTA:
        alertas.append(ALERTA_RACHA)
    if nivel == cfg.ROJO:
        alertas.append(ALERTA_ROJO)
    elif nivel == cfg.AMARILLO:
        alertas.append(ALERTA_AMARILLO)
    elif nivel == cfg.VERDE:
        # Alerta temprana: todavía está verde en el año, pero viene empeorando.
        if ausencias_recientes * 100 >= cfg.UMBRAL_AMARILLO_PCT * len(reciente):
            alertas.append(ALERTA_TENDENCIA)

    return ResultadoNino(
        dias_lectivos=dias,
        ausencias=ausencias,
        pct_inasistencia=porcentaje_inasistencia(ausencias, dias),
        nivel=nivel,
        racha_actual=racha,
        pct_reciente=pct_reciente,
        alertas=tuple(alertas),
    )


def resumen_jardin(resultados: Iterable[ResultadoNino]) -> ResumenJardin:
    """Junta a los niños de un jardín.

    Muestra a la vez el promedio de asistencia (lo que se mira hoy) y cuántos
    niños están en rojo (lo que el promedio esconde).
    """
    resultados = list(resultados)
    total_dias = sum(r.dias_lectivos for r in resultados)
    total_ausencias = sum(r.ausencias for r in resultados)

    if total_dias > 0:
        asistencia = 100 - porcentaje_inasistencia(total_ausencias, total_dias)
    else:
        asistencia = None

    verde = sum(1 for r in resultados if r.nivel == cfg.VERDE)
    amarillo = sum(1 for r in resultados if r.nivel == cfg.AMARILLO)
    rojo = sum(1 for r in resultados if r.nivel == cfg.ROJO)
    sin_datos = sum(1 for r in resultados if r.nivel == cfg.SIN_DATOS)

    evaluados = verde + amarillo + rojo
    pct_rojo = rojo / evaluados * 100 if evaluados else 0.0
    pct_riesgo = (amarillo + rojo) / evaluados * 100 if evaluados else 0.0

    return ResumenJardin(
        ninos=len(resultados),
        asistencia_promedio_pct=asistencia,
        ninos_verde=verde,
        ninos_amarillo=amarillo,
        ninos_rojo=rojo,
        ninos_sin_datos=sin_datos,
        pct_ninos_rojo=pct_rojo,
        pct_ninos_en_riesgo=pct_riesgo,
        ninos_con_alerta=sum(1 for r in resultados if r.tiene_alerta),
    )
