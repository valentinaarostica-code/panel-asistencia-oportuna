"""Base de demostración compartida por las pruebas de las pantallas.

Se genera una sola vez en memoria con la semilla fija 2026 (la misma de la
demo) y se copia a un archivo temporal, porque la app abre la base por ruta.
Las pruebas solo la leen: no la modifican.
"""

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app import db
from scripts import generar_datos as gen

SEMILLA = 2026

_carpeta = None
_ruta = None
_memoria = None


def base_demo() -> tuple[Path, sqlite3.Connection]:
    """Devuelve (ruta del archivo para la app, conexión en memoria para comparar)."""
    global _carpeta, _ruta, _memoria
    if _memoria is None:
        _memoria = db.conectar(":memory:")
        gen.generar(_memoria, semilla=SEMILLA)
        # Se borra sola al terminar las pruebas.
        _carpeta = tempfile.TemporaryDirectory()
        _ruta = Path(_carpeta.name) / "demo.db"
        with closing(db.conectar(_ruta)) as archivo:
            _memoria.backup(archivo)
    return _ruta, _memoria


def copia_demo(destino: Path) -> Path:
    """Copia la base de demostración a otro archivo, para pruebas que sí la modifican."""
    _, memoria = base_demo()
    with closing(db.conectar(destino)) as archivo:
        memoria.backup(archivo)
    return destino
