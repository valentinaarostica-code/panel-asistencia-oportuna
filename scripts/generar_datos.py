"""Generador de datos FICTICIOS para el Panel de Asistencia Oportuna.

Crea jardines, salas, niños (con código seudónimo) y la asistencia diaria de
cada niño, y los guarda en la base de datos.

Uso (desde la carpeta principal del proyecto):

    python scripts/generar_datos.py
    python scripts/generar_datos.py --jardines 5 --ninos-por-jardin 20
    python scripts/generar_datos.py --semilla 7

Con la misma semilla siempre salen exactamente los mismos datos, así que el
profesor y el equipo ven lo mismo.

Nada de esto es real: los nombres de los jardines, las comunas asignadas, los
niños y la asistencia son inventados con fines académicos.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Permite ejecutar este archivo directamente con "python scripts/generar_datos.py".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as cfg  # noqa: E402
from app import db  # noqa: E402
from app.models import Asistencia, Jardin, Nino, Sala  # noqa: E402

INICIO_DEFECTO = date(2026, 3, 2)   # inicio de clases (lunes)
FIN_DEFECTO = date(2026, 10, 23)    # viernes antes de la entrega

# Feriados aproximados de 2026, solo para dar realismo (no son un calendario oficial).
FERIADOS_APROXIMADOS = frozenset(
    {
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 5, 21),
        date(2026, 6, 29),
        date(2026, 7, 16),
        date(2026, 9, 18),
        date(2026, 10, 12),
    }
)

NOMBRES_JARDIN = (
    "Rayito de Sol", "Semillitas", "Pequeños Pasos", "Arco Iris",
    "Mis Primeros Amigos", "Luna Nueva", "Colibrí", "Manitos Alegres",
    "Caracolito", "Estrella del Norte", "Pehuén", "Pintitas de Colores",
)

UBICACIONES = (  # (comuna, región)
    ("Antofagasta", "Antofagasta"), ("Calama", "Antofagasta"),
    ("Tocopilla", "Antofagasta"), ("Mejillones", "Antofagasta"),
    ("Valparaíso", "Valparaíso"), ("Viña del Mar", "Valparaíso"),
    ("Puente Alto", "Metropolitana"), ("Recoleta", "Metropolitana"),
    ("La Pintana", "Metropolitana"), ("Concepción", "Biobío"),
    ("Temuco", "La Araucanía"), ("Puerto Montt", "Los Lagos"),
)

# Escenarios para los primeros jardines: sirven para probar y mostrar la demo.
ESCENARIOS_FIJOS = ("mejora", "cae", "promedio_oculta")
DESCRIPCION_ESCENARIO = {
    "mejora": "las ausencias bajan a lo largo del año",
    "cae": "las ausencias suben a lo largo del año",
    "promedio_oculta": "buen promedio, pero con varios niños en rojo escondidos",
    "estable": "comportamiento parejo durante el año",
}

# Probabilidad diaria de faltar según el perfil del niño: (mínimo, máximo).
PERFILES = {
    "muy_regular": (0.01, 0.03),
    "regular": (0.04, 0.08),
    "moderado": (0.10, 0.18),
    "critico": (0.22, 0.35),
    "racha": (0.02, 0.05),     # base baja, pero con rachas de faltas seguidas
    "empeora": (0.02, 0.04),   # va bien y se deteriora hacia el final
}
PESOS_PERFIL = {"regular": 40, "moderado": 28, "critico": 15, "racha": 9, "empeora": 8}

MESES_INVIERNO = frozenset({6, 7, 8})
FACTOR_INVIERNO = 1.4  # en invierno se falta más (enfermedades respiratorias)

PESOS_MOTIVO = {
    cfg.SALUD: 42, cfg.TRASLADO: 14, cfg.FAMILIAR: 17, cfg.CLIMA: 2,
    cfg.SIN_INFORMACION: 25,
}
PESOS_MOTIVO_INVIERNO = {
    cfg.SALUD: 52, cfg.TRASLADO: 8, cfg.FAMILIAR: 10, cfg.CLIMA: 10,
    cfg.SIN_INFORMACION: 20,
}


@dataclass(frozen=True)
class JardinGenerado:
    id: int
    nombre: str
    escenario: str


def dias_lectivos(inicio: date, fin: date) -> list[date]:
    """Lunes a viernes entre dos fechas (inclusive), sin los feriados aproximados."""
    if inicio > fin:
        raise ValueError("La fecha de inicio debe ser anterior o igual a la de fin.")
    dias = []
    actual = inicio
    while actual <= fin:
        if actual.weekday() < 5 and actual not in FERIADOS_APROXIMADOS:
            dias.append(actual)
        actual += timedelta(days=1)
    return dias


def _multiplicador_jardin(escenario: str, base: float, t: float) -> float:
    """Cuánto se falta en el jardín según el escenario. t va de 0 (inicio) a 1 (fin)."""
    if escenario == "mejora":
        return 1.4 + (0.5 - 1.4) * t
    if escenario == "cae":
        return 0.6 + (1.6 - 0.6) * t
    return base


def asignar_perfiles(rng: random.Random, cantidad: int, escenario: str) -> list[str]:
    """Reparte los perfiles de los niños de un jardín."""
    if escenario == "promedio_oculta":
        criticos = min(4, cantidad)
        perfiles = ["critico"] * criticos + ["muy_regular"] * (cantidad - criticos)
        rng.shuffle(perfiles)
        return perfiles
    return rng.choices(
        list(PESOS_PERFIL), weights=list(PESOS_PERFIL.values()), k=cantidad
    )


def simular_ausencias(
    rng: random.Random,
    perfil: str,
    fechas: list[date],
    escenario: str,
    base_jardin: float,
) -> list[bool]:
    """Devuelve una lista con True en los días en que el niño estuvo ausente."""
    n = len(fechas)
    minimo, maximo = PERFILES[perfil]
    p_base = rng.uniform(minimo, maximo)
    p_final = rng.uniform(0.30, 0.45) if perfil == "empeora" else p_base
    corte = int(n * 0.70)

    ausente = []
    for i, fecha in enumerate(fechas):
        t = i / max(n - 1, 1)
        p = p_final if (perfil == "empeora" and i >= corte) else p_base
        p *= _multiplicador_jardin(escenario, base_jardin, t)
        if fecha.month in MESES_INVIERNO:
            p *= FACTOR_INVIERNO
        ausente.append(rng.random() < min(p, 0.9))

    if perfil == "racha":
        for _ in range(rng.randint(1, 2)):
            largo = min(rng.randint(3, 7), n)
            inicio = rng.randrange(0, max(n - largo + 1, 1))
            for j in range(largo):
                ausente[inicio + j] = True
        if rng.random() < 0.35:  # racha que sigue activa en el último día
            largo = min(rng.randint(3, 5), n)
            for j in range(1, largo + 1):
                ausente[-j] = True

    return ausente


def elegir_motivos(
    rng: random.Random, fechas: list[date], ausente: list[bool]
) -> list[str | None]:
    """Motivo de cada ausencia. En una racha, casi siempre se repite el mismo motivo."""
    motivos: list[str | None] = [None] * len(fechas)
    anterior: str | None = None
    for i, (fecha, falto) in enumerate(zip(fechas, ausente)):
        if not falto:
            anterior = None
            continue
        if anterior is not None and rng.random() < 0.8:
            motivo = anterior
        else:
            pesos = PESOS_MOTIVO_INVIERNO if fecha.month in MESES_INVIERNO else PESOS_MOTIVO
            motivo = rng.choices(list(pesos), weights=list(pesos.values()))[0]
        motivos[i] = motivo
        anterior = motivo
    return motivos


def generar(
    conn,
    semilla: int = 2026,
    n_jardines: int = 12,
    ninos_por_jardin: int = 25,
    inicio: date = INICIO_DEFECTO,
    fin: date = FIN_DEFECTO,
) -> list[JardinGenerado]:
    """Borra la base y la llena con datos ficticios. Devuelve un resumen de los jardines."""
    if not 1 <= n_jardines <= len(NOMBRES_JARDIN):
        raise ValueError(f"Los jardines deben ser entre 1 y {len(NOMBRES_JARDIN)}.")
    if ninos_por_jardin < 1:
        raise ValueError("Debe haber al menos 1 niño por jardín.")
    fechas = dias_lectivos(inicio, fin)
    if not fechas:
        raise ValueError("No hay días de clases entre esas fechas.")

    rng = random.Random(semilla)
    db.reiniciar_esquema(conn)
    generados: list[JardinGenerado] = []

    with conn:
        for i in range(n_jardines):
            comuna, region = UBICACIONES[i]
            jardin = Jardin(
                nombre=f"Jardín {NOMBRES_JARDIN[i]} (ficticio)",
                comuna=comuna,
                region=region,
            )
            db.insertar_jardin(conn, jardin)

            escenario = ESCENARIOS_FIJOS[i] if i < len(ESCENARIOS_FIJOS) else "estable"
            base_jardin = rng.uniform(0.8, 1.3) if escenario == "estable" else 1.0
            generados.append(JardinGenerado(jardin.id, jardin.nombre, escenario))

            salas = []
            for nivel in cfg.NIVELES_SALA:
                sala = Sala(jardin_id=jardin.id, nivel=nivel)
                db.insertar_sala(conn, sala)
                salas.append(sala)

            perfiles = asignar_perfiles(rng, ninos_por_jardin, escenario)
            for k, perfil in enumerate(perfiles):
                nino = Nino(codigo=f"J{i + 1:02d}-N{k + 1:03d}", sala_id=salas[k % len(salas)].id)
                db.insertar_nino(conn, nino)

                ausente = simular_ausencias(rng, perfil, fechas, escenario, base_jardin)
                motivos = elegir_motivos(rng, fechas, ausente)
                db.insertar_asistencias(
                    conn,
                    (
                        Asistencia(
                            nino_id=nino.id,
                            fecha=fecha,
                            estado=cfg.AUSENTE if falto else cfg.PRESENTE,
                            motivo=motivo,
                        )
                        for fecha, falto, motivo in zip(fechas, ausente, motivos)
                    ),
                )

    return generados


def _leer_argumentos(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera datos ficticios de asistencia para el prototipo."
    )
    parser.add_argument("--semilla", type=int, default=2026,
                        help="misma semilla = mismos datos (por defecto 2026)")
    parser.add_argument("--jardines", type=int, default=12,
                        help=f"cantidad de jardines, de 1 a {len(NOMBRES_JARDIN)} (por defecto 12)")
    parser.add_argument("--ninos-por-jardin", type=int, default=25,
                        help="niños en cada jardín (por defecto 25)")
    parser.add_argument("--inicio", type=date.fromisoformat, default=INICIO_DEFECTO,
                        help="primer día, formato AAAA-MM-DD (por defecto 2026-03-02)")
    parser.add_argument("--fin", type=date.fromisoformat, default=FIN_DEFECTO,
                        help="último día, formato AAAA-MM-DD (por defecto 2026-10-23)")
    parser.add_argument("--salida", default=str(cfg.RUTA_BD),
                        help="archivo de la base de datos (por defecto data/asistencia.db)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _leer_argumentos(argv)
    conn = db.conectar(args.salida)
    try:
        generados = generar(
            conn,
            semilla=args.semilla,
            n_jardines=args.jardines,
            ninos_por_jardin=args.ninos_por_jardin,
            inicio=args.inicio,
            fin=args.fin,
        )
        n_dias = len(dias_lectivos(args.inicio, args.fin))
        print(cfg.AVISO_DATOS_FICTICIOS)
        print(f"Base creada en: {args.salida}")
        print(
            f"  Jardines: {db.contar(conn, 'jardin')} | "
            f"Salas: {db.contar(conn, 'sala')} | "
            f"Niños: {db.contar(conn, 'nino')} | "
            f"Días de clases: {n_dias} | "
            f"Registros de asistencia: {db.contar(conn, 'asistencia')}"
        )
        print("\nEscenarios de demostración:")
        for g in generados:
            print(f"  {g.nombre:<38} {g.escenario:<16} {DESCRIPCION_ESCENARIO[g.escenario]}")
        print("\nPara ver el semáforo por jardín: python scripts/resumen_datos.py")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
