"""Pruebas de la pantalla "Panel del jardín" (/panel en app/main.py).

Usan la base de demostración con semilla fija (tests/base_demo.py).
"""

import re
import unittest

from fastapi.testclient import TestClient

from app import config as cfg
from app import db
from app.main import _frase_resumen, app, ruta_bd
from app.rules import DESCRIPCION_ALERTA, ResumenJardin, evaluar_nino, resumen_jardin
from tests.base_demo import base_demo

PEQUENOS_PASOS = 3
RAYITO_DE_SOL = 1

PRIORIDAD = {cfg.ROJO: 0, "racha": 1, cfg.AMARILLO: 2, cfg.VERDE: 3, cfg.SIN_DATOS: 4}
ETIQUETAS = {cfg.VERDE: "Verde", cfg.AMARILLO: "Amarillo", cfg.ROJO: "Rojo", cfg.SIN_DATOS: "Sin datos"}


class TestPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruta, cls.memoria = base_demo()
        app.dependency_overrides[ruta_bd] = lambda: cls.ruta
        cls.cliente = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    # --- Ayudas -------------------------------------------------------------

    def _panel(self, **params):
        r = self.cliente.get("/panel", params=params)
        self.assertEqual(r.status_code, 200, r.text[:500])
        return r

    @staticmethod
    def _filas(html):
        """[(código, nivel, tiene_racha, html_de_la_fila), ...] en el orden de la tabla."""
        return [
            (codigo, nivel, racha == "1", cuerpo)
            for codigo, nivel, racha, cuerpo in re.findall(
                r'<tr data-codigo="([^"]+)" data-nivel="(\w+)" data-racha="(\d)">(.*?)</tr>',
                html, re.S,
            )
        ]

    def _resumen(self, jardin_id):
        """El resumen calculado directamente con rules, para comparar con la pantalla."""
        estados = db.estados_por_nino(self.memoria, jardin_id)
        return resumen_jardin(evaluar_nino(e) for e in estados.values())

    @staticmethod
    def _tarjetas(html):
        return re.findall(r'class="tarjeta-valor">([^<]+)<', html)

    # --- Pequeños Pasos: el promedio esconde a los niños en rojo ------------

    def test_pequenos_pasos_promedio_alto_con_ninos_en_rojo(self):
        r = self._panel(jardin_id=PEQUENOS_PASOS)
        self.assertIn("Pequeños Pasos", r.text)
        promedio_txt, rojos_txt = self._tarjetas(r.text)
        promedio = float(promedio_txt.strip().rstrip("%").replace(",", "."))
        self.assertGreaterEqual(promedio, 90)
        self.assertGreaterEqual(int(rojos_txt.strip()), 3)

        esperado = self._resumen(PEQUENOS_PASOS)
        self.assertEqual(int(rojos_txt.strip()), esperado.ninos_rojo)
        self.assertAlmostEqual(promedio, esperado.asistencia_promedio_pct, places=1)

    def test_pequenos_pasos_muestra_la_advertencia(self):
        r = self._panel(jardin_id=PEQUENOS_PASOS)
        self.assertIn('class="frase advertencia"', r.text)
        self.assertIn(
            "El promedio se ve bien (92,5%), pero 4 de 25 niños (16%) están en rojo.", r.text
        )

    def test_sin_advertencia_cuando_el_promedio_es_bajo(self):
        r = self._panel(jardin_id=RAYITO_DE_SOL)  # 83,5% de asistencia
        self.assertNotIn('class="frase advertencia"', r.text)
        self.assertIn("La asistencia promedio es 83,5% y 9 de 25 niños (36%) están en rojo.", r.text)

    def test_conteos_del_jardin(self):
        r = self._panel(jardin_id=RAYITO_DE_SOL)
        res = self._resumen(RAYITO_DE_SOL)
        for nivel, etiqueta in ETIQUETAS.items():
            self.assertIn(f"{etiqueta}: {getattr(res, 'ninos_' + nivel)}<", r.text)
        self.assertIn(f"Niños con alerta: {res.ninos_con_alerta}<", r.text)

    # --- Lista por prioridad -------------------------------------------------

    def test_orden_pone_primero_a_los_ninos_en_rojo(self):
        for jardin in (RAYITO_DE_SOL, PEQUENOS_PASOS):
            filas = self._filas(self._panel(jardin_id=jardin).text)
            self.assertEqual(len(filas), 25)
            rojos = self._resumen(jardin).ninos_rojo
            self.assertTrue(all(nivel == cfg.ROJO for _, nivel, _, _ in filas[:rojos]))
            self.assertTrue(all(nivel != cfg.ROJO for _, nivel, _, _ in filas[rojos:]))

    def test_orden_completo_rojo_racha_amarillo_verde(self):
        for jardin_id in range(1, 13):
            filas = self._filas(self._panel(jardin_id=jardin_id).text)
            prioridades = [
                PRIORIDAD[cfg.ROJO] if nivel == cfg.ROJO
                else PRIORIDAD["racha"] if racha
                else PRIORIDAD[nivel]
                for _, nivel, racha, _ in filas
            ]
            self.assertEqual(prioridades, sorted(prioridades), f"jardín {jardin_id}")

    def test_cada_fila_tiene_sus_datos_y_etiqueta_de_texto(self):
        r = self._panel(jardin_id=PEQUENOS_PASOS)
        codigo, nivel, _, fila = self._filas(r.text)[0]
        self.assertTrue(codigo.startswith("J03-N"))
        self.assertIn(f'<span class="semaforo {nivel}">{ETIQUETAS[nivel]}</span>', fila)
        self.assertRegex(fila, r'class="numero">\d+,\d%</td>')
        self.assertRegex(fila, r"\d+ ausencias? de \d+ días")
        self.assertIn(DESCRIPCION_ALERTA["RIESGO_ROJO"], fila)
        self.assertRegex(fila, r'href="/\?jardin_id=3&amp;sala_id=\d+"')

    # --- Filtros -------------------------------------------------------------

    def test_filtro_por_sala(self):
        sala = db.listar_salas(self.memoria, PEQUENOS_PASOS)[1]
        en_sala = {
            n["codigo"] for n in db.ninos_de_jardin(self.memoria, PEQUENOS_PASOS)
            if n["sala_id"] == sala["id"]
        }
        r = self._panel(jardin_id=PEQUENOS_PASOS, sala_id=sala["id"])
        filas = self._filas(r.text)
        self.assertEqual({codigo for codigo, *_ in filas}, en_sala)
        self.assertTrue(all(f"<td>{sala['nivel']}</td>" in cuerpo for *_, cuerpo in filas))
        # Las tarjetas siguen siendo del jardín completo.
        self.assertEqual(self._tarjetas(r.text)[0].strip(), "92,5%")

    def test_filtro_por_color(self):
        for nivel in cfg.NIVELES:
            filas = self._filas(self._panel(jardin_id=RAYITO_DE_SOL, color=nivel).text)
            self.assertEqual(len(filas), getattr(self._resumen(RAYITO_DE_SOL), "ninos_" + nivel))
            self.assertTrue(all(n == nivel for _, n, _, _ in filas))

    def test_filtro_solo_con_alerta(self):
        filas = self._filas(self._panel(jardin_id=PEQUENOS_PASOS, solo_alerta="1").text)
        self.assertEqual(len(filas), self._resumen(PEQUENOS_PASOS).ninos_con_alerta)
        self.assertTrue(all('class="alertas"' in cuerpo for *_, cuerpo in filas))

    def test_filtros_combinados(self):
        sala = db.listar_salas(self.memoria, RAYITO_DE_SOL)[0]
        r = self._panel(jardin_id=RAYITO_DE_SOL, sala_id=sala["id"], color=cfg.ROJO, solo_alerta="1")
        filas = self._filas(r.text)
        self.assertTrue(filas)
        for _, nivel, _, cuerpo in filas:
            self.assertEqual(nivel, cfg.ROJO)
            self.assertIn(f"<td>{sala['nivel']}</td>", cuerpo)
        self.assertIn("Quitar filtros", r.text)

    def test_filtros_invalidos_se_ignoran_con_aviso(self):
        sala_ajena = db.listar_salas(self.memoria, RAYITO_DE_SOL)[0]["id"]
        r = self._panel(jardin_id=PEQUENOS_PASOS, sala_id=sala_ajena, color="morado")
        self.assertEqual(len(self._filas(r.text)), 25)
        self.assertIn("no es de este jardín", r.text)
        self.assertIn("no existe: se muestran todos los colores", r.text)

    # --- Errores, navegación y aviso --------------------------------------------

    def test_jardin_que_no_existe_da_404(self):
        for valor in ("999", "abc"):
            r = self.cliente.get("/panel", params={"jardin_id": valor})
            self.assertEqual(r.status_code, 404)
            self.assertIn("No existe un jardín", r.text)
            self.assertIn("Datos ficticios con fines académicos", r.text)

    def test_sin_parametros_muestra_el_primer_jardin(self):
        r = self._panel()
        self.assertIn('selected>Jardín Rayito de Sol', r.text)

    def test_aviso_fecha_y_menu(self):
        r = self._panel(jardin_id=PEQUENOS_PASOS)
        self.assertIn("Datos ficticios con fines académicos", r.text)
        self.assertIn("Datos al: <strong>23-10-2026</strong>", r.text)
        self.assertIn('href="/?jardin_id=3" >Registro diario</a>', r.text)
        self.assertIn('href="/panel?jardin_id=3" aria-current="page">Panel del jardín</a>', r.text)

    def test_registro_tambien_tiene_menu(self):
        r = self.cliente.get("/", params={"jardin_id": PEQUENOS_PASOS})
        self.assertIn('href="/?jardin_id=3" aria-current="page">Registro diario</a>', r.text)
        self.assertIn('href="/panel?jardin_id=3" >Panel del jardín</a>', r.text)

    def test_enlace_lleva_al_registro_de_esa_sala(self):
        codigo, _, _, fila = self._filas(self._panel(jardin_id=PEQUENOS_PASOS).text)[0]
        enlace = re.search(r'href="(/\?[^"]+)"', fila).group(1).replace("&amp;", "&")
        r = self.cliente.get(enlace)
        self.assertEqual(r.status_code, 200)
        self.assertIn(codigo, r.text)


class TestFraseResumen(unittest.TestCase):
    def _resumen(self, **cambios):
        base = dict(
            ninos=25, asistencia_promedio_pct=92.5, ninos_verde=21, ninos_amarillo=0,
            ninos_rojo=4, ninos_sin_datos=0, pct_ninos_rojo=16.0,
            pct_ninos_en_riesgo=16.0, ninos_con_alerta=5,
        )
        base.update(cambios)
        return ResumenJardin(**base)

    def test_advertencia_desde_90(self):
        frase, advertencia = _frase_resumen(self._resumen(asistencia_promedio_pct=90.0))
        self.assertTrue(advertencia)
        self.assertTrue(frase.startswith("El promedio se ve bien (90,0%)"))

    def test_bajo_90_no_es_advertencia(self):
        _, advertencia = _frase_resumen(self._resumen(asistencia_promedio_pct=89.9))
        self.assertFalse(advertencia)

    def test_sin_rojos(self):
        frase, advertencia = _frase_resumen(
            self._resumen(ninos_rojo=0, ninos_verde=25, pct_ninos_rojo=0.0)
        )
        self.assertEqual(frase, "La asistencia promedio es 92,5% y ningún niño está en rojo.")
        self.assertFalse(advertencia)

    def test_un_solo_nino_en_rojo_y_algunos_sin_datos(self):
        frase, _ = _frase_resumen(
            self._resumen(ninos_rojo=1, ninos_verde=19, ninos_sin_datos=5, pct_ninos_rojo=5.0)
        )
        self.assertIn("pero 1 de 20 niños con semáforo (5%) está en rojo.", frase)

    def test_sin_datos(self):
        frase, advertencia = _frase_resumen(self._resumen(asistencia_promedio_pct=None))
        self.assertIn("Todavía no hay asistencia", frase)
        self.assertFalse(advertencia)


if __name__ == "__main__":
    unittest.main()
