"""Pruebas de grafo.py y textos.py. Los epígrafes son reales (tomados de registros del monitor);
el texto articulado de `TEXTO_SINTETICO` es inventado solo para probar el segmentador y lo dice."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import grafo  # noqa: E402
import textos  # noqa: E402


def reg(**k):
    base = {"id": "x", "categoria": "Norma", "tipo": "Decreto", "numero": "", "fecha": "", "fecha_captura": "2026-11-01",
            "organo": "", "sala": "", "titulo": "", "resumen": "", "estado": "Expedida", "url": "https://dapre.presidencia.gov.co/x.pdf",
            "url_alterna": "", "verificacion": "V2 Registro oficial leído", "nota": "", "nivel": "Nacional"}
    base.update(k)
    return base


class Referencias(unittest.TestCase):
    def test_ley_y_articulo(self):
        r = grafo.relaciones_por_verbo("Por medio de la cual se modifica el artículo 88 de la Ley 1801 de 2016 garantizando el acceso")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["nombre"], "Ley 1801 de 2016")
        self.assertEqual(r[0]["verbos"], ["Modifica"])
        self.assertIn("artículo 88", r[0]["parte"])

    def test_varios_verbos_y_herencia(self):
        r = grafo.relaciones_por_verbo("Por el cual se derogan el Decreto 1047 de 2024 y el Decreto 0949 de 2025 y se restablece el régimen")
        self.assertEqual([x["nombre"] for x in r], ["Decreto 1047 de 2024", "Decreto 0949 de 2025"])
        self.assertTrue(all(x["verbos"] == ["Deroga"] for x in r))

    def test_participio_no_es_verbo(self):
        r = grafo.relaciones_por_verbo("Por el cual se liquidan los recursos adicionados en el Decreto 1412 de 2026 al Presupuesto")
        self.assertEqual(r[0]["verbos"], [])

    def test_bloqueo_en_el_marco(self):
        t = ("Por el cual se suspende transitoriamente la verificación de condicionalidades, en el marco del Estado de "
             "Emergencia declarado mediante el Decreto Legislativo 1261 de 2026")
        self.assertEqual(grafo.relaciones_por_verbo(t)[0]["verbos"], [])

    def test_fecha_completa_en_referencia(self):
        r = grafo.referencias("se modifica el Decreto 2442 del 18 de julio de 2006 en lo relacionado")
        self.assertEqual(r[0][2], "Decreto 2442 de 2006")

    def test_mes_sin_dia(self):
        self.assertEqual(grafo.referencias("Modificación del Acuerdo 050 de noviembre de 2025")[0][2], "Acuerdo 050 de 2025")

    def test_constitucion(self):
        r = grafo.relaciones_por_verbo("Proyecto de acto legislativo que modifica el artículo 197 de la Constitución")
        self.assertEqual(r[0]["nombre"], "Constitución Política")

    def test_imperativo(self):
        r = grafo.relaciones_por_verbo("ARTÍCULO 5. Modifíquese el artículo 2.2.1 del Decreto 1077 de 2015, el cual quedará así")
        self.assertEqual(r[0]["verbos"], ["Modifica"])


class Derivacion(unittest.TestCase):
    def test_relacion_epigrafe_oficial_es_sugerida_y_literal(self):
        r = reg(id="d1", numero="1490", fecha="2026-10-09", titulo="Por el cual se modifica el Decreto 2555 de 2010, en lo relacionado")
        rel = grafo.relaciones_de(r, {}, {})
        self.assertEqual(rel[0]["estado_validacion"], "Sugerida por IA")
        self.assertEqual(rel[0]["fragmento_literal"], "sí")

    def test_titulo_descriptivo_queda_pendiente(self):
        r = reg(id="d2", numero="1529", titulo="Decreto 1529 de 2026 — modificación del régimen portuario en el Decreto 1079 de 2015 (título descriptivo)")
        rel = grafo.relaciones_de(r, {}, {})
        self.assertEqual(rel[0]["estado_validacion"], "Pendiente de revisión")
        self.assertEqual(rel[0]["fragmento_literal"], "no")

    def test_no_se_relaciona_consigo_misma(self):
        r = reg(id="d3", tipo="Ley", numero="2640", fecha="2026-11-04", titulo="Ley 2640 de 2026 — modifica la Ley 418 de 1997")
        self.assertEqual([x["destino_ref"] for x in grafo.relaciones_de(r, {}, {})], ["Ley 418 de 1997"])

    def test_decision_sobre_la_norma_cercana(self):
        r = reg(id="j1", categoria="Jurisprudencia", tipo="Sentencia C", numero="C-273/26", estado="Decidida",
                resumen="Declara exequible la expresión «x» del art. 31 del Decreto Ley 196 de 1971, en el entendido de que aplica según la Ley 1905 de 2018.")
        rel = {x["destino_ref"]: x["tipo"] for x in grafo.relaciones_de(r, {}, {})}
        self.assertEqual(rel["Decreto Ley 196 de 1971"], "Declara exequible condicionado")
        self.assertEqual(rel["Ley 1905 de 2018"], "Cita o aplica norma")

    def test_proyecto_que_se_convirtio_en_ley(self):
        r = reg(id="p1", categoria="Proyecto", tipo="Proyecto de ley", estado="Sancionado (Ley 2640 de 2026, 4-nov-2026, según prensa)")
        rel = grafo.relaciones_de(r, grafo.indice_normas([reg(id="l1", tipo="Ley", numero="2640", fecha="2026-11-04")]), {})
        self.assertEqual(rel[0]["tipo"], "Se convirtió en")
        self.assertEqual(rel[0]["destino_id"], "l1")
        self.assertEqual(rel[0]["estado_validacion"], "Pendiente de revisión")

    def test_eventos_desde_estado_con_fecha(self):
        r = reg(id="p2", categoria="Proyecto", tipo="Proyecto de ley", fecha="",
                estado="Aprobado en primer debate (Comisiones Sextas Conjuntas, 29-oct-2026)")
        ev = grafo.eventos_de(r)
        self.assertIn(("2026-10-29", "Aprobación en primer debate"), [(e["fecha"], e["tipo_evento"]) for e in ev])

    def test_fecha_de_proyecto_es_radicacion_salvo_que_el_estado_diga_otra_cosa(self):
        self.assertEqual(grafo.evento_de_fecha(reg(categoria="Proyecto", tipo="Proyecto de ley", fecha="2026-10-29", estado="Radicado")), "Radicación")
        self.assertEqual(grafo.evento_de_fecha(reg(categoria="Proyecto", tipo="Proyecto de ley", fecha="2026-11-04",
                                                   estado="Aprobado en primer debate (Comisiones, 4-nov-2026)")), "Aprobación en primer debate")

    def test_fecha_de_vigencia_no_es_evento(self):
        r = reg(id="a1", tipo="Acuerdo", fecha="2026-10-08", estado="Expedida (según su texto rige desde el 9-oct-2026 y la sobretasa desde el 1-ene-2027)",
                nota="[4-nov-2026: estado normalizado; antes «Vigente (desde el 9-oct-2026)».]")
        self.assertEqual(sorted(e["fecha"] for e in grafo.eventos_de(r)), ["2026-10-08", "2026-11-01"])

    def test_no_hay_vigencia_inferida(self):
        r = reg(id="n1", numero="1", fecha="2026-10-01", estado="Expedida")
        self.assertNotIn("Entrada en vigencia", [e["tipo_evento"] for e in grafo.eventos_de(r)])

    def test_historial_desde_nota(self):
        r = reg(id="h1", nota="Algo. [4-nov-2026: estado normalizado; antes «Expedida (reportada)».]")
        h = grafo.historial_de_notas(r)
        self.assertEqual(h[0]["antes"], "Expedida (reportada)")
        self.assertEqual(h[0]["fecha"], "2026-11-04")


class Validacion(unittest.TestCase):
    def test_confirmada_exige_persona(self):
        x = grafo.nueva_relacion("a", "", "Ley 1 de 2020", "Modifica", "f", True, "https://x.gov.co", "Patrón sobre epígrafe oficial", "Confirmada")
        self.assertTrue(any("Confirmada" in e for e in grafo.validar("relacion", [x])))

    def test_ia_exige_fragmento_literal(self):
        x = grafo.nueva_relacion("a", "", "Ley 1 de 2020", "Modifica", "f", False, "https://x.gov.co", "Extracción por IA de fuente oficial", "Sugerida por IA")
        self.assertTrue(grafo.validar("relacion", [x]))

    def test_regla_juridica_exige_literal(self):
        x = {"id": "an-1", "doc_id": "a", "tipo": "Regla jurídica", "valor": "v", "fragmento": "f", "fragmento_literal": "no",
             "fuente_url": "https://x", "metodo": "Patrón sobre resumen del registro", "estado_validacion": "Pendiente de revisión"}
        self.assertTrue(grafo.validar("analisis", [x]))

    def test_validacion_humana_gana_y_se_conserva(self):
        nov = [reg(id="d1", numero="1490", fecha="2026-10-09", titulo="Por el cual se modifica el Decreto 2555 de 2010")]
        rid = grafo.relaciones_de(nov[0], {}, {})[0]["id"]
        with tempfile.TemporaryDirectory() as d:
            json.dump(nov, open(f"{d}/n.json", "w"))
            json.dump([{"objeto": "relacion", "id": rid, "decision": "confirmada", "at": "2026-11-05T10:00:00-05:00"}], open(f"{d}/v.json", "w"))
            args = type("A", (), dict(novedades=f"{d}/n.json", anterior=None, eventos=None, relaciones=None, analisis=None,
                                      historial=None, validaciones=f"{d}/v.json", fecha="2026-11-05", corrida="t", salida_dir=f"{d}/o"))
            self.assertEqual(grafo.procesar(args), 0)
            rel = json.load(open(f"{d}/o/relaciones.json"))
            self.assertEqual(rel[0]["estado_validacion"], "Confirmada")
            self.assertEqual(rel[0]["metodo"], "Validación humana")
            # Segunda pasada sin el archivo de validaciones: la confirmación no se pierde.
            args.relaciones, args.validaciones = f"{d}/o/relaciones.json", None
            self.assertEqual(grafo.procesar(args), 0)
            self.assertEqual(json.load(open(f"{d}/o/relaciones.json"))[0]["estado_validacion"], "Confirmada")

    def test_ids_estables(self):
        r = reg(id="d1", numero="1490", fecha="2026-10-09", titulo="Por el cual se modifica el Decreto 2555 de 2010")
        self.assertEqual(grafo.relaciones_de(r, {}, {})[0]["id"], grafo.relaciones_de(dict(r), {}, {})[0]["id"])


TEXTO_SINTETICO = """TEXTO DE PRUEBA SINTÉTICO (no es una norma real)
DECRETA:
ARTÍCULO 1. Objeto. El presente decreto tiene por objeto probar el segmentador.
ARTÍCULO 2. Modifíquese el artículo 2.2.1.1 del Decreto 1077 de 2015, el cual quedará así: texto.
PARÁGRAFO 1. Un parágrafo de prueba.
PARÁGRAFO 2. Otro parágrafo.
ARTÍCULO 3. Vigencia y derogatorias. El presente decreto rige a partir de la fecha de su publicación y deroga el artículo 4 del Decreto 999 de 2020.
"""


class Textos(unittest.TestCase):
    def test_segmenta_articulos_y_paragrafos(self):
        u = [x["unidad"] for x in textos.segmentar(TEXTO_SINTETICO)]
        self.assertEqual(u[1:], ["Artículo 1", "Artículo 2", "Artículo 2, parágrafo 1", "Artículo 2, parágrafo 2", "Artículo 3"])

    def test_relaciones_y_vigencia_literal(self):
        filas, rel, an = textos.procesar("doc", TEXTO_SINTETICO, "https://dapre.presidencia.gov.co/x.pdf", "abc", "2026-11-05")
        tipos = {(x["tipo"], x["destino_ref"]) for x in rel}
        self.assertIn(("Modifica", "Decreto 1077 de 2015"), tipos)
        self.assertIn(("Deroga", "Decreto 999 de 2020"), tipos)
        self.assertTrue(all(x["fragmento_literal"] == "sí" for x in rel))
        self.assertEqual(an[0]["tipo"], "Regla de vigencia")
        self.assertIn("rige a partir de la fecha de su publicación", an[0]["fragmento"])
        self.assertEqual(grafo.validar("relacion", rel) + grafo.validar("analisis", an), [])

    def test_sin_encabezados(self):
        self.assertEqual(textos.segmentar("Un texto sin artículos.")[0]["unidad"], "Texto")


if __name__ == "__main__":
    unittest.main()
