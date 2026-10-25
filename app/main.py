"""Pantallas web del Panel de Asistencia Oportuna (FastAPI + Jinja2).

Por ahora hay una sola pantalla: el registro diario de asistencia de una sala.
Todavía no hay login: los roles se agregan después.

Para ejecutarla (desde la carpeta principal del proyecto):

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config as cfg
from app import db
from app.models import Asistencia
from app.rules import DESCRIPCION_ALERTA, evaluar_nino

CARPETA_APP = Path(__file__).resolve().parent

app = FastAPI(title=cfg.NOMBRE_SISTEMA)
app.mount("/static", StaticFiles(directory=CARPETA_APP / "static"), name="static")
plantillas = Jinja2Templates(directory=CARPETA_APP / "templates")

ETIQUETA_NIVEL = {
    cfg.VERDE: "Verde",
    cfg.AMARILLO: "Amarillo",
    cfg.ROJO: "Rojo",
    cfg.SIN_DATOS: "Sin datos",
}


def ruta_bd() -> Path:
    """Dónde está la base de datos. Las pruebas la reemplazan por una temporal."""
    return cfg.RUTA_BD


def _abrir(ruta: Path) -> sqlite3.Connection:
    conn = db.conectar(ruta)
    db.crear_esquema(conn)
    return conn


def _leer_fecha(texto: Optional[str]) -> Optional[date]:
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _leer_id(texto: Optional[str]) -> Optional[int]:
    try:
        return int(texto) if texto else None
    except ValueError:
        return None


def _formato_pct(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + "%"


def _elegir(conn: sqlite3.Connection, jardin_id, sala_id, fecha):
    """Completa la selección con valores por defecto válidos."""
    jardines = db.listar_jardines(conn)
    ids_jardin = [j["id"] for j in jardines]
    if jardin_id not in ids_jardin:
        jardin_id = ids_jardin[0] if ids_jardin else None

    salas = db.listar_salas(conn, jardin_id) if jardin_id is not None else []
    ids_sala = [s["id"] for s in salas]
    if sala_id not in ids_sala:
        sala_id = ids_sala[0] if ids_sala else None

    if fecha is None:
        fecha = db.ultima_fecha_con_datos(conn, jardin_id) or date.today()
    return jardines, jardin_id, salas, sala_id, fecha


def _filas(
    conn: sqlite3.Connection,
    jardin_id: Optional[int],
    sala_id: Optional[int],
    fecha: date,
    valores: Optional[Mapping[str, str]] = None,
) -> list[dict]:
    """Un renglón por niño: lo registrado ese día y su semáforo con todo su historial."""
    if sala_id is None:
        return []
    guardados = db.asistencias_del_dia(conn, sala_id, fecha)
    historial = db.estados_por_nino(conn, jardin_id)
    filas = []
    for nino in db.ninos_de_sala(conn, sala_id):
        guardado = guardados.get(nino["id"])
        if valores is not None:
            # Se vuelve a mostrar lo que se envió, para no perderlo si hubo un error.
            estado = valores.get(f"estado_{nino['id']}", cfg.PRESENTE)
            motivo = valores.get(f"motivo_{nino['id']}") or cfg.SIN_INFORMACION
        elif guardado is not None:
            estado = guardado["estado"]
            motivo = guardado["motivo"] or cfg.SIN_INFORMACION
        else:
            estado, motivo = cfg.PRESENTE, cfg.SIN_INFORMACION

        resultado = evaluar_nino(historial.get(nino["id"], []))
        filas.append(
            {
                "id": nino["id"],
                "codigo": nino["codigo"],
                "estado": estado,
                "motivo": motivo,
                "registrado": guardado is not None,
                "nivel": resultado.nivel,
                "etiqueta": ETIQUETA_NIVEL[resultado.nivel],
                "pct": _formato_pct(resultado.pct_inasistencia),
                "ausencias": resultado.ausencias,
                "dias": resultado.dias_lectivos,
                "alertas": [DESCRIPCION_ALERTA[a] for a in resultado.alertas],
            }
        )
    return filas


def _pantalla(
    request: Request,
    conn: sqlite3.Connection,
    jardin_id=None,
    sala_id=None,
    fecha=None,
    valores=None,
    errores=(),
    guardados=None,
    status_code=200,
):
    jardines, jardin_id, salas, sala_id, fecha = _elegir(conn, jardin_id, sala_id, fecha)
    contexto = {
        "nombre_sistema": cfg.NOMBRE_SISTEMA,
        "aviso": cfg.AVISO_DATOS_FICTICIOS,
        "jardines": jardines,
        "salas": salas,
        "jardin_id": jardin_id,
        "sala_id": sala_id,
        "fecha": fecha,
        "hoy": date.today(),
        "filas": _filas(conn, jardin_id, sala_id, fecha, valores),
        "presente": cfg.PRESENTE,
        "ausente": cfg.AUSENTE,
        "motivos": cfg.MOTIVOS,
        "min_dias": cfg.MIN_DIAS_LECTIVOS,
        "errores": list(errores),
        "guardados": guardados,
    }
    return plantillas.TemplateResponse(
        request, "registro.html", contexto, status_code=status_code
    )


@app.get("/", response_class=HTMLResponse)
def registro(
    request: Request,
    jardin_id: Optional[str] = None,
    sala_id: Optional[str] = None,
    fecha: Optional[str] = None,
    guardado: Optional[str] = None,
    ruta: Path = Depends(ruta_bd),
):
    errores = []
    fecha_elegida = _leer_fecha(fecha)
    if fecha and fecha_elegida is None:
        errores.append(f"La fecha {fecha!r} no es válida; se muestra el último día con datos.")
    with closing(_abrir(ruta)) as conn:
        return _pantalla(
            request,
            conn,
            _leer_id(jardin_id),
            _leer_id(sala_id),
            fecha_elegida,
            errores=errores,
            guardados=_leer_id(guardado),
        )


@app.post("/registro", response_class=HTMLResponse)
async def guardar_registro(request: Request, ruta: Path = Depends(ruta_bd)):
    form = await request.form()
    valores = {k: v for k, v in form.items() if isinstance(v, str)}
    jardin_id = _leer_id(valores.get("jardin_id"))
    sala_id = _leer_id(valores.get("sala_id"))
    fecha = _leer_fecha(valores.get("fecha"))

    with closing(_abrir(ruta)) as conn:
        errores = []
        salas = db.listar_salas(conn, jardin_id) if jardin_id is not None else []
        if sala_id not in [s["id"] for s in salas]:
            errores.append("La sala elegida no pertenece al jardín.")
        if fecha is None:
            errores.append("La fecha no es válida.")
        elif fecha > date.today():
            errores.append("No se puede registrar asistencia de un día futuro.")

        if errores:
            return _pantalla(
                request, conn, jardin_id, sala_id, fecha,
                errores=errores, status_code=400,
            )

        ninos = db.ninos_de_sala(conn, sala_id)
        ids_sala = {n["id"] for n in ninos}
        for clave in valores:
            if clave.startswith("estado_") and _leer_id(clave[7:]) not in ids_sala:
                errores.append("Se envió un niño que no pertenece a esta sala.")
                break

        registros = []
        for nino in ninos:
            estado = valores.get(f"estado_{nino['id']}")
            if estado is None:
                errores.append(f"{nino['codigo']}: falta marcar presente o ausente.")
                continue
            # El menú de motivo solo aplica si faltó; si está presente se ignora.
            motivo = valores.get(f"motivo_{nino['id']}") or None
            if estado == cfg.PRESENTE:
                motivo = None
            try:
                registros.append(Asistencia(nino["id"], fecha, estado, motivo))
            except ValueError as error:
                errores.append(f"{nino['codigo']}: {error}")

        if errores:
            # No se guarda nada si hay un solo error: o se guarda la sala completa o nada.
            return _pantalla(
                request, conn, jardin_id, sala_id, fecha,
                valores=valores, errores=errores, status_code=400,
            )

        with conn:
            db.guardar_asistencias(conn, registros)

    consulta = urlencode(
        {
            "jardin_id": jardin_id,
            "sala_id": sala_id,
            "fecha": fecha.isoformat(),
            "guardado": len(registros),
        }
    )
    return RedirectResponse(f"/?{consulta}", status_code=303)
