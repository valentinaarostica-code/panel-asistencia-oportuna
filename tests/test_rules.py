"""Pruebas de las reglas del semáforo y las alertas.

Se ejecutan con:   python -m unittest discover -s tests -t . -v
(o con pytest, si está instalado:   pytest)
"""

import unittest

from app import config as cfg
from app import rules

P, A = cfg.PRESENTE, cfg.AUSENTE


def estados(presentes: int, ausentes: int, al_final_ausentes: bool = False):
    """Arma una lista de estados. Por defecto, las ausencias quedan repartidas."""
    if al_final_ausentes:
        return [P] * presentes + [A] * ausentes
    lista = [P] * (presentes + ausentes)
    paso = max((presentes + ausentes) // max(ausentes, 1), 1)
    puestas = 0
    i = 0
    while puestas < ausentes and i < len(lista):
        lista[i] = A
        puestas += 1
        i += paso
    return lista


class TestPorcentaje(unittest.TestCase):
    def test_porcentaje_basico(self):
        self.assertEqual(rules.porcentaje_inasistencia(2, 20), 10.0)

    def test_sin_dias_es_cero(self):
        self.assertEqual(rules.porcentaje_inasistencia(0, 0), 0.0)


class TestNivel(unittest.TestCase):
    def test_menos_de_10_es_verde(self):
        self.assertEqual(rules.calcular_nivel(1, 20), cfg.VERDE)       # 5%
        self.assertEqual(rules.calcular_nivel(2, 21), cfg.VERDE)       # 9,5%

    def test_exactamente_10_es_amarillo(self):
        self.assertEqual(rules.calcular_nivel(2, 20), cfg.AMARILLO)    # 10%
        self.assertEqual(rules.calcular_nivel(3, 30), cfg.AMARILLO)    # 10%
        self.assertEqual(rules.calcular_nivel(16, 160), cfg.AMARILLO)  # 10%

    def test_entre_10_y_20_es_amarillo(self):
        self.assertEqual(rules.calcular_nivel(3, 20), cfg.AMARILLO)    # 15%
        self.assertEqual(rules.calcular_nivel(19, 100), cfg.AMARILLO)  # 19%

    def test_desde_20_es_rojo(self):
        self.assertEqual(rules.calcular_nivel(4, 20), cfg.ROJO)        # 20%
        self.assertEqual(rules.calcular_nivel(6, 30), cfg.ROJO)        # 20%
        self.assertEqual(rules.calcular_nivel(50, 100), cfg.ROJO)      # 50%

    def test_con_pocos_dias_no_hay_semaforo(self):
        self.assertEqual(rules.calcular_nivel(1, cfg.MIN_DIAS_LECTIVOS - 1), cfg.SIN_DATOS)
        self.assertEqual(rules.calcular_nivel(0, 0), cfg.SIN_DATOS)

    def test_con_el_minimo_de_dias_si_hay_semaforo(self):
        self.assertEqual(rules.calcular_nivel(0, cfg.MIN_DIAS_LECTIVOS), cfg.VERDE)


class TestRacha(unittest.TestCase):
    def test_racha_al_final(self):
        self.assertEqual(rules.racha_actual([P, A, P, A, A, A]), 3)

    def test_sin_racha_si_el_ultimo_dia_asistio(self):
        self.assertEqual(rules.racha_actual([A, A, A, P]), 0)

    def test_lista_vacia(self):
        self.assertEqual(rules.racha_actual([]), 0)


class TestEvaluarNino(unittest.TestCase):
    def test_nino_regular_sin_alertas(self):
        r = rules.evaluar_nino(estados(98, 2))
        self.assertEqual(r.nivel, cfg.VERDE)
        self.assertEqual(r.alertas, ())
        self.assertFalse(r.tiene_alerta)

    def test_nino_amarillo(self):
        r = rules.evaluar_nino(estados(85, 15))  # 15%
        self.assertEqual(r.nivel, cfg.AMARILLO)
        self.assertIn(rules.ALERTA_AMARILLO, r.alertas)

    def test_nino_rojo(self):
        r = rules.evaluar_nino(estados(70, 30))  # 30%
        self.assertEqual(r.nivel, cfg.ROJO)
        self.assertIn(rules.ALERTA_ROJO, r.alertas)
        self.assertNotIn(rules.ALERTA_AMARILLO, r.alertas)

    def test_racha_da_alerta_aunque_el_semaforo_este_verde(self):
        e = [P] * 97 + [A] * 3  # 3% en el año, pero 3 faltas seguidas hoy
        r = rules.evaluar_nino(e)
        self.assertEqual(r.nivel, cfg.VERDE)
        self.assertEqual(r.racha_actual, 3)
        self.assertIn(rules.ALERTA_RACHA, r.alertas)

    def test_dos_faltas_seguidas_no_dan_alerta_de_racha(self):
        r = rules.evaluar_nino([P] * 98 + [A] * 2)
        self.assertNotIn(rules.ALERTA_RACHA, r.alertas)

    def test_tendencia_nino_verde_que_empeora(self):
        # 160 días sin faltar y luego 20 días con 5 faltas repartidas (25% reciente)
        reciente = [P, P, P, A, P, P, A, P, P, A, P, P, A, P, P, A, P, P, P, P]
        r = rules.evaluar_nino([P] * 160 + reciente)
        self.assertEqual(r.nivel, cfg.VERDE)
        self.assertEqual(r.pct_reciente, 25.0)
        self.assertIn(rules.ALERTA_TENDENCIA, r.alertas)

    def test_sin_tendencia_si_lo_reciente_esta_bien(self):
        r = rules.evaluar_nino([P] * 180)
        self.assertNotIn(rules.ALERTA_TENDENCIA, r.alertas)

    def test_pocos_dias_sin_semaforo_pero_con_racha(self):
        r = rules.evaluar_nino([P, A, A, A])
        self.assertEqual(r.nivel, cfg.SIN_DATOS)
        self.assertIn(rules.ALERTA_RACHA, r.alertas)

    def test_estado_desconocido_da_error(self):
        with self.assertRaises(ValueError):
            rules.evaluar_nino([P, "faltó", A])

    def test_lista_vacia(self):
        r = rules.evaluar_nino([])
        self.assertEqual(r.nivel, cfg.SIN_DATOS)
        self.assertEqual(r.dias_lectivos, 0)


class TestResumenJardin(unittest.TestCase):
    def test_el_promedio_esconde_a_los_ninos_en_rojo(self):
        """La brecha del proyecto: buen promedio con niños en rojo escondidos."""
        buenos = [rules.evaluar_nino([P] * 100) for _ in range(21)]
        criticos = [rules.evaluar_nino([P] * 70 + [A] * 30) for _ in range(4)]
        resumen = rules.resumen_jardin(buenos + criticos)

        self.assertGreaterEqual(resumen.asistencia_promedio_pct, 94)  # "se ve bien"
        self.assertEqual(resumen.ninos_rojo, 4)                        # pero hay 4 en rojo
        self.assertEqual(resumen.pct_ninos_rojo, 16.0)

    def test_conteos_y_porcentajes(self):
        resultados = (
            [rules.evaluar_nino([P] * 100)] * 5
            + [rules.evaluar_nino([P] * 85 + [A] * 15)] * 3
            + [rules.evaluar_nino([P] * 70 + [A] * 30)] * 2
        )
        r = rules.resumen_jardin(resultados)
        self.assertEqual((r.ninos, r.ninos_verde, r.ninos_amarillo, r.ninos_rojo), (10, 5, 3, 2))
        self.assertEqual(r.pct_ninos_rojo, 20.0)
        self.assertEqual(r.pct_ninos_en_riesgo, 50.0)

    def test_los_ninos_sin_datos_no_cuentan_para_los_porcentajes(self):
        resultados = [rules.evaluar_nino([P] * 100), rules.evaluar_nino([A, A])]
        r = rules.resumen_jardin(resultados)
        self.assertEqual(r.ninos_sin_datos, 1)
        self.assertEqual(r.pct_ninos_rojo, 0.0)

    def test_jardin_sin_ninos(self):
        r = rules.resumen_jardin([])
        self.assertEqual(r.ninos, 0)
        self.assertIsNone(r.asistencia_promedio_pct)
        self.assertEqual(r.pct_ninos_rojo, 0.0)


if __name__ == "__main__":
    unittest.main()
