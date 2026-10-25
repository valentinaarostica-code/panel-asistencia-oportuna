"""Conexión con la base de datos (SQLite, que viene incluida con Python).

Aquí se crean las tablas, se guardan los registros y se hacen las consultas.
El resto del programa no escribe SQL: usa estas funciones.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Union

from app import config as cfg
from app.models import Asistencia, Jardin, Nino, Sala

_ESTADOS_SQL = ", ".join(f"'{e}'" for e in cfg.ESTADOS)

ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS jardin (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE,
    comuna  TEXT NOT NULL,
    region  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sala (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    jardin_id  INTEGER NOT NULL REFERENCES jardin(id),
    nivel      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nino (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo   TEXT NOT NULL UNIQUE,
    sala_id  INTEGER NOT NULL REFERENCES sala(id)
);

CREATE TABLE IF NOT EXISTS asistencia (
    nino_id                INTEGER NOT NULL REFERENCES nino(id),
    fecha                  TEXT    NOT NULL,   -- formato AAAA-MM-DD
    estado                 TEXT    NOT NULL CHECK (estado IN ({_ESTADOS_SQL})),
    motivo                 TEXT,
    informado_por_familia  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (nino_id, fecha)
);

CREATE INDEX IF NOT EXISTS idx_asistencia_fecha ON asistencia(fecha);
"""

_TABLAS = ("jardin", "sala", "nino", "asistencia")


def conectar(ruta: Union[str, Path, None] = None) -> sqlite3.Connection:
    """Abre la base de datos. Usa ':memory:' para una base temporal (pruebas)."""
    destino = str(ruta) if ruta is not None else str(cfg.RUTA_BD)
    if destino != ":memory:":
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(destino)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def crear_esquema(conn: sqlite3.Connection) -> None:
    """Crea las tablas si no existen."""
    conn.executescript(ESQUEMA)


def reiniciar_esquema(conn: sqlite3.Connection) -> None:
    """Borra todo y vuelve a crear las tablas vacías."""
    conn.executescript(
        "DROP TABLE IF EXISTS asistencia;"
        "DROP TABLE IF EXISTS nino;"
        "DROP TABLE IF EXISTS sala;"
        "DROP TABLE IF EXISTS jardin;"
    )
    crear_esquema(conn)


# --- Guardar -----------------------------------------------------------------
# Estas funciones no hacen commit: quien las llama decide cuándo confirmar
# (por ejemplo con "with conn:").

def insertar_jardin(conn: sqlite3.Connection, jardin: Jardin) -> int:
    cur = conn.execute(
        "INSERT INTO jardin (nombre, comuna, region) VALUES (?, ?, ?)",
        (jardin.nombre, jardin.comuna, jardin.region),
    )
    jardin.id = cur.lastrowid
    return jardin.id


def insertar_sala(conn: sqlite3.Connection, sala: Sala) -> int:
    cur = conn.execute(
        "INSERT INTO sala (jardin_id, nivel) VALUES (?, ?)",
        (sala.jardin_id, sala.nivel),
    )
    sala.id = cur.lastrowid
    return sala.id


def insertar_nino(conn: sqlite3.Connection, nino: Nino) -> int:
    cur = conn.execute(
        "INSERT INTO nino (codigo, sala_id) VALUES (?, ?)",
        (nino.codigo, nino.sala_id),
    )
    nino.id = cur.lastrowid
    return nino.id


def insertar_asistencias(
    conn: sqlite3.Connection, registros: Iterable[Asistencia]
) -> None:
    conn.executemany(
        "INSERT INTO asistencia (nino_id, fecha, estado, motivo, informado_por_familia) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            (
                r.nino_id,
                r.fecha.isoformat(),
                r.estado,
                r.motivo,
                int(r.informado_por_familia),
            )
            for r in registros
        ),
    )


def guardar_asistencias(
    conn: sqlite3.Connection, registros: Iterable[Asistencia]
) -> None:
    """Guarda la asistencia; si el niño ya tiene registro ese día, lo actualiza."""
    conn.executemany(
        "INSERT INTO asistencia (nino_id, fecha, estado, motivo, informado_por_familia) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (nino_id, fecha) DO UPDATE SET "
        "estado = excluded.estado, motivo = excluded.motivo, "
        "informado_por_familia = excluded.informado_por_familia",
        (
            (
                r.nino_id,
                r.fecha.isoformat(),
                r.estado,
                r.motivo,
                int(r.informado_por_familia),
            )
            for r in registros
        ),
    )


# --- Consultar ---------------------------------------------------------------

def contar(conn: sqlite3.Connection, tabla: str) -> int:
    if tabla not in _TABLAS:
        raise ValueError(f"Tabla desconocida: {tabla!r}")
    return conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


def listar_jardines(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, nombre, comuna, region FROM jardin ORDER BY id"
    ).fetchall()


def ninos_de_jardin(conn: sqlite3.Connection, jardin_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT n.id, n.codigo, s.nivel AS sala "
        "FROM nino n JOIN sala s ON s.id = n.sala_id "
        "WHERE s.jardin_id = ? ORDER BY n.id",
        (jardin_id,),
    ).fetchall()


def estados_por_nino(
    conn: sqlite3.Connection, jardin_id: Optional[int] = None
) -> dict[int, list[str]]:
    """Devuelve {id_del_niño: [estados día por día, del más antiguo al más nuevo]}."""
    filas = conn.execute(
        "SELECT a.nino_id, a.estado "
        "FROM asistencia a "
        "JOIN nino n ON n.id = a.nino_id "
        "JOIN sala s ON s.id = n.sala_id "
        "WHERE (? IS NULL OR s.jardin_id = ?) "
        "ORDER BY a.nino_id, a.fecha",
        (jardin_id, jardin_id),
    ).fetchall()
    resultado: dict[int, list[str]] = {}
    for fila in filas:
        resultado.setdefault(fila["nino_id"], []).append(fila["estado"])
    return resultado


def listar_salas(conn: sqlite3.Connection, jardin_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, jardin_id, nivel FROM sala WHERE jardin_id = ? ORDER BY id",
        (jardin_id,),
    ).fetchall()


def ninos_de_sala(conn: sqlite3.Connection, sala_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, codigo FROM nino WHERE sala_id = ? ORDER BY codigo",
        (sala_id,),
    ).fetchall()


def ultima_fecha_con_datos(
    conn: sqlite3.Connection, jardin_id: Optional[int] = None
) -> Optional[date]:
    """Último día con asistencia registrada (en un jardín o en todos). None si no hay."""
    valor = conn.execute(
        "SELECT MAX(a.fecha) "
        "FROM asistencia a "
        "JOIN nino n ON n.id = a.nino_id "
        "JOIN sala s ON s.id = n.sala_id "
        "WHERE (? IS NULL OR s.jardin_id = ?)",
        (jardin_id, jardin_id),
    ).fetchone()[0]
    return date.fromisoformat(valor) if valor else None


def asistencias_del_dia(
    conn: sqlite3.Connection, sala_id: int, fecha: date
) -> dict[int, sqlite3.Row]:
    """Devuelve {id_del_niño: registro} con lo ya guardado de una sala en un día."""
    filas = conn.execute(
        "SELECT a.nino_id, a.estado, a.motivo "
        "FROM asistencia a JOIN nino n ON n.id = a.nino_id "
        "WHERE n.sala_id = ? AND a.fecha = ?",
        (sala_id, fecha.isoformat()),
    ).fetchall()
    return {fila["nino_id"]: fila for fila in filas}
