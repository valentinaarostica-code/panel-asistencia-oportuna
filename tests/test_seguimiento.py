"""Pruebas de la regla de seguimiento de casos (funciones puras de app/seguimiento.py)."""

import unittest

from app import config as cfg
from app.seguimiento import (
    EN_SEGUIMIENTO,
    ESCALAR,
    MEJORA,
    SIN_MEJORA,
    SUGERIR_CIERRE,
    estado_caso,
    resultado_revision,
    resultados_del_caso,
    sin_mejora_seguidas,
)


class TestConstantes(unittest.TestCase):
    def test_constantes_nuevas(self):
        self.assertEqual(cfg.MEJORA_MIN_PUNTOS, 5)
        self.assertEqual(cfg.REVISIONES_SIN_MEJORA_ESCALA, 2)
        self.assertEqual(
            cfg.ACCIONES_SEGUIMIENTO,
            ("Llamado a la familia", "Visita al hogar", "Reunión con la familia",
             "Apoyo de traslado o transporte", "Derivación a red de apoyo"),
        )


class TestResultadoRevision(unittest.TestCase):
    def test_justo_5_puntos_es_mejora(self):
        self.assertEqual(resultado_revision(30.0, 25.0), MEJORA)

    def test_4_puntos_no_es_mejora(self):
        self.assertEqual(resultado_revision(30.0, 26.0), SIN_MEJORA)

    def test_casi_5_puntos_no_es_mejora(self):
        self.assertEqual(resultado_revision(30.0, 25.1), SIN_MEJORA)

    def test_5_puntos_con_errores_de_decimales_sigue_siendo_mejora(self):
        # 7 de 20 días = 35%, 6 de 20 días = 30%; en decimales 30.000000000000004.
        self.assertEqual(resultado_revision(7 / 20 * 100, 6 / 20 * 100), MEJORA)

    def test_mas_de_5_puntos_es_mejora(self):
        self.assertEqual(resultado_revision(50.0, 20.0), MEJORA)

    def test_subir_o_quedar_igual_no_es_mejora(self):
        self.assertEqual(resultado_revision(30.0, 30.0), SIN_MEJORA)
        self.assertEqual(resultado_revision(30.0, 40.0), SIN_MEJORA)


class TestResultadosDelCaso(unittest.TestCase):
    def test_la_primera_se_compara_con_la_apertura(self):
        self.assertEqual(resultados_del_caso(40.0, [35.0]), [MEJORA])
        self.assertEqual(resultados_del_caso(40.0, [36.0]), [SIN_MEJORA])

    def test_las_siguientes_se_comparan_con_la_anterior(self):
        # 40 → 35 mejora; 35 → 33 sin mejora (aunque está 7 puntos bajo la apertura).
        self.assertEqual(resultados_del_caso(40.0, [35.0, 33.0]), [MEJORA, SIN_MEJORA])

    def test_sin_revisiones(self):
        self.assertEqual(resultados_del_caso(40.0, []), [])


class TestEstadoCaso(unittest.TestCase):
    def test_dos_sin_mejora_seguidas_dan_escalar(self):
        resultados = resultados_del_caso(40.0, [39.0, 38.0])
        self.assertEqual(resultados, [SIN_MEJORA, SIN_MEJORA])
        self.assertEqual(estado_caso(resultados, cfg.ROJO), ESCALAR)

    def test_una_mejora_en_el_medio_reinicia_la_cuenta(self):
        resultados = [SIN_MEJORA, MEJORA, SIN_MEJORA]
        self.assertEqual(sin_mejora_seguidas(resultados), 1)
        self.assertEqual(estado_caso(resultados, cfg.ROJO), EN_SEGUIMIENTO)

    def test_despues_de_reiniciar_vuelve_a_escalar(self):
        resultados = [SIN_MEJORA, MEJORA, SIN_MEJORA, SIN_MEJORA]
        self.assertEqual(sin_mejora_seguidas(resultados), 2)
        self.assertEqual(estado_caso(resultados, cfg.ROJO), ESCALAR)

    def test_una_sola_sin_mejora_sigue_en_seguimiento(self):
        self.assertEqual(estado_caso([SIN_MEJORA], cfg.ROJO), EN_SEGUIMIENTO)
        self.assertEqual(estado_caso([MEJORA, MEJORA], cfg.ROJO), EN_SEGUIMIENTO)
        self.assertEqual(estado_caso([], cfg.ROJO), EN_SEGUIMIENTO)

    def test_si_ya_no_esta_en_rojo_se_sugiere_cierre(self):
        for nivel in (cfg.AMARILLO, cfg.VERDE):
            self.assertEqual(estado_caso([MEJORA], nivel), SUGERIR_CIERRE)

    def test_sugerir_cierre_gana_a_escalar(self):
        self.assertEqual(estado_caso([SIN_MEJORA, SIN_MEJORA], cfg.AMARILLO), SUGERIR_CIERRE)


if __name__ == "__main__":
    unittest.main()
