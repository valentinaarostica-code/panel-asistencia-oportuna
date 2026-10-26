"""Crea casos de seguimiento de EJEMPLO para la demo (datos ficticios).

Se corre después de generar_datos.py:

    python scripts/generar_datos.py
    python scripts/sembrar_casos.py
    python scripts/sembrar_casos.py --reiniciar   # borra los casos y los vuelve a crear

Usa los niños en rojo del jardín "Pequeños Pasos (ficticio)" y deja:

- un caso con una revisión que MEJORA;
- un caso con 2 revisiones SIN MEJORA (sale "Escalar");
- un caso recién abierto, sin revisiones;
- y al menos un niño en rojo SIN caso, para mostrar el botón "Abrir caso".

Las fechas no se eligen a ciegas: el script busca, en los datos generados, fechas
de apertura y de revisión (separadas por cerca de un mes, en meses anteriores)
que den cada resultado. Así sigue funcionando aunque cambie la semilla. Si no
encuentra fechas que sirvan, termina con un mensaje claro.

Si ya hay casos guardados, no hace nada (para no borrar los creados a mano),
salvo que se use --reiniciar.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Permite ejecutar este archivo directamente con "python scripts/sembrar_casos.py".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as cfg  # noqa: E402
from app import db  # noqa: E402
from app import seguimiento as seg  # noqa: E402

NOMBRE_JARDIN = "Pequeños Pasos"
DIAS_ENTRE_REVISIONES = 21          # unos 21 días de clases: cerca de un mes
DESDE_APERTURA = date(2026, 5, 1)   # buscar aperturas desde mayo...

ACCIONES_EJEMPLO = (
    (("Llamado a la familia",), "Se acordó con la familia avisar las ausencias."),
    (("Reunión con la familia", "Apoyo de traslado o transporte"), "Se coordinó apoyo para el traslado."),
    (("Visita al hogar", "Derivación a red de apoyo"), "Se derivó a la red de apoyo local."),
)


class SinFechasQueSirvan(RuntimeError):
    pass


def _dias_de_clases(conn: sqlite3.Connection) -> list[date]:
    filas = conn.execute("SELECT DISTINCT fecha FROM asistencia ORDER BY fecha").fetchall()
    return [date.fromisoformat(f[0]) for f in filas]


def _inicio_mes(fecha: date) -> date:
    return fecha.replace(day=1)


def _buscar(
    conn: sqlite3.Connection, nino_id: int, dias: list[date], resultados_buscados: list[str]
) -> Optional[list[date]]:
    """Busca [apertura, revisión 1, revisión 2, ...] que den esos resultados.

    Todas las fechas quedan en meses anteriores al último mes con datos y cada
    revisión cae en un mes distinto. Se prefiere la apertura más reciente.
    """
    limite = _inicio_mes(dias[-1])  # las revisiones van en meses anteriores
    pct = {}

    def reciente(i):
        if i not in pct:
            pct[i] = seg.evaluar_al(conn, nino_id, dias[i])
        return pct[i]

    saltos = len(resultados_buscados)
    for i in range(len(dias) - 1, -1, -1):
        if dias[i] < DESDE_APERTURA:
            break
        indices = [i + DIAS_ENTRE_REVISIONES * k for k in range(saltos + 1)]
        if indices[-1] >= len(dias) or dias[indices[-1]] >= limite:
            continue
        fechas = [dias[j] for j in indices]
        if len({(f.year, f.month) for f in fechas}) != len(fechas):
            continue  # cada revisión en un mes distinto
        if reciente(i).nivel != cfg.ROJO:
            continue
        pcts = [reciente(j).pct_reciente for j in indices]
        if seg.resultados_del_caso(pcts[0], pcts[1:]) == resultados_buscados:
            return fechas
    return None


def sembrar(conn: sqlite3.Connection, reiniciar: bool = False) -> list[dict]:
    """Crea los casos de ejemplo. Devuelve qué se creó (para mostrarlo o probarlo)."""
    if reiniciar:
        with conn:
            conn.execute("DELETE FROM revision")
            conn.execute("DELETE FROM caso")
    elif db.contar(conn, "caso") > 0:
        return []

    dias = _dias_de_clases(conn)
    if not dias:
        raise SinFechasQueSirvan("No hay asistencia. Primero ejecuta: python scripts/generar_datos.py")
    jardin = next((j for j in db.listar_jardines(conn) if NOMBRE_JARDIN in j["nombre"]), None)
    if jardin is None:
        raise SinFechasQueSirvan(f"No existe el jardín {NOMBRE_JARDIN!r} en la base.")

    en_rojo = [
        n for n in db.ninos_de_jardin(conn, jardin["id"])
        if seg.evaluar_al(conn, n["id"]).nivel == cfg.ROJO
    ]
    en_rojo.sort(key=lambda n: n["codigo"])
    if len(en_rojo) < 4:
        raise SinFechasQueSirvan(
            f"{jardin['nombre']} tiene {len(en_rojo)} niños en rojo; se necesitan al menos 4."
        )

    # (nombre del ejemplo, resultados que debe tener). El recién abierto va aparte.
    escenarios = [
        ("Escalar", [seg.SIN_MEJORA, seg.SIN_MEJORA]),
        ("Mejora", [seg.MEJORA]),
    ]
    plan = []
    libres = list(en_rojo)
    for nombre, buscados in escenarios:
        for nino in libres:
            fechas = _buscar(conn, nino["id"], dias, buscados)
            if fechas:
                plan.append((nombre, nino, fechas))
                libres.remove(nino)
                break
        else:
            raise SinFechasQueSirvan(
                f"No se encontraron fechas para el ejemplo {nombre!r} en {jardin['nombre']}."
            )
    # Recién abierto: el último día con datos. Queda al menos un niño en rojo sin caso.
    plan.append(("Recién abierto", libres.pop(0), [dias[-1]]))

    creados = []
    with conn:
        for nombre, nino, fechas in plan:
            caso_id = seg.abrir_caso(conn, nino["id"], fechas[0], hoy=dias[-1])
            for k, fecha in enumerate(fechas[1:]):
                acciones, observacion = ACCIONES_EJEMPLO[k % len(ACCIONES_EJEMPLO)]
                seg.registrar_revision(conn, caso_id, fecha, acciones, observacion, hoy=dias[-1])
            resumen = seg.resumen_caso(conn, db.obtener_caso(conn, caso_id))
            creados.append(
                {
                    "ejemplo": nombre,
                    "codigo": nino["codigo"],
                    "caso_id": caso_id,
                    "fechas": fechas,
                    "pcts": [resumen["caso"]["pct_reciente_apertura"]]
                    + [r["pct_reciente"] for r in resumen["revisiones"]],
                    "resultados": resumen["resultados"],
                    "estado": resumen["estado"],
                }
            )
    return creados


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crea casos de seguimiento de ejemplo (ficticios).")
    parser.add_argument("--bd", default=str(cfg.RUTA_BD), help="archivo de la base de datos")
    parser.add_argument("--reiniciar", action="store_true",
                        help="borra TODOS los casos y revisiones y crea los ejemplos de nuevo")
    args = parser.parse_args(argv)

    conn = db.conectar(args.bd)
    try:
        db.crear_esquema(conn)
        try:
            creados = sembrar(conn, reiniciar=args.reiniciar)
        except (SinFechasQueSirvan, seg.ErrorSeguimiento) as error:
            print(f"No se pudieron crear los casos: {error}", file=sys.stderr)
            return 1
        print(cfg.AVISO_DATOS_FICTICIOS)
        if not creados:
            print(f"Ya hay {db.contar(conn, 'caso')} casos guardados: no se cambió nada.")
            print("Usa --reiniciar para borrarlos y crear los ejemplos de nuevo.")
            return 0
        for c in creados:
            fechas = " → ".join(f.strftime("%d-%m-%Y") for f in c["fechas"])
            pcts = " → ".join(f"{p:.1f}%".replace(".", ",") for p in c["pcts"])
            resultados = ", ".join(seg.ETIQUETA_RESULTADO[r] for r in c["resultados"]) or "sin revisiones"
            print(f"  {c['ejemplo']:<15} {c['codigo']}  fechas: {fechas}")
            print(f"  {'':<15} faltas recientes: {pcts}  ({resultados})"
                  f"  → {seg.ETIQUETA_ESTADO[c['estado']]}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
