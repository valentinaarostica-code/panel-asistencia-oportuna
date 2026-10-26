"""Pantallas web del Panel de Asistencia Oportuna (FastAPI + Jinja2).

Pantallas:
- "/"       Registro diario de asistencia de una sala.
- "/panel"  Panel del jardín: a quién actuar esta semana.
- "/subdireccion"  Panel de la Subdirección: todos los jardines juntos.
- "/casos"  Seguimiento de casos del Comité de Asistencia.

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
from app import seguimiento as seg
from app.models import Asistencia
from app.rules import (
    ALERTA_RACHA,
    DESCRIPCION_ALERTA,
    ResultadoNino,
    ResumenJardin,
    evaluar_nino,
    resumen_jardin,
)

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

SENAL_PROMEDIO_OCULTA = "Promedio que oculta casos graves"


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


def _formato_pct_corto(valor: float) -> str:
    """Como _formato_pct, pero sin ",0" cuando es entero: 16% en vez de 16,0%."""
    texto = _formato_pct(valor)
    return texto.replace(",0%", "%")


def _plural(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _contexto_base(seccion: str, jardin_id: Optional[int]) -> dict:
    """Lo que necesita base.html: el aviso, el menú y la pantalla activa."""
    return {
        "nombre_sistema": cfg.NOMBRE_SISTEMA,
        "aviso": cfg.AVISO_DATOS_FICTICIOS,
        "seccion": seccion,
        "jardin_id": jardin_id,
    }


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
        **_contexto_base("registro", jardin_id),
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


# --- Pantalla 2: Panel del jardín ----------------------------------------------

def _prioridad(resultado: ResultadoNino) -> int:
    """Orden de atención: rojo, racha, amarillo, verde y al final sin datos."""
    if resultado.nivel == cfg.ROJO:
        return 0
    if ALERTA_RACHA in resultado.alertas:
        return 1
    if resultado.nivel == cfg.AMARILLO:
        return 2
    if resultado.nivel == cfg.VERDE:
        return 3
    return 4


def _promedio_alto(promedio: Optional[float]) -> bool:
    """True si la asistencia promedio "se ve bien" (desde cfg.UMBRAL_PROMEDIO_ALTO_PCT).

    Se redondea para que 90% exacto no quede fuera por un error de decimales.
    """
    return promedio is not None and round(promedio, 6) >= cfg.UMBRAL_PROMEDIO_ALTO_PCT


def _frase_resumen(resumen: ResumenJardin) -> tuple[str, bool]:
    """La frase bajo las tarjetas y si va destacada como advertencia."""
    promedio = resumen.asistencia_promedio_pct
    if promedio is None:
        return "Todavía no hay asistencia registrada en este jardín.", False
    texto_prom = _formato_pct(promedio)
    con_semaforo = resumen.ninos - resumen.ninos_sin_datos
    if con_semaforo == 0:
        return (
            f"La asistencia promedio es {texto_prom}, pero aún hay muy pocos días "
            "de clases para pintar el semáforo.",
            False,
        )
    if resumen.ninos_rojo == 0:
        return f"La asistencia promedio es {texto_prom} y ningún niño está en rojo.", False

    # pct_ninos_rojo se calcula sobre los niños que ya tienen semáforo.
    total = f"{con_semaforo} niños" + (" con semáforo" if resumen.ninos_sin_datos else "")
    rojos = (
        f"{resumen.ninos_rojo} de {total} ({_formato_pct_corto(resumen.pct_ninos_rojo)}) "
        f"{'está' if resumen.ninos_rojo == 1 else 'están'} en rojo"
    )
    if _promedio_alto(promedio):
        return f"El promedio se ve bien ({texto_prom}), pero {rojos}.", True
    return f"La asistencia promedio es {texto_prom} y {rojos}.", False


def _pantalla_panel(request: Request, contexto: dict, status_code: int = 200):
    return plantillas.TemplateResponse(
        request, "panel.html", contexto, status_code=status_code
    )


@app.get("/panel", response_class=HTMLResponse)
def panel(
    request: Request,
    jardin_id: Optional[str] = None,
    sala_id: Optional[str] = None,
    color: Optional[str] = None,
    solo_alerta: Optional[str] = None,
    ruta: Path = Depends(ruta_bd),
):
    with closing(_abrir(ruta)) as conn:
        jardines = db.listar_jardines(conn)
        if jardin_id:
            jardin = next((j for j in jardines if j["id"] == _leer_id(jardin_id)), None)
            if jardin is None:
                return _pantalla_panel(
                    request,
                    {
                        **_contexto_base("panel", None),
                        "jardines": jardines,
                        "jardin": None,
                        "error": f"No existe un jardín con el número «{jardin_id}».",
                    },
                    status_code=404,
                )
        else:
            jardin = jardines[0] if jardines else None

        if jardin is None:
            return _pantalla_panel(
                request,
                {**_contexto_base("panel", None), "jardines": [], "jardin": None},
            )

        salas = db.listar_salas(conn, jardin["id"])
        historial = db.estados_por_nino(conn, jardin["id"])
        evaluados = [
            (nino, evaluar_nino(historial.get(nino["id"], [])))
            for nino in db.ninos_de_jardin(conn, jardin["id"])
        ]
        # Las tarjetas y los conteos son siempre del jardín completo:
        # los filtros solo achican la lista.
        resumen = resumen_jardin(r for _, r in evaluados)
        frase, advertencia = _frase_resumen(resumen)
        ultima = db.ultima_fecha_con_datos(conn, jardin["id"])

        # --- Filtros (si un valor no sirve, se ignora y se avisa) -------------
        avisos = []
        sala_elegida = _leer_id(sala_id)
        if sala_id and sala_elegida not in [s["id"] for s in salas]:
            avisos.append("La sala elegida no es de este jardín: se muestran todas las salas.")
            sala_elegida = None
        color_elegido = color or None
        if color_elegido is not None and color_elegido not in cfg.NIVELES:
            avisos.append(f"El color «{color}» no existe: se muestran todos los colores.")
            color_elegido = None
        solo_con_alerta = solo_alerta == "1"

        visibles = [
            (nino, r)
            for nino, r in evaluados
            if (sala_elegida is None or nino["sala_id"] == sala_elegida)
            and (color_elegido is None or r.nivel == color_elegido)
            and (not solo_con_alerta or r.tiene_alerta)
        ]
        visibles.sort(key=lambda par: (_prioridad(par[1]), -par[1].pct_inasistencia, par[0]["codigo"]))

        filas = [
            {
                "codigo": nino["codigo"],
                "sala": nino["sala"],
                "nivel": r.nivel,
                "etiqueta": ETIQUETA_NIVEL[r.nivel],
                "pct": _formato_pct(r.pct_inasistencia),
                "ausencias": (
                    f"{_plural(r.ausencias, 'ausencia', 'ausencias')} de "
                    f"{_plural(r.dias_lectivos, 'día', 'días')}"
                ),
                "alertas": [DESCRIPCION_ALERTA[a] for a in r.alertas],
                "racha": ALERTA_RACHA in r.alertas,
                "enlace_registro": "/?" + urlencode(
                    {"jardin_id": jardin["id"], "sala_id": nino["sala_id"]}
                ),
            }
            for nino, r in visibles
        ]

        contexto = {
            **_contexto_base("panel", jardin["id"]),
            "jardines": jardines,
            "jardin": jardin,
            "salas": salas,
            "resumen": resumen,
            "promedio": (
                _formato_pct(resumen.asistencia_promedio_pct)
                if resumen.asistencia_promedio_pct is not None else "—"
            ),
            "pct_rojo": _formato_pct_corto(resumen.pct_ninos_rojo),
            "con_semaforo": resumen.ninos - resumen.ninos_sin_datos,
            "frase": frase,
            "advertencia": advertencia,
            "datos_al": ultima.strftime("%d-%m-%Y") if ultima else "sin datos",
            "filas": filas,
            "sala_elegida": sala_elegida,
            "color_elegido": color_elegido,
            "solo_con_alerta": solo_con_alerta,
            "hay_filtros": bool(sala_elegida or color_elegido or solo_con_alerta),
            "avisos": avisos,
            "colores": [(n, ETIQUETA_NIVEL[n]) for n in (cfg.ROJO, cfg.AMARILLO, cfg.VERDE, cfg.SIN_DATOS)],
            "base_panel": f"/panel?jardin_id={jardin['id']}",
        }
        return _pantalla_panel(request, contexto)


# --- Pantalla 3: Panel de la Subdirección --------------------------------------

# Columnas por las que se puede ordenar: (cómo se lee el valor, dirección por defecto).
ORDENES = {
    "rojo": (lambda f: f["resumen"].pct_ninos_rojo, "desc"),
    "riesgo": (lambda f: f["resumen"].pct_ninos_en_riesgo, "desc"),
    "promedio": (lambda f: f["resumen"].asistencia_promedio_pct, "desc"),
    "alerta": (lambda f: f["resumen"].ninos_con_alerta, "desc"),
    "ninos": (lambda f: f["resumen"].ninos, "desc"),
    "nombre": (lambda f: f["nombre"].casefold(), "asc"),
}
ORDEN_DEFECTO = "rojo"


def _senal(resumen: ResumenJardin) -> Optional[str]:
    """Señal del jardín: el promedio se ve bien, pero tiene varios niños en rojo."""
    if _promedio_alto(resumen.asistencia_promedio_pct) and (
        resumen.ninos_rojo >= cfg.MIN_ROJOS_ALERTA_JARDIN
    ):
        return SENAL_PROMEDIO_OCULTA
    return None


def _puestos(valores: Mapping[int, Optional[float]]) -> dict[int, tuple[Optional[int], bool]]:
    """Ranking de mayor a menor: {id: (puesto, ¿empatado?)}. Los empates comparten puesto.

    Ejemplo: 40, 40, 36 → puestos 1, 1, 3. Sin valor (None) no tiene puesto.
    """
    redondeados = {k: round(v, 6) for k, v in valores.items() if v is not None}
    resultado: dict[int, tuple[Optional[int], bool]] = {k: (None, False) for k in valores}
    for clave, valor in redondeados.items():
        mayores = sum(1 for v in redondeados.values() if v > valor)
        iguales = sum(1 for v in redondeados.values() if v == valor)
        resultado[clave] = (mayores + 1, iguales > 1)
    return resultado


def _ordenar(filas: list[dict], orden: str, direccion: str) -> list[dict]:
    """Ordena por la columna pedida; los empates y los jardines sin datos van por nombre."""
    leer, _ = ORDENES[orden]
    por_nombre = sorted(filas, key=lambda f: f["nombre"].casefold())
    con_valor = [f for f in por_nombre if leer(f) is not None]
    sin_valor = [f for f in por_nombre if leer(f) is None]
    # sorted es estable también con reverse=True: los empates quedan por nombre.
    return sorted(con_valor, key=leer, reverse=(direccion == "desc")) + sin_valor


def _celdas_resumen(resumen: ResumenJardin) -> dict:
    """Los números de una fila de la tabla, ya con formato."""
    con_semaforo = resumen.ninos - resumen.ninos_sin_datos
    return {
        "resumen": resumen,
        "promedio": (
            _formato_pct(resumen.asistencia_promedio_pct)
            if resumen.asistencia_promedio_pct is not None else "—"
        ),
        "pct_rojo": _formato_pct(resumen.pct_ninos_rojo) if con_semaforo else "—",
        "pct_riesgo": _formato_pct(resumen.pct_ninos_en_riesgo) if con_semaforo else "—",
    }


@app.get("/subdireccion", response_class=HTMLResponse)
def subdireccion(
    request: Request,
    orden: Optional[str] = None,
    dir: Optional[str] = None,
    region: Optional[str] = None,
    ruta: Path = Depends(ruta_bd),
):
    with closing(_abrir(ruta)) as conn:
        jardines = db.listar_jardines(conn)
        ultima = db.ultima_fecha_con_datos(conn)
        filas = []
        todos_los_ninos = []
        for jardin in jardines:
            historial = db.estados_por_nino(conn, jardin["id"])
            resultados = [
                evaluar_nino(historial.get(nino["id"], []))
                for nino in db.ninos_de_jardin(conn, jardin["id"])
            ]
            todos_los_ninos.append(resultados)
            resumen = resumen_jardin(resultados)
            filas.append(
                {
                    "id": jardin["id"],
                    "nombre": jardin["nombre"],
                    "comuna": jardin["comuna"],
                    "region": jardin["region"],
                    "enlace": f"/panel?jardin_id={jardin['id']}",
                    "senal": _senal(resumen),
                    **_celdas_resumen(resumen),
                }
            )

    # Los puestos se calculan con toda la red, para que el filtro no los cambie.
    por_promedio = _puestos({f["id"]: f["resumen"].asistencia_promedio_pct for f in filas})
    por_rojo = _puestos({f["id"]: f["resumen"].pct_ninos_rojo for f in filas})
    for f in filas:
        f["puesto_promedio"], f["empate_promedio"] = por_promedio[f["id"]]
        f["puesto_rojo"], f["empate_rojo"] = por_rojo[f["id"]]

    # Tarjetas: siempre de toda la red.
    red = resumen_jardin(r for resultados in todos_los_ninos for r in resultados)
    jardines_con_senal = sum(1 for f in filas if f["senal"])

    # Filtro por región (si no existe, se muestran todas y se avisa).
    avisos = []
    regiones = sorted({f["region"] for f in filas})
    region_elegida = region or None
    if region_elegida is not None and region_elegida not in regiones:
        avisos.append(f"La región «{region}» no existe: se muestran todas las regiones.")
        region_elegida = None
    indices_visibles = [
        i for i, f in enumerate(filas) if region_elegida is None or f["region"] == region_elegida
    ]
    visibles = [filas[i] for i in indices_visibles]

    # Orden (si no es válido, se usa el orden por defecto, sin error).
    if orden not in ORDENES:
        orden, dir = ORDEN_DEFECTO, None
    if dir not in ("asc", "desc"):
        dir = ORDENES[orden][1]
    visibles = _ordenar(visibles, orden, dir)

    # Fila de totales: lo que se ve en la tabla.
    total = _celdas_resumen(
        resumen_jardin(r for i in indices_visibles for r in todos_los_ninos[i])
    )

    def enlace_orden(columna: str) -> str:
        """Enlace del encabezado: si ya se ordena por esa columna, invierte la dirección."""
        if columna == orden:
            nueva = "asc" if dir == "desc" else "desc"
        else:
            nueva = ORDENES[columna][1]
        params = {"orden": columna, "dir": nueva}
        if region_elegida:
            params["region"] = region_elegida
        return "/subdireccion?" + urlencode(params)

    contexto = {
        **_contexto_base("subdireccion", None),
        "datos_al": ultima.strftime("%d-%m-%Y") if ultima else "sin datos",
        "red": red,
        "pct_rojo_red": _formato_pct(red.pct_ninos_rojo),
        "con_semaforo_red": red.ninos - red.ninos_sin_datos,
        "jardines_con_senal": jardines_con_senal,
        "total_jardines": len(filas),
        "filas": visibles,
        "total": total,
        "titulo_total": f"Total {region_elegida}" if region_elegida else "Total de la red",
        "regiones": regiones,
        "region_elegida": region_elegida,
        "orden": orden,
        "dir": dir,
        "enlaces_orden": {c: enlace_orden(c) for c in ORDENES},
        "avisos": avisos,
        "senal_texto": SENAL_PROMEDIO_OCULTA,
        "umbral_promedio": cfg.UMBRAL_PROMEDIO_ALTO_PCT,
        "min_rojos": cfg.MIN_ROJOS_ALERTA_JARDIN,
    }
    return plantillas.TemplateResponse(request, "subdireccion.html", contexto)


# --- Pantalla 4: Seguimiento de casos ---------------------------------------------

# Orden de la tabla de casos: primero lo que pide una decisión del Comité.
PRIORIDAD_ESTADO = {seg.ESCALAR: 0, seg.SUGERIR_CIERRE: 1, seg.EN_SEGUIMIENTO: 2}

CONFIRMACIONES = {
    "abierto": "Caso abierto para {codigo}.",
    "revision": "Revisión registrada para {codigo}.",
    "cerrado": "Caso de {codigo} cerrado.",
}


def _volver_a_casos(jardin_id: Optional[int], ok: str, codigo: str) -> RedirectResponse:
    params = {"ok": ok, "codigo": codigo}
    if jardin_id is not None:
        params["jardin_id"] = jardin_id
    return RedirectResponse("/casos?" + urlencode(params), status_code=303)


def _pantalla_casos(
    request: Request,
    conn: sqlite3.Connection,
    jardin_id: Optional[str] = None,
    confirmacion: Optional[str] = None,
    error: Optional[str] = None,
    error_caso_id: Optional[int] = None,
    valores: Optional[dict] = None,
    status_code: int = 200,
):
    jardines = db.listar_jardines(conn)
    avisos = []
    jardin_elegido = _leer_id(jardin_id)
    if jardin_id and jardin_elegido not in [j["id"] for j in jardines]:
        avisos.append("El jardín elegido no existe: se muestran todos los jardines.")
        jardin_elegido = None

    # Casos abiertos, con su estado calculado por app.seguimiento.
    casos = [seg.resumen_caso(conn, c) for c in db.listar_casos_abiertos(conn, jardin_elegido)]
    con_caso = {c["caso"]["nino_id"] for c in casos}
    casos.sort(key=lambda c: (PRIORIDAD_ESTADO[c["estado"]], c["caso"]["fecha_apertura"], c["caso"]["codigo"]))
    for c in casos:
        c["etiqueta_estado"] = seg.ETIQUETA_ESTADO[c["estado"]]
        c["etiqueta_resultado"] = seg.ETIQUETA_RESULTADO[c["ultimo_resultado"]]
        c["etiqueta_nivel"] = ETIQUETA_NIVEL[c["nivel_actual"]]
        c["pct_apertura"] = _formato_pct(c["caso"]["pct_reciente_apertura"])
        c["pct_reciente"] = _formato_pct(c["pct_reciente_actual"])
        c["pct_actual"] = _formato_pct(c["pct_actual"])
        for r in c["revisiones"]:
            r["etiqueta"] = seg.ETIQUETA_RESULTADO[r["resultado"]]
            r["pct"] = _formato_pct(r["pct_reciente"])
            r["fecha_txt"] = date.fromisoformat(r["fecha"]).strftime("%d-%m-%Y")
        c["apertura_txt"] = date.fromisoformat(c["caso"]["fecha_apertura"]).strftime("%d-%m-%Y")

    # Niños en rojo sin caso abierto (con todo su historial).
    historial = db.estados_por_nino(conn, jardin_elegido)
    candidatos = []
    for nino in db.ninos_con_jardin(conn, jardin_elegido):
        if nino["id"] in con_caso:
            continue
        r = evaluar_nino(historial.get(nino["id"], []))
        if r.nivel == cfg.ROJO:
            candidatos.append(
                {
                    "id": nino["id"],
                    "codigo": nino["codigo"],
                    "jardin": nino["jardin"],
                    "sala": nino["sala"],
                    "pct": _formato_pct(r.pct_inasistencia),
                    "pct_reciente": _formato_pct(r.pct_reciente),
                    "orden": -r.pct_inasistencia,
                }
            )
    candidatos.sort(key=lambda n: (n["orden"], n["codigo"]))

    ultima = db.ultima_fecha_con_datos(conn)
    contexto = {
        **_contexto_base("casos", jardin_elegido),
        "jardines": jardines,
        "jardin_elegido": jardin_elegido,
        "datos_al": ultima.strftime("%d-%m-%Y") if ultima else "sin datos",
        "hoy": date.today(),
        "casos": casos,
        "candidatos": candidatos,
        "acciones": cfg.ACCIONES_SEGUIMIENTO,
        "max_observacion": seg.MAX_OBSERVACION,
        "ventana": cfg.VENTANA_RECIENTE_DIAS,
        "mejora_min": cfg.MEJORA_MIN_PUNTOS,
        "revisiones_escala": cfg.REVISIONES_SIN_MEJORA_ESCALA,
        "confirmacion": confirmacion,
        "error": error,
        "error_caso_id": error_caso_id,
        "valores": valores or {},
        "avisos": avisos,
        "SUGERIR_CIERRE": seg.SUGERIR_CIERRE,
    }
    return plantillas.TemplateResponse(request, "casos.html", contexto, status_code=status_code)


@app.get("/casos", response_class=HTMLResponse)
def casos(
    request: Request,
    jardin_id: Optional[str] = None,
    ok: Optional[str] = None,
    codigo: Optional[str] = None,
    ruta: Path = Depends(ruta_bd),
):
    confirmacion = None
    if ok in CONFIRMACIONES and codigo:
        confirmacion = CONFIRMACIONES[ok].format(codigo=codigo)
    with closing(_abrir(ruta)) as conn:
        return _pantalla_casos(request, conn, jardin_id, confirmacion=confirmacion)


@app.post("/casos/abrir", response_class=HTMLResponse)
async def abrir_caso(request: Request, ruta: Path = Depends(ruta_bd)):
    form = await request.form()
    jardin_id = form.get("jardin_id") or None
    nino_id = _leer_id(form.get("nino_id"))
    with closing(_abrir(ruta)) as conn:
        try:
            if nino_id is None:
                raise seg.ErrorSeguimiento("Falta indicar el niño.")
            with conn:
                seg.abrir_caso(conn, nino_id, date.today())
        except seg.ErrorSeguimiento as error:
            return _pantalla_casos(request, conn, jardin_id, error=str(error), status_code=400)
        codigo = db.obtener_nino(conn, nino_id)["codigo"]
    return _volver_a_casos(_leer_id(jardin_id), "abierto", codigo)


@app.post("/casos/{caso_id}/revision", response_class=HTMLResponse)
async def registrar_revision(caso_id: int, request: Request, ruta: Path = Depends(ruta_bd)):
    form = await request.form()
    jardin_id = form.get("jardin_id") or None
    acciones = [a for a in form.getlist("acciones") if isinstance(a, str)]
    observacion = form.get("observacion") or ""
    texto_fecha = form.get("fecha") or ""
    with closing(_abrir(ruta)) as conn:
        try:
            fecha = _leer_fecha(texto_fecha)
            if fecha is None:
                raise seg.ErrorSeguimiento("La fecha de la revisión no es válida.")
            with conn:
                seg.registrar_revision(conn, caso_id, fecha, acciones, observacion)
        except seg.ErrorSeguimiento as error:
            valores = {"fecha": texto_fecha, "acciones": acciones, "observacion": observacion}
            return _pantalla_casos(
                request, conn, jardin_id, error=str(error),
                error_caso_id=caso_id, valores=valores, status_code=400,
            )
        codigo = db.obtener_caso(conn, caso_id)["codigo"]
    return _volver_a_casos(_leer_id(jardin_id), "revision", codigo)


@app.post("/casos/{caso_id}/cerrar", response_class=HTMLResponse)
async def cerrar_caso(caso_id: int, request: Request, ruta: Path = Depends(ruta_bd)):
    form = await request.form()
    jardin_id = form.get("jardin_id") or None
    with closing(_abrir(ruta)) as conn:
        try:
            with conn:
                seg.cerrar_caso(conn, caso_id)
        except seg.ErrorSeguimiento as error:
            return _pantalla_casos(request, conn, jardin_id, error=str(error), status_code=400)
        codigo = db.obtener_caso(conn, caso_id)["codigo"]
    return _volver_a_casos(_leer_id(jardin_id), "cerrado", codigo)
