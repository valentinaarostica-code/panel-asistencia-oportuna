"""Qué se guarda en el sistema.

Cada clase es una "ficha". Los niños no tienen nombre: solo un código
seudónimo (por ejemplo J01-N007), para no manejar datos personales.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app import config as cfg


@dataclass
class Jardin:
    nombre: str
    comuna: str
    region: str
    id: Optional[int] = None


@dataclass
class Sala:
    jardin_id: int
    nivel: str
    id: Optional[int] = None


@dataclass
class Nino:
    codigo: str          # seudónimo, sin nombre ni RUT
    sala_id: int
    id: Optional[int] = None


@dataclass
class Asistencia:
    """Qué pasó con un niño en un día.

    Reglas de calidad de datos (se validan al crear el registro):
    - el estado solo puede ser "presente" o "ausente";
    - un niño presente no lleva motivo;
    - una ausencia sin motivo se guarda como "Sin información";
    - el motivo debe ser uno de la lista oficial.
    """

    nino_id: int
    fecha: date
    estado: str
    motivo: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.fecha, date):
            raise ValueError("La fecha debe ser de tipo date.")
        if self.estado not in cfg.ESTADOS:
            raise ValueError(f"Estado inválido: {self.estado!r}. Usa {cfg.ESTADOS}.")
        if self.estado == cfg.PRESENTE and self.motivo is not None:
            raise ValueError("Un niño presente no lleva motivo de ausencia.")
        if self.estado == cfg.AUSENTE and self.motivo is None:
            self.motivo = cfg.SIN_INFORMACION
        if self.motivo is not None and self.motivo not in cfg.MOTIVOS:
            raise ValueError(f"Motivo inválido: {self.motivo!r}. Usa {cfg.MOTIVOS}.")

    @property
    def informado_por_familia(self) -> bool:
        """True si la familia avisó el motivo de la ausencia."""
        return self.estado == cfg.AUSENTE and self.motivo != cfg.SIN_INFORMACION
