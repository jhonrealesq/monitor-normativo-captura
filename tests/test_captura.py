"""Pruebas de captura, corpus, pendientes y estados de confiabilidad (v1.11). Sin red: todo con datos locales."""
import json
import os
import sys
import tempfile
import unittest
import urllib.robotparser

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import captura  # noqa: E402
import corpus  # noqa: E402
import grafo  # noqa: E402
import pendientes  # noqa: E402
import textos  # noqa: E402

LEY = """LEY 9 DE 2026
EL CONGRESO DE COLOMBIA
DECRETA:
ARTÍCULO 1o. Objeto. La presente ley regula el trámite.
Notas de Vigencia
- Artículo modificado por el artículo 3 de la Ley 2400 de 2026, publicada en el Diario Oficial No. 53.000.
ARTÍCULO 2o. Modifícase el artículo 5 de la Ley 100 de 1993, el cual quedará así:
PARÁGRAFO 1. Transitorio.
ARTÍCULO 3o. Vigencia. La presente ley rige a partir de su promulgación.
"""


class Captura(unittest.TestCase):
    def test_html_a_texto(self):
        t = captura.texto_html(b"<html><script>x()</script><p>ARTICULO 1. Hola</p><p>Fin</p></html>", "utf-8")
        self.assertIn("ARTICULO 1. Hola", t)
        self.assertNotIn("x()", t)

    def test_robots_bloquea_sin_red(self):
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(["User-agent: *", "Disallow: /"])
        captura._ROBOTS["https://www.ejemplo.gov.co"] = (rp, "")
        with tempfile.TemporaryDirectory() as d:
            f = captura.capturar({"doc_id": "x", "url": "https://www.ejemplo.gov.co/ley.pdf"}, d, "2026-11-05")
        self.assertEqual(f["estado"], "bloqueado por robots.txt")
        self.assertEqual(f["sha256"], "")

    def test_dominio_no_oficial_se_omite(self):
        with tempfile.TemporaryDirectory() as d:
            f = captura.capturar({"doc_id": "x", "url": "https://www.periodico.com/nota"}, d, "2026-11-05")
        self.assertEqual(f["estado"], "omitido")


class Bloqueos(unittest.TestCase):
    def test_pagina_antibots_no_es_documento(self):
        b = b"<head><title>Radware Bot Manager Block</title><script>var x=1;</script></head>"
        self.assertIn("no se elude", captura.pagina_de_bloqueo(b, "text/html", "https://www.minhacienda.gov.co/x/PD.pdf"))

    def test_pdf_pedido_y_html_recibido(self):
        self.assertTrue(captura.pagina_de_bloqueo(b"<html><body>hola</body></html>", "text/html", "https://a.gov.co/d.pdf"))

    def test_documento_real_pasa(self):
        self.assertEqual(captura.pagina_de_bloqueo(b"%PDF-1.7 ...", "application/pdf", "https://a.gov.co/d.pdf"), "")
        self.assertEqual(captura.pagina_de_bloqueo(b"<html><title>Sentencia T-246/26</title></html>", "text/html",
                                                   "https://www.corteconstitucional.gov.co/relatoria/2026/T-246-26.htm"), "")


class Textos(unittest.TestCase):
    def test_notas_vigencia_solo_en_compilaciones(self):
        filas, rel, an = textos.procesar("ley-9", LEY, "http://www.secretariasenado.gov.co/senado/basedoc/ley_0009_2026.html")
        art1 = next(f for f in filas if f["unidad"] == "Artículo 1o")
        self.assertTrue(any("modificado por el artículo 3 de la Ley 2400" in n for n in art1["notas_vigencia"]))
        filas2, _, _ = textos.procesar("ley-9", LEY, "https://www.funcionpublica.gov.co/ley9.pdf")
        self.assertFalse(any(f["notas_vigencia"] for f in filas2))

    def test_regla_vigencia_literal_sin_fecha(self):
        _, _, an = textos.procesar("ley-9", LEY, "https://x.gov.co/l.pdf")
        self.assertTrue(any(a["tipo"] == "Regla de vigencia" and "rige a partir de su promulgación" in a["fragmento"] for a in an))


class Corpus(unittest.TestCase):
    def _capturas(self, d, sha, texto):
        os.makedirs(os.path.join(d, "por_doc", "ley-9"), exist_ok=True)
        filas, rel, an = textos.procesar("ley-9", texto, "https://x.gov.co/l.pdf", sha, "2026-11-05")
        for n, x in (("textos", filas), ("relaciones", rel), ("analisis", an)):
            json.dump(x, open(os.path.join(d, "por_doc", "ley-9", n + ".json"), "w", encoding="utf-8"))
        json.dump([{"doc_id": "ley-9", "url": "https://x.gov.co/l.pdf", "fecha_captura": "2026-11-05", "estado": "fallido", "sha256": ""},
                   {"doc_id": "ley-9", "url": "https://x.gov.co/l.pdf", "fecha_captura": "2026-11-05", "estado": "capturado", "sha256": sha,
                    "metodo_extraccion": "pdftotext -layout", "archivo": "originales/a.pdf", "nota": ""}],
                  open(os.path.join(d, "manifiesto.json"), "w", encoding="utf-8"))

    def test_corpus_y_version_anterior(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._capturas(d1, "a" * 64, LEY)
            filas, docs, rels, ans = corpus.construir(d1)
            self.assertEqual(len(filas), 1)
            self.assertEqual(filas[0]["articulos"], 3)
            self.assertIsNone(docs["ley-9"]["anterior"])
            prev = os.path.join(d2, "previo")
            os.makedirs(prev)
            json.dump(docs["ley-9"], open(os.path.join(prev, "ley-9.json"), "w", encoding="utf-8"))
            self._capturas(d1, "b" * 64, LEY.replace("regula el trámite", "regula el procedimiento"))
            _, docs2, _, _ = corpus.construir(d1, prev)
            self.assertEqual(docs2["ley-9"]["anterior"]["sha256"], "a" * 64)
            self.assertFalse(grafo.validar("relacion", rels) + grafo.validar("analisis", ans))

    def test_partes_por_tamano(self):
        largo = "\n".join(f"ARTÍCULO {i}. " + ("texto " * 3000) for i in range(1, 80))
        with tempfile.TemporaryDirectory() as d:
            self._capturas(d, "c" * 64, largo)
            _, docs, _, _ = corpus.construir(d)
        self.assertGreater(len(docs), 1)
        self.assertTrue(all(len(json.dumps(x, ensure_ascii=False).encode()) < 256_000 for x in docs.values()))
        self.assertEqual(sum(len(x["unidades"]) for x in docs.values()), 79)


    def test_sentencia_larga_se_divide_sin_perder_texto(self):
        cuerpo = " ".join(f"Considerando número {i} de la Sala sobre el caso." for i in range(6000))
        with tempfile.TemporaryDirectory() as d:
            self._capturas(d, "d" * 64, cuerpo)
            _, docs, _, _ = corpus.construir(d)
        us = [u for x in docs.values() for u in x["unidades"]]
        self.assertGreater(len(us), 5)
        self.assertTrue(all(len(u["texto"]) <= corpus.MAX_UNIDAD for u in us))
        self.assertEqual(" ".join(u["texto"] for u in us).replace("  ", " "), textos.normalizar(cuerpo))
        self.assertTrue(all(len(json.dumps(x, ensure_ascii=False).encode()) < 256_000 for x in docs.values()))


class Pendientes(unittest.TestCase):
    def test_prioridad_y_filtros(self):
        nov = [
            {"id": "a", "categoria": "Norma", "url": "https://www.x.gov.co/a.pdf", "verificacion": "V2", "relevancia": "Alta", "fecha": "2026-11-01", "fecha_captura": "2026-11-01"},
            {"id": "b", "categoria": "Norma", "url": "https://www.x.gov.co/b.pdf", "verificacion": "V1", "relevancia": "Baja", "fecha": "2026-10-20", "fecha_captura": "2026-10-20"},
            {"id": "c", "categoria": "Norma", "url": "https://www.prensa.com/c", "verificacion": "V3", "relevancia": "Alta", "fecha": "2026-11-01", "fecha_captura": "2026-11-01"},
            {"id": "d", "categoria": "Agenda", "url": "https://www.x.gov.co/d", "verificacion": "V2", "relevancia": "Alta", "fecha": "2026-11-01", "fecha_captura": "2026-11-01"},
            {"id": "e", "categoria": "Norma", "url": "https://www.x.gov.co/e.pdf", "verificacion": "V2", "relevancia": "Alta", "fecha": "2026-01-01", "fecha_captura": "2026-01-01"},
            {"id": "f", "categoria": "Norma", "url": "https://www.x.gov.co/f.pdf", "verificacion": "V2", "relevancia": "Alta", "fecha": "2026-11-02", "fecha_captura": "2026-11-02"},
        ]
        man = [{"doc_id": "f", "estado": "capturado", "sha256": "z"}]
        p = pendientes.elegir(nov, man, "2026-11-05", 30, 10)
        self.assertEqual([x["doc_id"] for x in p], ["b", "a"])


class Estados(unittest.TestCase):
    def _r(self, **k):
        r = {"id": "n1", "titulo": "Ley 9 de 2026", "verificacion": "V2 · registro oficial", "url": "https://www.x.gov.co/a.pdf", "fecha": "2026-11-01", "fecha_captura": "2026-11-02"}
        r.update(k)
        return r

    def test_escalera_de_estados(self):
        cor = [{"doc_id": "n1", "estado": "capturado", "sha256": "s" * 64, "fecha_captura": "2026-11-05", "metodo": "pdftotext -layout", "archivo": "o.pdf"}]
        t = grafo.trazabilidad([self._r()], [], [], [], [], [], "2026-11-05")[0]
        self.assertEqual(t["estado_confiabilidad"], "Capturado")
        t = grafo.trazabilidad([self._r()], [], [], [], [], [], "2026-11-05", cor)[0]
        self.assertEqual(t["estado_confiabilidad"], "Extracción exitosa")
        self.assertEqual(t["hash_original"], "s" * 64)
        val = [{"objeto": "registro", "id": "n1", "decision": "validado", "por": "u_1", "at": "2026-11-05T10:00"}]
        t = grafo.trazabilidad([self._r()], [], [], [], [], val, "2026-11-05", cor)[0]
        self.assertEqual(t["estado_confiabilidad"], "Verificado")
        t = grafo.trazabilidad([self._r()], [], [], [], [], val, "2026-11-05")[0]
        self.assertNotEqual(t["estado_confiabilidad"], "Verificado")
        self.assertIn("no alcanza «Verificado»", t["limitaciones"])
        t = grafo.trazabilidad([self._r(verificacion="V3 · prensa")], [], [], [], [], val, "2026-11-05", cor)[0]
        self.assertEqual(t["estado_confiabilidad"], "Pendiente de confirmación")

    def test_corroboracion_cuenta_dominios(self):
        r = self._r(url_alterna="https://www.otra.gov.co/a")
        t = grafo.trazabilidad([r], [], [], [], [], [], "2026-11-05")[0]
        self.assertEqual(t["corroboracion"], 2)
        self.assertNotIn("Una sola fuente", t["limitaciones"])


class Compuerta(unittest.TestCase):
    def test_integridad_rechaza_verificado_sin_texto(self):
        import integridad
        nov = [{"id": "n1", "titulo": "t", "fecha": "2026-11-01", "fecha_captura": "2026-11-02", "verificacion": "V2", "url": "https://x.gov.co/a"}]
        tz = grafo.trazabilidad(nov, [], [], [], [], [], "2026-11-05")
        tz[0]["estado_confiabilidad"] = "Verificado"
        with tempfile.TemporaryDirectory() as d:
            for n, x in (("novedades", nov), ("trazabilidad", tz)):
                json.dump(x, open(os.path.join(d, n + ".json"), "w", encoding="utf-8"))
            E, A, _ = integridad.revisar(d, "2026-11-05", validar_registro=False)
        self.assertTrue(any("«Verificado» sin texto completo" in e for e in E))

    def test_bitacora_anota_solo_campos_permitidos(self):
        import subprocess
        sc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "bitacora.py")
        with tempfile.TemporaryDirectory() as d:
            k = [{"id": "2026-11-05-2", "fecha": "2026-11-05", "fuentes_ok": "senado", "fuentes_fallidas": "", "nota": "Tarde"}]
            f = [{"id": "senado", "estado": "Operativa"}]
            json.dump(k, open(os.path.join(d, "k.json"), "w")); json.dump(f, open(os.path.join(d, "f.json"), "w"))
            base = [sys.executable, sc, "--corridas", os.path.join(d, "k.json"), "--fuentes", os.path.join(d, "f.json"),
                    "--salida-corridas", os.path.join(d, "k2.json"), "--salida-fuentes", os.path.join(d, "f2.json")]
            r = subprocess.run(base + ["--anotar", "integridad=0 errores · 0 avisos", "--anotar", "grafo=546 eventos"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            fila = json.load(open(os.path.join(d, "k2.json")))[0]
            self.assertEqual(fila["integridad"], "0 errores · 0 avisos")
            r = subprocess.run(base + ["--anotar", "estado=completada"], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
