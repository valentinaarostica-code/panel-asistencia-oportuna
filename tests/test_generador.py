"""Pruebas del generador de datos ficticios."""

import unittest
from datetime import date

from app import config as cfg
from app import db, rules
from scripts import generar_datos as gen


def volcar(conn):
    """Copia ordenada de toda la asistencia, para comparar dos bases."""
    return conn.execute(
        "SELECT nino_id, fecha, estado, motivo, informado_por_familia "
        "FROM asistencia ORDER BY nino_id, fecha"
    ).fetchall()


class TestDiasLectivos(unittest.TestCase):
    def test_solo_lunes_a_viernes(self):
        dias = gen.dias_lectivos(date(2026, 3, 2), date(2026, 3, 15))
        self.assertEqual(len(dias), 10)
        self.assertTrue(all(d.weekday() < 5 for d in dias))

    def test_sin_feriados(self):
        dias = gen.dias_lectivos(date(2026, 4, 1), date(2026, 4, 30))
        self.assertNotIn(date(2026, 4, 3), dias)

    def test_fechas_al_reves_dan_error(self):
        with self.assertRaises(ValueError):
            gen.dias_lectivos(date(2026, 5, 1), date(2026, 3, 1))


class TestGeneracionPequena(unittest.TestCase):
    """Una base chica y rápida para revisar la forma de los datos."""

    @classmethod
    def setUpClass(cls):
        cls.conn = db.conectar(":memory:")
        cls.inicio, cls.fin = date(2026, 3, 2), date(2026, 5, 29)
        cls.generados = gen.generar(
            cls.conn, semilla=1, n_jardines=4, ninos_por_jardin=10,
            inicio=cls.inicio, fin=cls.fin,
        )
        cls.n_dias = len(gen.dias_lectivos(cls.inicio, cls.fin))

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_cantidades(self):
        self.assertEqual(db.contar(self.conn, "jardin"), 4)
        self.assertEqual(db.contar(self.conn, "sala"), 4 * len(cfg.NIVELES_SALA))
        self.assertEqual(db.contar(self.conn, "nino"), 40)
        self.assertEqual(db.contar(self.conn, "asistencia"), 40 * self.n_dias)

    def test_cada_nino_tiene_un_registro_por_dia_de_clases(self):
        for estados in db.estados_por_nino(self.conn).values():
            self.assertEqual(len(estados), self.n_dias)

    def test_los_jardines_se_marcan_como_ficticios(self):
        for jardin in db.listar_jardines(self.conn):
            self.assertIn("(ficticio)", jardin["nombre"])

    def test_los_ninos_son_seudonimos(self):
        for jardin in db.listar_jardines(self.conn):
            for nino in db.ninos_de_jardin(self.conn, jardin["id"]):
                self.assertRegex(nino["codigo"], r"^J\d{2}-N\d{3}$")

    def test_nunca_hay_clases_en_fin_de_semana_ni_feriado(self):
        for (texto,) in self.conn.execute("SELECT DISTINCT fecha FROM asistencia"):
            d = date.fromisoformat(texto)
            self.assertLess(d.weekday(), 5)
            self.assertNotIn(d, gen.FERIADOS_APROXIMADOS)

    def test_motivos_validos_y_solo_en_ausencias(self):
        for fila in volcar(self.conn):
            if fila["estado"] == cfg.PRESENTE:
                self.assertIsNone(fila["motivo"])
                self.assertEqual(fila["informado_por_familia"], 0)
            else:
                self.assertIn(fila["motivo"], cfg.MOTIVOS)
                self.assertEqual(
                    fila["informado_por_familia"],
                    int(fila["motivo"] != cfg.SIN_INFORMACION),
                )

    def test_las_ausencias_existen_pero_no_son_la_mayoria(self):
        total = db.contar(self.conn, "asistencia")
        ausentes = self.conn.execute(
            "SELECT COUNT(*) FROM asistencia WHERE estado = 'ausente'"
        ).fetchone()[0]
        self.assertGreater(ausentes, 0)
        self.assertLess(ausentes / total, 0.4)

    def test_el_resumen_de_jardines_viene_en_orden(self):
        self.assertEqual([g.escenario for g in self.generados],
                         ["mejora", "cae", "promedio_oculta", "estable"])


class TestDeterminismo(unittest.TestCase):
    def _generar(self, semilla):
        conn = db.conectar(":memory:")
        gen.generar(conn, semilla=semilla, n_jardines=2, ninos_por_jardin=8,
                    inicio=date(2026, 3, 2), fin=date(2026, 4, 30))
        datos = [tuple(f) for f in volcar(conn)]
        conn.close()
        return datos

    def test_misma_semilla_mismos_datos(self):
        self.assertEqual(self._generar(5), self._generar(5))

    def test_otra_semilla_otros_datos(self):
        self.assertNotEqual(self._generar(5), self._generar(6))

    def test_se_puede_regenerar_sobre_la_misma_base(self):
        conn = db.conectar(":memory:")
        for _ in range(2):
            gen.generar(conn, n_jardines=2, ninos_por_jardin=5,
                        inicio=date(2026, 3, 2), fin=date(2026, 3, 20))
        self.assertEqual(db.contar(conn, "nino"), 10)  # no se duplicó nada
        conn.close()


class TestParametrosInvalidos(unittest.TestCase):
    def setUp(self):
        self.conn = db.conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_demasiados_jardines(self):
        with self.assertRaises(ValueError):
            gen.generar(self.conn, n_jardines=99)

    def test_cero_ninos(self):
        with self.assertRaises(ValueError):
            gen.generar(self.conn, ninos_por_jardin=0)

    def test_sin_dias_de_clases(self):
        with self.assertRaises(ValueError):  # un sábado y un domingo
            gen.generar(self.conn, inicio=date(2026, 3, 7), fin=date(2026, 3, 8))


class TestEscenariosCompletos(unittest.TestCase):
    """Con los valores por defecto (12 jardines x 25 niños), como en la demo."""

    @classmethod
    def setUpClass(cls):
        cls.conn = db.conectar(":memory:")
        gen.generar(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def _tasa_por_tercio(self, jardin_id):
        filas = self.conn.execute(
            "SELECT a.fecha, a.estado FROM asistencia a "
            "JOIN nino n ON n.id = a.nino_id JOIN sala s ON s.id = n.sala_id "
            "WHERE s.jardin_id = ?", (jardin_id,),
        ).fetchall()
        fechas = sorted({f["fecha"] for f in filas})
        k = len(fechas) // 3
        tercios = [set(fechas[:k]), set(fechas[2 * k:])]
        tasas = []
        for tercio in tercios:
            sub = [f["estado"] for f in filas if f["fecha"] in tercio]
            tasas.append(sub.count(cfg.AUSENTE) / len(sub) * 100)
        return tasas  # [inicio, final]

    def test_cantidades_por_defecto(self):
        self.assertEqual(db.contar(self.conn, "jardin"), 12)
        self.assertEqual(db.contar(self.conn, "nino"), 300)

    def test_jardin_que_mejora(self):
        inicio, final = self._tasa_por_tercio(1)
        self.assertLess(final, inicio)

    def test_jardin_que_cae(self):
        inicio, final = self._tasa_por_tercio(2)
        self.assertGreater(final, inicio)

    def test_jardin_con_promedio_que_oculta_ninos_en_rojo(self):
        resultados = [
            rules.evaluar_nino(e)
            for e in db.estados_por_nino(self.conn, jardin_id=3).values()
        ]
        resumen = rules.resumen_jardin(resultados)
        self.assertGreaterEqual(resumen.asistencia_promedio_pct, 90)  # "se ve bien"
        self.assertGreaterEqual(resumen.ninos_rojo, 3)                # pero hay casos graves

    def test_hay_de_todo_para_probar_las_alertas(self):
        niveles, alertas = set(), set()
        for estados in db.estados_por_nino(self.conn).values():
            r = rules.evaluar_nino(estados)
            niveles.add(r.nivel)
            alertas.update(r.alertas)
        self.assertTrue({cfg.VERDE, cfg.AMARILLO, cfg.ROJO} <= niveles)
        self.assertTrue(
            {rules.ALERTA_RACHA, rules.ALERTA_TENDENCIA,
             rules.ALERTA_AMARILLO, rules.ALERTA_ROJO} <= alertas
        )


if __name__ == "__main__":
    unittest.main()
