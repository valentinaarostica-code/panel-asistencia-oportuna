"""Pruebas de la pantalla "Panel de la Subdirección" (/subdireccion en app/main.py).

Usan la base de demostración con semilla fija (tests/base_demo.py).
"""

import re
import unittest

from fastapi.testclient import TestClient

from app import config as cfg
from app import db
from app.main import _puestos, _senal, app, ruta_bd
from app.rules import ResumenJardin, evaluar_nino, resumen_jardin
from tests.base_demo import base_demo

SENAL = "Promedio que oculta casos graves"
PEQUENOS_PASOS = 3

# Columnas de cada fila de jardines (en el orden de la tabla).
COLUMNAS = (
    "nombre", "comuna", "region", "ninos", "promedio", "puesto_promedio",
    "verde", "amarillo", "rojo", "sin_datos", "pct_rojo", "puesto_rojo",
    "pct_riesgo", "alerta", "senal",
)
COLUMNAS_TOTAL = (
    "titulo", "ninos", "promedio", "", "verde", "amarillo", "rojo", "sin_datos",
    "pct_rojo", "", "pct_riesgo", "alerta", "",
)
ENTEROS = ("ninos", "verde", "amarillo", "rojo", "sin_datos", "alerta")


def _texto(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _celdas(html_fila):
    return [_texto(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", html_fila, re.S)]


def _pct(texto):
    return float(texto.rstrip("%").replace(",", "."))


class TestSubdireccion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruta, cls.memoria = base_demo()
        app.dependency_overrides[ruta_bd] = lambda: cls.ruta
        cls.cliente = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    # --- Ayudas -------------------------------------------------------------

    def _ver(self, **params):
        r = self.cliente.get("/subdireccion", params=params)
        self.assertEqual(r.status_code, 200, r.text[:500])
        return r.text

    def _filas(self, html):
        filas = []
        for jid, senal, cuerpo in re.findall(
            r'<tr data-jardin="(\d+)"( class="con-senal")?>(.*?)</tr>', html, re.S
        ):
            fila = dict(zip(COLUMNAS, _celdas(cuerpo)))
            fila["id"] = int(jid)
            fila["marcada"] = bool(senal)
            for c in ENTEROS:
                fila[c] = int(fila[c])
            filas.append(fila)
        return filas

    def _total(self, html):
        cuerpo = re.search(r'<tr class="totales">(.*?)</tr>', html, re.S).group(1)
        total = dict(zip(COLUMNAS_TOTAL, _celdas(cuerpo)))
        for c in ENTEROS:
            total[c] = int(total[c])
        return total

    def _resumen_de(self, jardin_ids):
        resultados = []
        for jid in jardin_ids:
            estados = db.estados_por_nino(self.memoria, jid)
            resultados += [
                evaluar_nino(estados.get(n["id"], []))
                for n in db.ninos_de_jardin(self.memoria, jid)
            ]
        return resumen_jardin(resultados)

    # --- Tabla y totales ------------------------------------------------------

    def test_salen_los_12_jardines_y_300_ninos(self):
        filas = self._filas(self._ver())
        self.assertEqual(len(filas), 12)
        self.assertEqual({f["id"] for f in filas}, set(range(1, 13)))
        self.assertEqual(sum(f["ninos"] for f in filas), 300)

    def test_fila_de_totales_coincide_con_la_suma(self):
        html = self._ver()
        filas, total = self._filas(html), self._total(html)
        self.assertEqual(total["titulo"], "Total de la red")
        for c in ENTEROS:
            self.assertEqual(total[c], sum(f[c] for f in filas), c)
        self.assertEqual(
            total["ninos"],
            total["verde"] + total["amarillo"] + total["rojo"] + total["sin_datos"],
        )
        # El promedio total es el de todos los niños (no el promedio de los promedios).
        red = self._resumen_de(range(1, 13))
        self.assertAlmostEqual(_pct(total["promedio"]), red.asistencia_promedio_pct, places=1)
        self.assertAlmostEqual(_pct(total["pct_rojo"]), red.pct_ninos_rojo, places=1)

    def test_cada_fila_coincide_con_resumen_jardin(self):
        for f in self._filas(self._ver()):
            res = self._resumen_de([f["id"]])
            self.assertEqual(f["rojo"], res.ninos_rojo)
            self.assertEqual(f["alerta"], res.ninos_con_alerta)
            self.assertAlmostEqual(_pct(f["promedio"]), res.asistencia_promedio_pct, places=1)
            self.assertAlmostEqual(_pct(f["pct_riesgo"]), res.pct_ninos_en_riesgo, places=1)

    def test_tarjetas_de_la_red(self):
        html = self._ver()
        valores = re.findall(r'class="tarjeta-valor">([^<]+)<', html)
        red = self._resumen_de(range(1, 13))
        self.assertEqual(valores[0], "300")
        self.assertAlmostEqual(_pct(valores[1]), red.pct_ninos_rojo, places=1)
        self.assertEqual(valores[2], "1")  # solo Pequeños Pasos

    # --- Señal y puestos --------------------------------------------------------

    def test_pequenos_pasos_tiene_la_senal(self):
        filas = {f["id"]: f for f in self._filas(self._ver())}
        pp = filas[PEQUENOS_PASOS]
        self.assertIn("Pequeños Pasos", pp["nombre"])
        self.assertIn(SENAL, pp["senal"])
        self.assertTrue(pp["marcada"])
        con_senal = [f["id"] for f in filas.values() if SENAL in f["senal"]]
        self.assertEqual(con_senal, [PEQUENOS_PASOS])

    def test_puestos_de_pequenos_pasos_muestran_la_brecha(self):
        pp = {f["id"]: f for f in self._filas(self._ver())}[PEQUENOS_PASOS]
        self.assertEqual(pp["puesto_promedio"], "1º")
        self.assertEqual(pp["puesto_rojo"], "9º (empate)")

    def test_puestos_son_coherentes_con_los_valores(self):
        filas = self._filas(self._ver())
        puesto = lambda t: int(t.split("º")[0])
        mejor_promedio = max(filas, key=lambda f: _pct(f["promedio"]))
        self.assertEqual(puesto(mejor_promedio["puesto_promedio"]), 1)
        for a in filas:
            for b in filas:
                if _pct(a["pct_rojo"]) > _pct(b["pct_rojo"]):
                    self.assertLess(puesto(a["puesto_rojo"]), puesto(b["puesto_rojo"]))

    # --- Orden -----------------------------------------------------------------

    def test_orden_por_defecto_es_pct_rojo_de_mayor_a_menor(self):
        filas = self._filas(self._ver())
        claves = [(-_pct(f["pct_rojo"]), f["nombre"].casefold()) for f in filas]
        self.assertEqual(claves, sorted(claves))

    def test_orden_invalido_usa_el_orden_por_defecto(self):
        por_defecto = [f["id"] for f in self._filas(self._ver())]
        for params in ({"orden": "xyz"}, {"orden": "xyz", "dir": "asc"},
                       {"dir": "xyz"}, {"orden": "rojo", "dir": "xyz"}):
            self.assertEqual([f["id"] for f in self._filas(self._ver(**params))], por_defecto, params)

    def test_ordenes_validos(self):
        casos = {
            "promedio": lambda f: _pct(f["promedio"]),
            "riesgo": lambda f: _pct(f["pct_riesgo"]),
            "rojo": lambda f: _pct(f["pct_rojo"]),
            "alerta": lambda f: f["alerta"],
            "ninos": lambda f: f["ninos"],
            "nombre": lambda f: f["nombre"].casefold(),
        }
        for orden, leer in casos.items():
            for direccion in ("asc", "desc"):
                valores = [leer(f) for f in self._filas(self._ver(orden=orden, dir=direccion))]
                self.assertEqual(valores, sorted(valores, reverse=(direccion == "desc")),
                                 f"{orden} {direccion}")

    def test_promedio_ascendente_pone_primero_la_peor_asistencia(self):
        filas = self._filas(self._ver(orden="promedio", dir="asc"))
        self.assertEqual(filas[-1]["id"], PEQUENOS_PASOS)  # el mejor promedio queda al final
        self.assertIn('aria-sort="ascending"', self._ver(orden="promedio", dir="asc"))

    # --- Filtro por región -----------------------------------------------------

    def test_filtro_por_region(self):
        html = self._ver(region="Antofagasta")
        filas = self._filas(html)
        esperados = {j["id"] for j in db.listar_jardines(self.memoria) if j["region"] == "Antofagasta"}
        self.assertEqual({f["id"] for f in filas}, esperados)
        self.assertTrue(all(f["region"] == "Antofagasta" for f in filas))

        total = self._total(html)
        self.assertEqual(total["titulo"], "Total Antofagasta")
        self.assertEqual(total["ninos"], sum(f["ninos"] for f in filas))
        self.assertEqual(total["rojo"], sum(f["rojo"] for f in filas))
        # Las tarjetas siguen siendo de toda la red y los puestos no cambian.
        self.assertEqual(re.findall(r'class="tarjeta-valor">([^<]+)<', html)[0], "300")
        pp = {f["id"]: f for f in filas}[PEQUENOS_PASOS]
        self.assertEqual((pp["puesto_promedio"], pp["puesto_rojo"]), ("1º", "9º (empate)"))

    def test_filtro_y_orden_juntos(self):
        filas = self._filas(self._ver(region="Antofagasta", orden="nombre", dir="asc"))
        nombres = [f["nombre"].casefold() for f in filas]
        self.assertEqual(nombres, sorted(nombres))
        self.assertTrue(all(f["region"] == "Antofagasta" for f in filas))

    def test_region_invalida_muestra_todas_con_aviso(self):
        html = self._ver(region="Atlántida")
        self.assertEqual(len(self._filas(html)), 12)
        self.assertIn("La región «Atlántida» no existe", html)

    # --- Navegación y aviso -------------------------------------------------------

    def test_aviso_fecha_menu_y_enlaces(self):
        html = self._ver()
        self.assertIn("Datos ficticios con fines académicos", html)
        self.assertIn("Datos al: <strong>23-10-2026</strong>", html)
        self.assertIn('href="/subdireccion" aria-current="page">Panel de la Subdirección</a>', html)
        self.assertIn('href="/" >Registro diario</a>', html)
        self.assertIn('href="/panel" >Panel del jardín</a>', html)
        for jid in range(1, 13):
            self.assertIn(f'<a href="/panel?jardin_id={jid}">', html)

    def test_enlace_al_panel_del_jardin(self):
        r = self.cliente.get(f"/panel?jardin_id={PEQUENOS_PASOS}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Pequeños Pasos", r.text)

    def test_colores_con_texto(self):
        html = self._ver()
        for clase, texto in (("verde", "Verde"), ("amarillo", "Amarillo"),
                             ("rojo", "Rojo"), ("sin_datos", "Sin datos")):
            self.assertIn(f'<span class="semaforo {clase}">{texto}</span>', html)

    def test_las_otras_pantallas_tienen_el_menu_completo(self):
        for ruta in ("/", "/panel"):
            self.assertIn("Panel de la Subdirección</a>", self.cliente.get(ruta).text)


class TestSenalYPuestos(unittest.TestCase):
    def _resumen(self, promedio, rojos):
        return ResumenJardin(
            ninos=25, asistencia_promedio_pct=promedio, ninos_verde=25 - rojos,
            ninos_amarillo=0, ninos_rojo=rojos, ninos_sin_datos=0,
            pct_ninos_rojo=rojos / 25 * 100, pct_ninos_en_riesgo=rojos / 25 * 100,
            ninos_con_alerta=rojos,
        )

    def test_constantes_nuevas_de_config(self):
        self.assertEqual(cfg.UMBRAL_PROMEDIO_ALTO_PCT, 90)
        self.assertEqual(cfg.MIN_ROJOS_ALERTA_JARDIN, 3)

    def test_senal_en_el_limite(self):
        self.assertEqual(_senal(self._resumen(90.0, 3)), SENAL)
        self.assertEqual(_senal(self._resumen(100 - 10.000000000000002, 3)), SENAL)
        self.assertIsNone(_senal(self._resumen(89.9, 3)))
        self.assertIsNone(_senal(self._resumen(95.0, 2)))
        self.assertIsNone(_senal(self._resumen(None, 5)))

    def test_puestos_con_empates(self):
        self.assertEqual(
            _puestos({1: 40.0, 2: 40.0, 3: 36.0, 4: None}),
            {1: (1, True), 2: (1, True), 3: (3, False), 4: (None, False)},
        )


if __name__ == "__main__":
    unittest.main()
