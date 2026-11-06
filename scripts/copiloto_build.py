#!/usr/bin/env python3
"""Página del copiloto con la copia de datos del monitor (v1.11).

Toma la plantilla `assets/copiloto.html` e inserta, como JSON, una copia reducida del repositorio: novedades (campos
que el copiloto lee), relaciones, análisis, el estado de confiabilidad de la trazabilidad y, si existen, los textos
completos de `corpus.py` (carpeta textos_db). La corrida la republica en la página compañera después de publicar.

Uso:
  python3 copiloto_build.py --plantilla assets/copiloto.html --dir carpeta_json --corrida 2026-11-05-2 \
      [--textos corpus/textos_db] --salida copiloto_publicar.html
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grafo  # noqa: E402

CAMPOS = ["id", "categoria", "tipo", "numero", "organo", "sala", "territorio", "nivel", "areas", "titulo", "resumen", "accion", "estado",
          "fecha", "fecha_captura", "url", "verificacion"]
LIMITE = 12_000_000


def construir(d, corrida, textos_dir=None):
    nov = [{k: r.get(k, "") for k in CAMPOS} for r in grafo.cargar(os.path.join(d, "novedades.json"))]
    rel = [{k: x.get(k, "") for k in ("origen_id", "destino_id", "destino_ref", "tipo", "fragmento", "fragmento_literal", "estado_validacion")} for x in grafo.cargar(os.path.join(d, "relaciones.json"))]
    an = [{k: x.get(k, "") for k in ("doc_id", "tipo", "valor", "fragmento", "fragmento_literal", "estado_validacion")} for x in grafo.cargar(os.path.join(d, "analisis.json"))]
    tz = [{"doc_id": t["doc_id"], "estado_confiabilidad": t.get("estado_confiabilidad", "")} for t in grafo.cargar(os.path.join(d, "trazabilidad.json"))]
    textos = {}
    if textos_dir and os.path.isdir(textos_dir):
        for p in sorted(glob.glob(os.path.join(textos_dir, "*.json"))):
            x = json.load(open(p, encoding="utf-8"))
            textos.setdefault(x["doc_id"], []).extend({"unidad": u["unidad"], "texto": u["texto"]} for u in x.get("unidades", []))
    return {"corrida": corrida, "novedades": nov, "relaciones": rel, "analisis": an, "trazabilidad": tz, "textos": textos}


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--plantilla", required=True)
    a.add_argument("--dir", required=True)
    a.add_argument("--corrida", required=True)
    a.add_argument("--textos")
    a.add_argument("--salida", required=True)
    x = a.parse_args()
    datos = construir(x.dir, x.corrida, x.textos)
    js = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if len(js.encode("utf-8")) > LIMITE:
        # El corpus crece: se recortan primero los textos más largos, nunca los metadatos.
        for k in sorted(datos["textos"], key=lambda k: -sum(len(u["texto"]) for u in datos["textos"][k])):
            del datos["textos"][k]
            js = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
            if len(js.encode("utf-8")) <= LIMITE:
                break
    html = open(x.plantilla, encoding="utf-8").read()
    if "/*__DATOS__*/null" not in html:
        sys.exit("La plantilla no tiene el marcador /*__DATOS__*/null")
    open(x.salida, "w", encoding="utf-8").write(html.replace("/*__DATOS__*/null", js))
    print(json.dumps({"documentos": len(datos["novedades"]), "textos": len(datos["textos"]), "bytes": len(js.encode("utf-8"))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
