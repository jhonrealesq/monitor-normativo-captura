#!/usr/bin/env python3
"""Texto oficial por artículos (v1.11).

Toma el texto extraído de un documento oficial (norma o providencia) y produce:

- filas para el dataset `textos`: una por artículo, parágrafo o apartado, con su hash (sha256 del texto normalizado);
- relaciones candidatas (modifica, adiciona, sustituye, deroga, reglamenta…) con el fragmento literal del artículo
  que las contiene, listas para `grafo.py agregar --tipo relacion`;
- análisis: la regla de vigencia literal (p. ej. «rige a partir de su publicación»), sin inferir ninguna fecha.

El texto de entrada debe venir de una captura real del documento oficial (ver `captura.py`); este script no lee
internet ni completa nada. Si el texto no tiene encabezados de artículo, devuelve una sola unidad «Texto» y lo dice.

Uso:
  python3 textos.py segmentar --doc-id <id> --texto documento.txt --url <url oficial> \
      [--hash-original <sha256 del archivo>] [--fecha 2026-11-05] --salida-dir salida/
Solo usa la biblioteca estándar.
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grafo  # noqa: E402

ORDINALES = r"PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[ÉE]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO|[ÚU]NICO|TRANSITORIO|FINAL"
ENC_ARTICULO = re.compile(
    r"^[ \t]*(?:ART[ÍI]CULO|Art[íi]culo|ART\.)\s+(?P<num>\d+[A-Za-z]?(?:\.\d+)*(?:\s*(?:bis|transitorio))?|" + ORDINALES + r")\s*[°º.:\-–—]*",
    re.M)
ENC_PARAGRAFO = re.compile(r"^[ \t]*(?:PAR[ÁA]GRAFO|Par[áa]grafo)(?:\s+(?P<num>\d+|" + ORDINALES + r"))?\s*[°º.:\-–—]*", re.M | re.I)
ENC_RESUELVE = re.compile(r"^[ \t]*(?:R\s?E\s?S\s?U\s?E\s?L\s?V\s?E|DECRETA|ACUERDA|ORDENA|DISPONE)\s*:?\s*$", re.M)
# Notas de vigencia de compilaciones oficiales (Secretaría del Senado, SUIN-Juriscol): se citan, nunca se infieren.
NOTA_VIG = re.compile(r"(?:^|\n)[ \t]*-?[ \t]*((?:Art[íi]culo|Inciso|Par[áa]grafo|Numeral|Literal)?[^\n]{0,80}?\b(?:modificad[oa]|adicionad[oa]|subrogad[oa]|derogad[oa]|sustituid[oa]|declarad[oa] (?:inexequible|exequible|condicionalmente exequible|nul[oa]))\b[^\n]{3,260})", re.I)
COMPILACIONES = re.compile(r"secretariasenado\.gov\.co|suin-juriscol\.gov\.co|suin\.gov\.co", re.I)
VIGENCIA = re.compile(r"(?:rige|regir[áa]|entra(?:r[áa])? en vigencia|tendr[áa] vigencia)[^.]{0,160}", re.I)


def normalizar(t):
    return re.sub(r"\s+", " ", (t or "").replace(" ", " ")).strip()


def sha(t):
    return hashlib.sha256(normalizar(t).encode("utf-8")).hexdigest()


def segmentar(texto):
    """[{unidad, numero, orden, texto, inicio, fin}] por artículo; los parágrafos quedan dentro de su artículo
    y además se listan como unidades propias («Artículo 3, parágrafo 1»)."""
    texto = texto.replace("\r\n", "\n")
    arts = list(ENC_ARTICULO.finditer(texto))
    unidades = []
    if not arts:
        return [{"unidad": "Texto", "numero": "", "orden": 0, "texto": normalizar(texto), "inicio": 0, "fin": len(texto),
                 "nota": "Sin encabezados de artículo reconocibles: se conserva como una sola unidad."}]
    m0 = ENC_RESUELVE.search(texto, 0, arts[0].start())
    pre = texto[:arts[0].start()]
    if normalizar(pre):
        unidades.append({"unidad": "Encabezado y considerandos", "numero": "", "orden": 0, "texto": normalizar(pre),
                         "inicio": 0, "fin": arts[0].start(), "nota": "Incluye la parte resolutiva inicial" if m0 else ""})
    for i, m in enumerate(arts):
        fin = arts[i + 1].start() if i + 1 < len(arts) else len(texto)
        num = re.sub(r"\s+", " ", m.group("num")).strip()
        cuerpo = texto[m.start():fin]
        unidades.append({"unidad": f"Artículo {num}", "numero": num, "orden": len(unidades), "texto": normalizar(cuerpo),
                         "inicio": m.start(), "fin": fin, "nota": ""})
        pars = list(ENC_PARAGRAFO.finditer(cuerpo))
        for j, p in enumerate(pars):
            pfin = pars[j + 1].start() if j + 1 < len(pars) else len(cuerpo)
            pn = (p.group("num") or "").strip()
            unidades.append({"unidad": f"Artículo {num}, parágrafo{(' ' + pn) if pn else ''}", "numero": f"{num}.p{pn or j + 1}",
                             "orden": len(unidades), "texto": normalizar(cuerpo[p.start():pfin]),
                             "inicio": m.start() + p.start(), "fin": m.start() + pfin, "nota": ""})
    return unidades


def notas_vigencia(texto_unidad, url):
    """Solo para textos de compilaciones oficiales: devuelve las notas tal como aparecen en el texto."""
    if not COMPILACIONES.search(url or ""):
        return []
    out = []
    for m in NOTA_VIG.finditer(texto_unidad):
        frag = normalizar(m.group(1))
        if frag and frag not in out:
            out.append(frag[:300])
    return out[:12]


def procesar(doc_id, texto, url, hash_original="", fecha=""):
    unidades = segmentar(texto)
    filas, relaciones, analisis = [], [], []
    for u in unidades:
        filas.append({
            "id": f"{doc_id}#{u['numero'] or u['orden']}", "doc_id": doc_id, "unidad": u["unidad"], "orden": u["orden"],
            "texto": u["texto"], "hash": sha(u["texto"])[:16], "fuente_url": url, "hash_original": hash_original,
            "fecha_procesamiento": fecha, "metodo": "Captura de texto completo", "nota": u.get("nota", ""),
            "notas_vigencia": notas_vigencia(texto[u["inicio"]:u["fin"]] if u.get("fin") else u["texto"], url),
        })
        if u["unidad"].startswith("Artículo") and ", parágrafo" not in u["unidad"]:
            for ref in grafo.relaciones_por_verbo(u["texto"]):
                for v in ref["verbos"]:
                    relaciones.append(grafo.nueva_relacion(
                        doc_id, "", ref["nombre"], v, ref["fragmento"][:400], True, url, "Captura de texto completo",
                        "Sugerida por IA", nota=f"Identificada en {u['unidad']} del texto capturado (hash {sha(u['texto'])[:16]}).",
                        parte=ref["parte"]))
            for m in VIGENCIA.finditer(u["texto"]):
                analisis.append({"id": "an-" + grafo.h(doc_id, "Regla de vigencia", m.group(0)), "doc_id": doc_id,
                                 "tipo": "Regla de vigencia", "valor": u["unidad"], "fragmento": normalizar(m.group(0))[:300],
                                 "fragmento_literal": "sí", "fuente_url": url, "metodo": "Captura de texto completo",
                                 "estado_validacion": "Sugerida por IA",
                                 "nota": "Regla literal; la fecha de entrada en vigencia no se infiere."})
    # una sola vez por relación
    vistos, rel = set(), []
    for x in relaciones:
        if x["id"] not in vistos:
            vistos.add(x["id"])
            rel.append(x)
    return filas, rel, analisis


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    g = s.add_parser("segmentar")
    g.add_argument("--doc-id", required=True)
    g.add_argument("--texto", required=True)
    g.add_argument("--url", required=True)
    g.add_argument("--hash-original", default="")
    g.add_argument("--fecha", default="")
    g.add_argument("--salida-dir", required=True)
    a = p.parse_args()
    texto = open(a.texto, encoding="utf-8").read()
    filas, rel, an = procesar(a.doc_id, texto, a.url, a.hash_original, a.fecha)
    os.makedirs(a.salida_dir, exist_ok=True)
    for n, x in (("textos", filas), ("relaciones", rel), ("analisis", an)):
        json.dump(x, open(os.path.join(a.salida_dir, f"{n}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    errores = grafo.validar("relacion", rel) + grafo.validar("analisis", an)
    print(json.dumps({"unidades": len(filas), "relaciones": len(rel), "reglas_de_vigencia": len(an), "errores": errores[:10]}, ensure_ascii=False))
    sys.exit(1 if errores else 0)


if __name__ == "__main__":
    main()
