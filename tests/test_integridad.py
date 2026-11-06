"""Pruebas de integridad.py con datos mínimos."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import grafo  # noqa: E402
import integridad  # noqa: E402

REG = {"id": "d1", "categoria": "Norma", "tipo": "Decreto", "numero": "1", "fecha": "2026-10-01", "fecha_captura": "2026-10-02",
       "organo": "Presidencia de la República", "sala": "", "titulo": "Por el cual se modifica el Decreto 2 de 2020", "resumen": "r",
       "estado": "Expedida", "url": "https://dapre.presidencia.gov.co/x.pdf", "url_alterna": "", "verificacion": "V2 Registro oficial leído", "nota": ""}


class Integridad(unittest.TestCase):
    def armar(self, d, **extra):
        ds = {"novedades": [REG], "eventos": grafo.eventos_de(REG), "relaciones": grafo.relaciones_de(REG, {}, {}), "analisis": [], "historial": [],
              "trazabilidad": grafo.trazabilidad([REG], [], [], [], [], [], "2026-11-05")}
        ds.update(extra)
        for n, x in ds.items():
            json.dump(x, open(os.path.join(d, n + ".json"), "w"))

    def test_limpio(self):
        with tempfile.TemporaryDirectory() as d:
            self.armar(d)
            E, A, R = integridad.revisar(d, "2026-11-05", validar_registro=False)
            self.assertEqual(E, [])

    def test_destino_inexistente_y_confirmada_sin_persona(self):
        rel = grafo.relaciones_de(REG, {}, {})
        rel[0]["destino_id"] = "no-existe"
        rel[0]["estado_validacion"] = "Confirmada"
        with tempfile.TemporaryDirectory() as d:
            self.armar(d, relaciones=rel)
            E, _, _ = integridad.revisar(d, "2026-11-05", validar_registro=False)
            self.assertTrue(any("destino_id inexistentes" in e for e in E))
            self.assertTrue(any("sin validación humana" in e for e in E))

    def test_trazabilidad_incompleta(self):
        with tempfile.TemporaryDirectory() as d:
            self.armar(d, trazabilidad=[])
            E, _, _ = integridad.revisar(d, "2026-11-05", validar_registro=False)
            self.assertTrue(any("trazabilidad" in e for e in E))


if __name__ == "__main__":
    unittest.main()
