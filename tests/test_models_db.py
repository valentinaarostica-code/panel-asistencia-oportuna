"""Pruebas de las fichas (models) y de la base de datos (db)."""

import sqlite3
import unittest
from datetime import date

from app import config as cfg
from app import db
from app.models import Asistencia, Jardin, Nino, Sala


class TestAsistencia(unittest.TestCase):
    def test_ausencia_sin_motivo_queda_como_sin_informacion(self):
        a = Asistencia(nino_id=1, fecha=date(2026, 3, 2), estado=cfg.AUSENTE)
        self.assertEqual(a.motivo, cfg.SIN_INFORMACION)
        self.assertFalse(a.informado_por_familia)

    def test_ausencia_con_motivo_informado(self):
        a = Asistencia(1, date(2026, 3, 2), cfg.AUSENTE, cfg.SALUD)
        self.assertTrue(a.informado_por_familia)

    def test_presente_no_lleva_motivo(self):
        with self.assertRaises(ValueError):
            Asistencia(1, date(2026, 3, 2), cfg.PRESENTE, cfg.SALUD)

    def test_presente_normal(self):
        a = Asistencia(1, date(2026, 3, 2), cfg.PRESENTE)
        self.assertIsNone(a.motivo)
        self.assertFalse(a.informado_por_familia)

    def test_estado_invalido(self):
        with self.assertRaises(ValueError):
            Asistencia(1, date(2026, 3, 2), "tarde")

    def test_motivo_invalido(self):
        with self.assertRaises(ValueError):
            Asistencia(1, date(2026, 3, 2), cfg.AUSENTE, "Flojera")

    def test_fecha_debe_ser_date(self):
        with self.assertRaises(ValueError):
            Asistencia(1, "2026-03-02", cfg.PRESENTE)


class TestBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.conn = db.conectar(":memory:")
        db.crear_esquema(self.conn)

    def tearDown(self):
        self.conn.close()

    def _armar_jardin(self):
        jardin = Jardin("Jardín Prueba (ficticio)", "Antofagasta", "Antofagasta")
        db.insertar_jardin(self.conn, jardin)
        sala = Sala(jardin.id, "Medio menor")
        db.insertar_sala(self.conn, sala)
        nino = Nino("J01-N001", sala.id)
        db.insertar_nino(self.conn, nino)
        return jardin, sala, nino

    def test_guardar_y_leer(self):
        jardin, _, nino = self._armar_jardin()
        db.insertar_asistencias(
            self.conn,
            [
                Asistencia(nino.id, date(2026, 3, 4), cfg.AUSENTE, cfg.SALUD),
                Asistencia(nino.id, date(2026, 3, 2), cfg.PRESENTE),
                Asistencia(nino.id, date(2026, 3, 3), cfg.PRESENTE),
            ],
        )
        self.conn.commit()

        self.assertEqual(db.contar(self.conn, "jardin"), 1)
        self.assertEqual(db.contar(self.conn, "asistencia"), 3)
        # Los estados salen ordenados por fecha, no por orden de inserción.
        self.assertEqual(
            db.estados_por_nino(self.conn),
            {nino.id: [cfg.PRESENTE, cfg.PRESENTE, cfg.AUSENTE]},
        )
        fila = self.conn.execute(
            "SELECT motivo, informado_por_familia FROM asistencia WHERE estado = 'ausente'"
        ).fetchone()
        self.assertEqual((fila["motivo"], fila["informado_por_familia"]), (cfg.SALUD, 1))
        self.assertEqual(db.listar_jardines(self.conn)[0]["nombre"], jardin.nombre)
        self.assertEqual(db.ninos_de_jardin(self.conn, jardin.id)[0]["sala"], "Medio menor")

    def test_filtrar_por_jardin(self):
        j1, _, n1 = self._armar_jardin()
        j2 = Jardin("Otro Jardín (ficticio)", "Calama", "Antofagasta")
        db.insertar_jardin(self.conn, j2)
        s2 = Sala(j2.id, "Sala cuna")
        db.insertar_sala(self.conn, s2)
        n2 = Nino("J02-N001", s2.id)
        db.insertar_nino(self.conn, n2)
        db.insertar_asistencias(
            self.conn,
            [
                Asistencia(n1.id, date(2026, 3, 2), cfg.PRESENTE),
                Asistencia(n2.id, date(2026, 3, 2), cfg.AUSENTE),
            ],
        )
        self.assertEqual(list(db.estados_por_nino(self.conn, j1.id)), [n1.id])
        self.assertEqual(list(db.estados_por_nino(self.conn, j2.id)), [n2.id])
        self.assertEqual(len(db.estados_por_nino(self.conn)), 2)

    def test_no_se_repite_el_registro_de_un_dia(self):
        _, _, nino = self._armar_jardin()
        db.insertar_asistencias(self.conn, [Asistencia(nino.id, date(2026, 3, 2), cfg.PRESENTE)])
        with self.assertRaises(sqlite3.IntegrityError):
            db.insertar_asistencias(
                self.conn, [Asistencia(nino.id, date(2026, 3, 2), cfg.AUSENTE)]
            )

    def test_no_se_aceptan_ninos_de_una_sala_que_no_existe(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db.insertar_nino(self.conn, Nino("J99-N001", sala_id=999))

    def test_reiniciar_deja_todo_vacio(self):
        self._armar_jardin()
        db.reiniciar_esquema(self.conn)
        for tabla in ("jardin", "sala", "nino", "asistencia"):
            self.assertEqual(db.contar(self.conn, tabla), 0)

    def test_contar_rechaza_tablas_desconocidas(self):
        with self.assertRaises(ValueError):
            db.contar(self.conn, "usuarios; DROP TABLE jardin")


if __name__ == "__main__":
    unittest.main()
