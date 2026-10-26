"""Pruebas del seguimiento de casos con base de datos y de la pantalla /casos."""

import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app import config as cfg
from app import db
from app import seguimiento as seg
from app.main import app, ruta_bd
from app.models import Asistencia, Jardin, Nino, Sala
from app.rules import evaluar_nino
from scripts import sembrar_casos
from tests.base_demo import copia_demo


def dias_habiles(inicio: date, cantidad: int) -> list[date]:
    dias, actual = [], inicio
    while len(dias) < cantidad:
        if actual.weekday() < 5:
            dias.append(actual)
        actual += timedelta(days=1)
    return dias


DIAS = dias_habiles(date(2026, 3, 2), 80)
HOY = date(2026, 10, 25)

# Niño "R": días 0-19 falta uno sí y uno no (50%); días 20-21 falta; 22-39 viene.
#   Al día 19: 10 de 20 = 50% (rojo); faltas recientes 50%.
#   Al día 29: 12 de 30 = 40% (rojo); faltas recientes (días 10-29) 7 de 20 = 35%.
#   Al día 39: 12 de 40 = 30% (rojo); faltas recientes (días 20-39) 2 de 20 = 10%.
ESTADOS_R = [cfg.AUSENTE if i % 2 == 0 else cfg.PRESENTE for i in range(20)] + [
    cfg.AUSENTE, cfg.AUSENTE] + [cfg.PRESENTE] * 18

# Niño "E": falta 3 de cada 10 días, siempre igual. Sus faltas recientes son 30% en
# cualquier ventana de 20 días: ninguna revisión mejora.
ESTADOS_E = ([cfg.AUSENTE] * 3 + [cfg.PRESENTE] * 7) * 4


class BaseConDatos(unittest.TestCase):
    """Un jardín con niños en rojo (R y E), uno en verde (V) y uno nuevo con pocos días (N)."""

    def setUp(self):
        self.conn = db.conectar(":memory:")
        db.crear_esquema(self.conn)
        jardin = Jardin("Jardín Prueba (ficticio)", "Antofagasta", "Antofagasta")
        db.insertar_jardin(self.conn, jardin)
        sala = Sala(jardin.id, "Medio menor")
        db.insertar_sala(self.conn, sala)
        self.r, self.v, self.n = Nino("J01-N001", sala.id), Nino("J01-N002", sala.id), Nino("J01-N003", sala.id)
        self.e = Nino("J01-N004", sala.id)
        for nino in (self.r, self.v, self.n, self.e):
            db.insertar_nino(self.conn, nino)
        db.insertar_asistencias(
            self.conn,
            [Asistencia(self.r.id, d, e) for d, e in zip(DIAS, ESTADOS_R)]
            + [Asistencia(self.e.id, d, e) for d, e in zip(DIAS, ESTADOS_E)]
            + [Asistencia(self.v.id, d, cfg.PRESENTE) for d in DIAS[:40]]
            + [Asistencia(self.n.id, d, cfg.AUSENTE) for d in DIAS[35:40]],
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def abrir(self, nino=None, dia=19):
        return seg.abrir_caso(self.conn, (nino or self.r).id, DIAS[dia], hoy=HOY)

    def revisar(self, caso_id, dia, acciones=("Llamado a la familia",), observacion=None):
        return seg.registrar_revision(self.conn, caso_id, DIAS[dia], acciones, observacion, hoy=HOY)


class TestAbrirCaso(BaseConDatos):
    def test_abrir_guarda_el_pct_reciente_de_la_apertura(self):
        caso_id = self.abrir()
        caso = db.obtener_caso(self.conn, caso_id)
        self.assertEqual(caso["estado"], "abierto")
        self.assertEqual(caso["fecha_apertura"], DIAS[19].isoformat())
        self.assertAlmostEqual(caso["pct_reciente_apertura"], 50.0)
        self.assertIsNone(caso["fecha_cierre"])

    def test_no_se_pueden_abrir_dos_casos_para_el_mismo_nino(self):
        self.abrir()
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "ya tiene un caso abierto"):
            self.abrir(dia=25)
        self.assertEqual(db.contar(self.conn, "caso"), 1)

    def test_la_base_tambien_impide_dos_casos_abiertos(self):
        db.insertar_caso(self.conn, self.r.id, DIAS[19], 50.0)
        with self.assertRaises(sqlite3.IntegrityError):
            db.insertar_caso(self.conn, self.r.id, DIAS[20], 50.0)

    def test_despues_de_cerrar_se_puede_abrir_otro(self):
        primero = db.insertar_caso(self.conn, self.r.id, DIAS[19], 50.0)
        db.cerrar_caso(self.conn, primero, DIAS[30])
        db.insertar_caso(self.conn, self.r.id, DIAS[35], 30.0)  # no falla
        self.assertEqual(db.contar(self.conn, "caso"), 2)

    def test_no_se_abre_caso_para_un_nino_que_no_esta_en_rojo(self):
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "no está en rojo"):
            self.abrir(self.v, dia=39)
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "no está en rojo"):
            self.abrir(self.n, dia=39)  # sin datos: solo 5 días
        self.assertEqual(db.contar(self.conn, "caso"), 0)

    def test_en_rojo_se_mira_a_la_fecha_de_apertura(self):
        # Al día 5 tiene 6 días de historial: todavía "sin datos".
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "no está en rojo"):
            self.abrir(dia=5)

    def test_no_se_abre_con_fecha_futura_ni_para_un_nino_inexistente(self):
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "futura"):
            seg.abrir_caso(self.conn, self.r.id, HOY + timedelta(days=1), hoy=HOY)
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "no existe"):
            seg.abrir_caso(self.conn, 999, DIAS[19], hoy=HOY)


class TestRevision(BaseConDatos):
    def test_pct_reciente_usa_solo_el_historial_hasta_la_fecha(self):
        caso_id = self.abrir()
        self.revisar(caso_id, 29)
        revision = db.revisiones_de_caso(self.conn, caso_id)[0]
        # Ya existen datos hasta el día 39, pero la revisión del día 29 no los mira.
        self.assertAlmostEqual(revision["pct_reciente"], 35.0)
        self.assertAlmostEqual(revision["pct_reciente"], evaluar_nino(ESTADOS_R[:30]).pct_reciente)
        self.assertAlmostEqual(evaluar_nino(ESTADOS_R).pct_reciente, 10.0)

    def test_corregir_asistencia_despues_no_cambia_la_revision(self):
        caso_id = self.abrir()
        self.revisar(caso_id, 29)
        db.guardar_asistencias(
            self.conn, [Asistencia(self.r.id, d, cfg.AUSENTE, cfg.SALUD) for d in DIAS[30:40]]
        )
        self.assertAlmostEqual(db.revisiones_de_caso(self.conn, caso_id)[0]["pct_reciente"], 35.0)

    def test_resultados_y_estado(self):
        caso_id = self.abrir()               # 50%
        self.revisar(caso_id, 29)            # 35%: mejora
        resumen = seg.resumen_caso(self.conn, db.obtener_caso(self.conn, caso_id))
        self.assertEqual(resumen["resultados"], [seg.MEJORA])
        self.assertEqual(resumen["estado"], seg.EN_SEGUIMIENTO)

    def test_dos_revisiones_sin_mejora_escalan(self):
        caso_id = self.abrir(self.e, dia=19)   # 30%
        self.revisar(caso_id, 29)              # 30%: sin mejora
        resumen = seg.resumen_caso(self.conn, db.obtener_caso(self.conn, caso_id))
        self.assertEqual(resumen["estado"], seg.EN_SEGUIMIENTO)
        self.revisar(caso_id, 39)              # 30%: sin mejora
        resumen = seg.resumen_caso(self.conn, db.obtener_caso(self.conn, caso_id))
        self.assertEqual(resumen["resultados"], [seg.SIN_MEJORA, seg.SIN_MEJORA])
        self.assertEqual(resumen["estado"], seg.ESCALAR)

    def test_una_mejora_en_el_medio_reinicia_la_cuenta(self):
        caso_id = self.abrir(dia=29)   # R: 35%
        self.revisar(caso_id, 30)      # 30%: mejora (baja justo 5)
        self.revisar(caso_id, 31)      # 30%: sin mejora
        self.revisar(caso_id, 32)      # 25%: mejora
        self.revisar(caso_id, 33)      # 25%: sin mejora
        resumen = seg.resumen_caso(self.conn, db.obtener_caso(self.conn, caso_id))
        self.assertEqual(
            resumen["resultados"], [seg.MEJORA, seg.SIN_MEJORA, seg.MEJORA, seg.SIN_MEJORA]
        )
        self.assertEqual(resumen["sin_mejora_seguidas"], 1)
        self.assertEqual(resumen["estado"], seg.EN_SEGUIMIENTO)

    def test_acciones_se_guardan_en_orden_del_catalogo(self):
        caso_id = self.abrir()
        self.revisar(caso_id, 29, acciones=("Visita al hogar", "Llamado a la familia", "Visita al hogar"))
        self.assertEqual(
            db.revisiones_de_caso(self.conn, caso_id)[0]["acciones"],
            ["Llamado a la familia", "Visita al hogar"],
        )

    def test_validaciones(self):
        caso_id = self.abrir()
        casos_malos = [
            ({"dia": 19}, "posterior a la apertura"),
            ({"dia": 10}, "posterior a la apertura"),
            ({"dia": 29, "acciones": ()}, "al menos una acción"),
            ({"dia": 29, "acciones": ("Retarlo",)}, "Acción desconocida"),
            ({"dia": 29, "observacion": "x" * 301}, "300 caracteres"),
            ({"dia": 29, "observacion": "Mamá con RUT 12.345.678-9"}, "RUT"),
            ({"dia": 29, "observacion": "rut 12345678-k"}, "RUT"),
        ]
        for kwargs, mensaje in casos_malos:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(seg.ErrorSeguimiento, mensaje):
                    self.revisar(caso_id, **kwargs)
        self.assertEqual(db.revisiones_de_caso(self.conn, caso_id), [])

        with self.assertRaisesRegex(seg.ErrorSeguimiento, "futura"):
            seg.registrar_revision(self.conn, caso_id, HOY + timedelta(days=1), ["Visita al hogar"], hoy=HOY)

        self.revisar(caso_id, 29, observacion="  Se coordinó apoyo.  ")
        self.assertEqual(db.revisiones_de_caso(self.conn, caso_id)[0]["observacion"], "Se coordinó apoyo.")
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "posterior a la última revisión"):
            self.revisar(caso_id, 29)
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "posterior a la última revisión"):
            self.revisar(caso_id, 25)

    def test_observacion_vacia_queda_sin_texto(self):
        caso_id = self.abrir()
        self.revisar(caso_id, 29, observacion="   ")
        self.assertIsNone(db.revisiones_de_caso(self.conn, caso_id)[0]["observacion"])


class TestCerrar(BaseConDatos):
    def test_no_se_cierra_si_sigue_en_rojo(self):
        caso_id = self.abrir()
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "cuando ya no está en rojo"):
            seg.cerrar_caso(self.conn, caso_id, hoy=HOY)
        self.assertEqual(db.obtener_caso(self.conn, caso_id)["estado"], "abierto")

    def test_se_cierra_cuando_sale_del_rojo(self):
        caso_id = self.abrir()
        # 40 días más con asistencia: 12 de 80 = 15% (amarillo).
        db.guardar_asistencias(self.conn, [Asistencia(self.r.id, d, cfg.PRESENTE) for d in DIAS[40:80]])
        resumen = seg.resumen_caso(self.conn, db.obtener_caso(self.conn, caso_id))
        self.assertEqual(resumen["nivel_actual"], cfg.AMARILLO)
        self.assertEqual(resumen["estado"], seg.SUGERIR_CIERRE)

        seg.cerrar_caso(self.conn, caso_id, hoy=HOY)
        caso = db.obtener_caso(self.conn, caso_id)
        self.assertEqual((caso["estado"], caso["fecha_cierre"]), ("cerrado", HOY.isoformat()))
        self.assertEqual(db.listar_casos_abiertos(self.conn), [])
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "ya está cerrado"):
            seg.cerrar_caso(self.conn, caso_id, hoy=HOY)
        with self.assertRaisesRegex(seg.ErrorSeguimiento, "cerrado"):
            self.revisar(caso_id, 79)

    def test_regenerar_datos_con_casos_guardados_no_falla(self):
        caso_id = self.abrir()
        self.revisar(caso_id, 29)
        self.conn.commit()
        db.reiniciar_esquema(self.conn)
        self.assertEqual(db.contar(self.conn, "caso"), 0)
        self.assertEqual(db.contar(self.conn, "revision"), 0)


# --- Datos de demostración y pantalla /casos --------------------------------------

class TestPantallaCasos(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.ruta = copia_demo(Path(self.carpeta.name) / "casos.db")
        self.conn = db.conectar(self.ruta)
        db.crear_esquema(self.conn)
        self.sembrados = sembrar_casos.sembrar(self.conn)
        app.dependency_overrides[ruta_bd] = lambda: self.ruta
        self.cliente = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.conn.close()
        self.carpeta.cleanup()

    @staticmethod
    def _casos(html):
        return {
            codigo: (int(caso_id), estado)
            for caso_id, codigo, estado in re.findall(
                r'<tr data-caso="(\d+)" data-codigo="([^"]+)" data-estado="(\w+)">', html
            )
        }

    @staticmethod
    def _candidatos(html):
        return re.findall(r'<tr data-candidato="([^"]+)">', html)

    def _fila(self, html, codigo):
        return re.search(rf'data-codigo="{codigo}".*?</tr>', html, re.S).group(0)

    def test_sembrar_deja_los_tres_ejemplos(self):
        por_ejemplo = {c["ejemplo"]: c for c in self.sembrados}
        self.assertEqual(set(por_ejemplo), {"Escalar", "Mejora", "Recién abierto"})
        self.assertEqual(por_ejemplo["Escalar"]["resultados"], [seg.SIN_MEJORA, seg.SIN_MEJORA])
        self.assertEqual(por_ejemplo["Escalar"]["estado"], seg.ESCALAR)
        self.assertEqual(por_ejemplo["Mejora"]["resultados"], [seg.MEJORA])
        self.assertEqual(por_ejemplo["Recién abierto"]["resultados"], [])
        for c in self.sembrados:
            self.assertTrue(c["codigo"].startswith("J03-"))  # Pequeños Pasos
            meses = [(f.year, f.month) for f in c["fechas"][1:]]
            self.assertEqual(len(meses), len(set(meses)))  # revisiones en meses distintos
            self.assertTrue(all(f < date(2026, 10, 1) for f in c["fechas"][1:]))

    def test_sembrar_dos_veces_no_duplica(self):
        self.assertEqual(sembrar_casos.sembrar(self.conn), [])
        self.assertEqual(db.contar(self.conn, "caso"), 3)
        self.assertEqual(len(sembrar_casos.sembrar(self.conn, reiniciar=True)), 3)
        self.assertEqual(db.contar(self.conn, "caso"), 3)

    def test_muestra_los_ejemplos_sembrados_con_sus_estados(self):
        r = self.cliente.get("/casos")
        self.assertEqual(r.status_code, 200)
        casos = self._casos(r.text)
        esperados = {c["codigo"]: c["estado"] for c in self.sembrados}
        self.assertEqual({k: v for k, (_, v) in casos.items()}, esperados)
        self.assertEqual(list(casos)[0], next(c["codigo"] for c in self.sembrados if c["ejemplo"] == "Escalar"))

        etiquetas = {"escalar": "Escalar", "en_seguimiento": "En seguimiento"}
        resultados = {"Escalar": "Sin mejora", "Mejora": "Mejora", "Recién abierto": "Sin revisiones"}
        for c in self.sembrados:
            fila = self._fila(r.text, c["codigo"])
            self.assertIn(f'<span class="estado-caso {c["estado"]}">{etiquetas[c["estado"]]}</span>', fila)
            self.assertIn(f">{resultados[c['ejemplo']]}</span>", fila)
            self.assertIn(f'<td class="numero">{len(c["fechas"]) - 1}</td>', fila)
            self.assertIn("Pequeños Pasos", fila)
            self.assertNotIn("Cerrar caso", fila)  # siguen en rojo

    def test_ninos_en_rojo_sin_caso(self):
        r = self.cliente.get("/casos", params={"jardin_id": 3})
        con_caso = {c["codigo"] for c in self.sembrados}
        candidatos = self._candidatos(r.text)
        self.assertEqual(len(candidatos), 1)
        self.assertNotIn(candidatos[0], con_caso)
        self.assertIn("Abrir caso", r.text)
        self.assertNotIn("Borrar", r.text)
        # Sin filtro: todos los niños en rojo de la red menos los 3 con caso (80 - 3).
        self.assertEqual(len(self._candidatos(self.cliente.get("/casos").text)), 77)

    def test_aviso_menu_fecha_y_privacidad(self):
        html = self.cliente.get("/casos").text
        self.assertIn("Datos ficticios con fines académicos", html)
        self.assertIn("Datos al: <strong>23-10-2026</strong>", html)
        self.assertIn(
            "No escribas nombres ni datos de salud o personales: usa solo el código del niño.", html
        )
        self.assertIn('href="/casos" aria-current="page">Seguimiento de casos</a>', html)
        for texto in ("Registro diario", "Panel del jardín", "Panel de la Subdirección"):
            self.assertIn(f">{texto}</a>", html)
        for accion in cfg.ACCIONES_SEGUIMIENTO:
            self.assertIn(f'value="{accion}"', html)

    def test_abrir_caso_desde_la_pantalla(self):
        html = self.cliente.get("/casos", params={"jardin_id": 3}).text
        codigo = self._candidatos(html)[0]
        nino_id = re.search(
            rf'data-candidato="{codigo}".*?name="nino_id" value="(\d+)"', html, re.S
        ).group(1)
        r = self.cliente.post("/casos/abrir", data={"nino_id": nino_id, "jardin_id": "3"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"Caso abierto para {codigo}.", r.text)
        self.assertEqual(self._casos(r.text)[codigo][1], seg.EN_SEGUIMIENTO)
        self.assertEqual(self._candidatos(r.text), [])

        r = self.cliente.post("/casos/abrir", data={"nino_id": nino_id, "jardin_id": "3"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("ya tiene un caso abierto", r.text)

    def test_abrir_caso_para_nino_que_no_esta_en_rojo_da_error(self):
        verde = next(
            n for n in db.ninos_de_jardin(self.conn, 3)
            if seg.evaluar_al(self.conn, n["id"]).nivel == cfg.VERDE
        )
        r = self.cliente.post("/casos/abrir", data={"nino_id": verde["id"]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no está en rojo", r.text)

    def test_registrar_revision_desde_la_pantalla(self):
        recien = next(c for c in self.sembrados if c["ejemplo"] == "Recién abierto")
        url = f"/casos/{recien['caso_id']}/revision"
        hoy = date.today().isoformat()

        r = self.cliente.post(url, data={"fecha": hoy, "acciones": ["Visita al hogar"],
                                         "observacion": "RUT 11.111.111-1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("parece tener un RUT", r.text)
        self.assertIn(f'id="caso-{recien["caso_id"]}" open', r.text)  # el formulario queda abierto
        self.assertRegex(r.text, r'value="Visita al hogar"\s+checked')

        r = self.cliente.post(url, data={"fecha": hoy, "observacion": "Sin acciones"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("al menos una acción", r.text)

        r = self.cliente.post(url, data={
            "fecha": hoy, "acciones": ["Visita al hogar", "Llamado a la familia"],
            "observacion": "Se acordó un nuevo horario de traslado.",
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"Revisión registrada para {recien['codigo']}.", r.text)
        revisiones = db.revisiones_de_caso(self.conn, recien["caso_id"])
        self.assertEqual(len(revisiones), 1)
        self.assertEqual(revisiones[0]["acciones"], ["Llamado a la familia", "Visita al hogar"])

    def test_cerrar_caso_que_sigue_en_rojo_da_error(self):
        caso_id = self.sembrados[0]["caso_id"]
        r = self.cliente.post(f"/casos/{caso_id}/cerrar", data={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("cuando ya no está en rojo", r.text)
        self.assertEqual(db.obtener_caso(self.conn, caso_id)["estado"], "abierto")

    def test_boton_cerrar_aparece_solo_con_sugerir_cierre(self):
        caso = next(c for c in self.sembrados if c["ejemplo"] == "Mejora")
        nino_id = db.obtener_caso(self.conn, caso["caso_id"])["nino_id"]
        # Muchos días más con asistencia: el niño sale del rojo.
        ultimo = db.ultima_fecha_con_datos(self.conn)
        nuevos = dias_habiles(ultimo + timedelta(days=1), 300)
        with self.conn:
            db.guardar_asistencias(self.conn, [Asistencia(nino_id, d, cfg.PRESENTE) for d in nuevos])

        r = self.cliente.get("/casos")
        fila = self._fila(r.text, caso["codigo"])
        self.assertIn("Sugerir cierre", fila)
        self.assertIn("Cerrar caso", fila)
        self.assertEqual(r.text.count(">Cerrar caso</button>"), 1)

        r = self.cliente.post(f"/casos/{caso['caso_id']}/cerrar", data={})
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"Caso de {caso['codigo']} cerrado.", r.text)
        self.assertNotIn(caso["codigo"], self._casos(r.text))


if __name__ == "__main__":
    unittest.main()
