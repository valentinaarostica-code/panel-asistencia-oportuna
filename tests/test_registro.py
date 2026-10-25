"""Pruebas de la pantalla "Registro diario de asistencia" (app/main.py)."""

import re
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app import config as cfg
from app import db
from app.main import app, ruta_bd
from app.models import Asistencia, Jardin, Nino, Sala


def dias_habiles(inicio: date, cantidad: int) -> list[date]:
    dias, actual = [], inicio
    while len(dias) < cantidad:
        if actual.weekday() < 5:
            dias.append(actual)
        actual += timedelta(days=1)
    return dias


# 13 días de clases: los 10 primeros ya están cargados, los 3 últimos se registran en las pruebas.
DIAS = dias_habiles(date(2026, 3, 2), 13)


class TestRegistro(unittest.TestCase):
    def setUp(self):
        self.carpeta = tempfile.TemporaryDirectory()
        self.ruta = Path(self.carpeta.name) / "prueba.db"
        with closing(db.conectar(self.ruta)) as conn:
            db.crear_esquema(conn)
            self.jardin = Jardin("Jardín Prueba (ficticio)", "Antofagasta", "Antofagasta")
            db.insertar_jardin(conn, self.jardin)
            self.sala = Sala(self.jardin.id, "Medio menor")
            db.insertar_sala(conn, self.sala)
            self.n1 = Nino("J01-N001", self.sala.id)
            self.n2 = Nino("J01-N002", self.sala.id)
            db.insertar_nino(conn, self.n1)
            db.insertar_nino(conn, self.n2)

            otro = Jardin("Otro Jardín (ficticio)", "Calama", "Antofagasta")
            db.insertar_jardin(conn, otro)
            self.otra_sala = Sala(otro.id, "Sala cuna")
            db.insertar_sala(conn, self.otra_sala)
            self.ajeno = Nino("J02-N001", self.otra_sala.id)
            db.insertar_nino(conn, self.ajeno)

            db.insertar_asistencias(
                conn,
                [Asistencia(n.id, d, cfg.PRESENTE) for n in (self.n1, self.n2) for d in DIAS[:10]],
            )
            conn.commit()

        app.dependency_overrides[ruta_bd] = lambda: self.ruta
        self.cliente = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.carpeta.cleanup()

    # --- Ayudas -------------------------------------------------------------

    def _formulario(self, fecha, **por_nino):
        """por_nino: {"n1": ("ausente", "Salud"), ...}; los no indicados quedan presentes."""
        datos = {
            "jardin_id": str(self.jardin.id),
            "sala_id": str(self.sala.id),
            "fecha": fecha.isoformat(),
        }
        for nombre in ("n1", "n2"):
            nino = getattr(self, nombre)
            estado, motivo = por_nino.get(nombre, (cfg.PRESENTE, cfg.SIN_INFORMACION))
            datos[f"estado_{nino.id}"] = estado
            datos[f"motivo_{nino.id}"] = motivo
        return datos

    def _guardar(self, fecha, **por_nino):
        return self.cliente.post("/registro", data=self._formulario(fecha, **por_nino))

    def _ver(self, fecha):
        return self.cliente.get(
            "/", params={"jardin_id": self.jardin.id, "sala_id": self.sala.id,
                         "fecha": fecha.isoformat()}
        )

    def _nivel(self, html, nino):
        fila = re.search(rf'<tr data-nino="{nino.id}">(.*?)</tr>', html, re.S)
        self.assertIsNotNone(fila, f"No aparece el niño {nino.codigo}")
        return re.search(r'data-nivel="([a-z_]+)"', fila.group(1)).group(1)

    def _registros(self):
        with closing(db.conectar(self.ruta)) as conn:
            return conn.execute(
                "SELECT nino_id, fecha, estado, motivo, informado_por_familia "
                "FROM asistencia ORDER BY nino_id, fecha"
            ).fetchall()

    # --- Pantalla -----------------------------------------------------------

    def test_muestra_aviso_y_solo_codigos_de_la_sala(self):
        r = self.cliente.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Datos ficticios con fines académicos", r.text)
        self.assertIn("Registro diario de asistencia", r.text)
        self.assertIn("J01-N001", r.text)
        self.assertIn("J01-N002", r.text)
        self.assertNotIn("J02-N001", r.text)  # es de otro jardín
        for motivo in cfg.MOTIVOS:
            self.assertIn(motivo, r.text)

    def test_fecha_por_defecto_es_el_ultimo_dia_con_datos(self):
        r = self.cliente.get("/")
        self.assertIn(f'name="fecha" value="{DIAS[9].isoformat()}"', r.text)

    def test_sala_de_otro_jardin_usa_la_primera_sala_del_jardin(self):
        r = self.cliente.get(
            "/", params={"jardin_id": self.jardin.id, "sala_id": self.otra_sala.id}
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("J01-N001", r.text)
        self.assertNotIn("J02-N001", r.text)

    def test_semaforo_inicial_verde(self):
        r = self._ver(DIAS[9])
        self.assertEqual(self._nivel(r.text, self.n1), cfg.VERDE)
        self.assertIn("0,0% de faltas (0 de 10 días)", r.text)

    def test_semaforo_sin_datos_con_pocos_dias(self):
        # Un niño que llegó hace poco: solo tiene 5 días registrados.
        with closing(db.conectar(self.ruta)) as conn:
            sala = Sala(self.jardin.id, "Sala cuna")
            db.insertar_sala(conn, sala)
            nuevo = Nino("J01-N003", sala.id)
            db.insertar_nino(conn, nuevo)
            db.insertar_asistencias(
                conn, [Asistencia(nuevo.id, d, cfg.AUSENTE) for d in DIAS[5:10]]
            )
            conn.commit()
        r = self.cliente.get("/", params={"jardin_id": self.jardin.id, "sala_id": sala.id})
        self.assertEqual(self._nivel(r.text, nuevo), cfg.SIN_DATOS)
        self.assertIn("5 de 10 días mínimos", r.text)

    def test_dia_antiguo_muestra_el_mismo_color_que_hoy(self):
        self._guardar(DIAS[10], n1=(cfg.AUSENTE, cfg.SALUD))
        self._guardar(DIAS[11], n1=(cfg.AUSENTE, cfg.SALUD))  # 2 de 12 = 16,7%

        hoy = self.cliente.get("/", params={"jardin_id": self.jardin.id, "sala_id": self.sala.id})
        self.assertIn(f'name="fecha" value="{DIAS[11].isoformat()}"', hoy.text)
        antiguo = self._ver(DIAS[0])  # ese día el niño vino y aún no tenía faltas

        self.assertEqual(self._nivel(hoy.text, self.n1), cfg.AMARILLO)
        self.assertEqual(self._nivel(antiguo.text, self.n1), cfg.AMARILLO)
        for r in (hoy, antiguo):
            self.assertIn("16,7% de faltas (2 de 12 días)", r.text)

    # --- Guardar ------------------------------------------------------------

    def test_guardar_crea_registros_y_confirma(self):
        r = self._guardar(DIAS[10], n1=(cfg.AUSENTE, cfg.SALUD))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.history), 1)
        self.assertEqual(r.history[0].status_code, 303)  # vuelve a la pantalla tras guardar
        self.assertIn("Asistencia guardada: 2 niños", r.text)

        nuevos = [f for f in self._registros() if f["fecha"] == DIAS[10].isoformat()]
        self.assertEqual(
            [tuple(f) for f in nuevos],
            [
                (self.n1.id, DIAS[10].isoformat(), cfg.AUSENTE, cfg.SALUD, 1),
                (self.n2.id, DIAS[10].isoformat(), cfg.PRESENTE, None, 0),
            ],
        )

    def test_ausente_sin_motivo_queda_sin_informacion(self):
        self._guardar(DIAS[10], n1=(cfg.AUSENTE, ""))
        fila = [f for f in self._registros() if f["fecha"] == DIAS[10].isoformat()][0]
        self.assertEqual((fila["motivo"], fila["informado_por_familia"]), (cfg.SIN_INFORMACION, 0))

    def test_presente_ignora_el_motivo_enviado(self):
        r = self._guardar(DIAS[10], n1=(cfg.PRESENTE, cfg.SALUD))
        self.assertEqual(r.status_code, 200)
        fila = [f for f in self._registros() if f["fecha"] == DIAS[10].isoformat()][0]
        self.assertIsNone(fila["motivo"])

    def test_guardar_otra_vez_actualiza_sin_duplicar(self):
        self._guardar(DIAS[10])
        total = len(self._registros())
        r = self._guardar(DIAS[10], n2=(cfg.AUSENTE, cfg.FAMILIAR))
        self.assertEqual(r.status_code, 200)
        filas = self._registros()
        self.assertEqual(len(filas), total)
        fila = [f for f in filas if f["nino_id"] == self.n2.id and f["fecha"] == DIAS[10].isoformat()][0]
        self.assertEqual((fila["estado"], fila["motivo"]), (cfg.AUSENTE, cfg.FAMILIAR))
        # Y la pantalla muestra lo guardado.
        self.assertRegex(r.text, rf'(?s)name="motivo_{self.n2.id}".*?<option value="{cfg.FAMILIAR}" selected')

    def test_corregir_un_dia_antiguo(self):
        r = self._guardar(DIAS[3], n1=(cfg.AUSENTE, cfg.CLIMA))
        self.assertEqual(r.status_code, 200)
        fila = [f for f in self._registros() if f["nino_id"] == self.n1.id and f["fecha"] == DIAS[3].isoformat()][0]
        self.assertEqual(fila["estado"], cfg.AUSENTE)

    # --- Errores ------------------------------------------------------------

    def test_motivo_invalido_no_guarda_nada(self):
        antes = len(self._registros())
        r = self._guardar(DIAS[10], n1=(cfg.AUSENTE, cfg.SALUD), n2=(cfg.AUSENTE, "Flojera"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("No se guardó nada", r.text)
        self.assertIn("J01-N002", r.text)
        self.assertIn("Motivo inválido", r.text)
        self.assertEqual(len(self._registros()), antes)  # tampoco se guardó el n1

    def test_estado_invalido(self):
        r = self._guardar(DIAS[10], n1=("tarde", cfg.SIN_INFORMACION))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Estado inválido", r.text)

    def test_falta_marcar_a_un_nino(self):
        datos = self._formulario(DIAS[10])
        del datos[f"estado_{self.n2.id}"]
        r = self.cliente.post("/registro", data=datos)
        self.assertEqual(r.status_code, 400)
        self.assertIn("falta marcar presente o ausente", r.text)

    def test_nino_de_otra_sala(self):
        datos = self._formulario(DIAS[10])
        datos[f"estado_{self.ajeno.id}"] = cfg.AUSENTE
        r = self.cliente.post("/registro", data=datos)
        self.assertEqual(r.status_code, 400)
        self.assertIn("no pertenece a esta sala", r.text)

    def test_sala_que_no_es_del_jardin(self):
        datos = self._formulario(DIAS[10])
        datos["sala_id"] = str(self.otra_sala.id)
        r = self.cliente.post("/registro", data=datos)
        self.assertEqual(r.status_code, 400)
        self.assertIn("La sala elegida no pertenece al jardín", r.text)

    def test_fecha_futura(self):
        manana = date.today() + timedelta(days=1)
        r = self._guardar(manana)
        self.assertEqual(r.status_code, 400)
        self.assertIn("día futuro", r.text)

    # --- El semáforo cambia al guardar ---------------------------------------

    def test_el_color_cambia_al_registrar_faltas(self):
        self.assertEqual(self._nivel(self._ver(DIAS[9]).text, self.n1), cfg.VERDE)

        r = self._guardar(DIAS[10], n1=(cfg.AUSENTE, cfg.SALUD))      # 1 de 11 = 9,1%
        self.assertEqual(self._nivel(r.text, self.n1), cfg.VERDE)

        r = self._guardar(DIAS[11], n1=(cfg.AUSENTE, cfg.SALUD))      # 2 de 12 = 16,7%
        self.assertEqual(self._nivel(r.text, self.n1), cfg.AMARILLO)
        self.assertIn("16,7% de faltas (2 de 12 días)", r.text)

        r = self._guardar(DIAS[12], n1=(cfg.AUSENTE, cfg.SIN_INFORMACION))  # 3 de 13 = 23,1%
        self.assertEqual(self._nivel(r.text, self.n1), cfg.ROJO)
        self.assertIn("faltas seguidas", r.text)   # alerta de racha
        self.assertEqual(self._nivel(r.text, self.n2), cfg.VERDE)  # el otro niño no cambia

    def test_corregir_una_falta_devuelve_el_color(self):
        self._guardar(DIAS[10], n1=(cfg.AUSENTE, cfg.SALUD))
        r = self._guardar(DIAS[11], n1=(cfg.AUSENTE, cfg.SALUD))
        self.assertEqual(self._nivel(r.text, self.n1), cfg.AMARILLO)
        r = self._guardar(DIAS[11])  # en realidad sí vino
        self.assertEqual(self._nivel(r.text, self.n1), cfg.VERDE)


class TestRegistroSinDatos(unittest.TestCase):
    def test_base_vacia_muestra_instrucciones(self):
        with tempfile.TemporaryDirectory() as carpeta:
            app.dependency_overrides[ruta_bd] = lambda: Path(carpeta) / "vacia.db"
            try:
                r = TestClient(app).get("/")
            finally:
                app.dependency_overrides.clear()
        self.assertEqual(r.status_code, 200)
        self.assertIn("python scripts/generar_datos.py", r.text)
        self.assertIn("Datos ficticios con fines académicos", r.text)


if __name__ == "__main__":
    unittest.main()
