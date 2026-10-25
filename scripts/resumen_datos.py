"""Muestra el semáforo de cada jardín a partir de la base de datos.

Sirve para comprobar que los datos ficticios funcionan y para ver con claridad
la brecha del proyecto: el promedio de asistencia de un jardín puede verse bien
y, aun así, tener niños en rojo escondidos.

Uso:

    python scripts/resumen_datos.py
    python scripts/resumen_datos.py --bd data/asistencia.db
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as cfg  # noqa: E402
from app import db  # noqa: E402
from app import rules  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Semáforo de asistencia por jardín.")
    parser.add_argument("--bd", default=str(cfg.RUTA_BD), help="archivo de la base de datos")
    args = parser.parse_args(argv)

    if args.bd != ":memory:" and not Path(args.bd).exists():
        print(f"No encuentro la base de datos en {args.bd}.")
        print("Primero ejecuta: python scripts/generar_datos.py")
        return 1

    conn = db.conectar(args.bd)
    try:
        print(cfg.AVISO_DATOS_FICTICIOS)
        print()
        encabezado = (
            f"{'Jardín':<38} {'Asist. prom.':>12} {'Verde':>6} {'Amar.':>6} "
            f"{'Rojo':>5} {'% rojo':>7} {'Con alerta':>11}"
        )
        print(encabezado)
        print("-" * len(encabezado))

        alertas_totales: Counter[str] = Counter()
        for jardin in db.listar_jardines(conn):
            resultados = [
                rules.evaluar_nino(estados)
                for estados in db.estados_por_nino(conn, jardin["id"]).values()
            ]
            for r in resultados:
                alertas_totales.update(r.alertas)
            resumen = rules.resumen_jardin(resultados)
            promedio = (
                f"{resumen.asistencia_promedio_pct:.1f}%"
                if resumen.asistencia_promedio_pct is not None
                else "-"
            )
            print(
                f"{jardin['nombre']:<38} {promedio:>12} {resumen.ninos_verde:>6} "
                f"{resumen.ninos_amarillo:>6} {resumen.ninos_rojo:>5} "
                f"{resumen.pct_ninos_rojo:>6.1f}% {resumen.ninos_con_alerta:>11}"
            )

        print("\nAlertas activas en total:")
        for codigo, cantidad in sorted(alertas_totales.items()):
            print(f"  {codigo:<16} {cantidad:>4}  {rules.DESCRIPCION_ALERTA[codigo]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
