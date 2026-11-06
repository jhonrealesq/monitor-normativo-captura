#!/usr/bin/env python3
"""Corpus de texto oficial para el tablero (v1.11).

Lee la carpeta de `captura.py` (manifiesto.json + por_doc/<id>/textos.json) y prepara lo que la corrida publica:

- `corpus.json`  dataset con una fila por documento capturado: hash del original, fecha, método, unidades, caracteres,
                 estado y aviso. Lo usa `grafo.py procesar --corpus` para la trazabilidad (estado «Extracción exitosa»).
- `textos_db/<id>.json`  un documento por registro para la colección `textos` de la base del tablero (el lector lo
                 carga solo al abrirlo). Si un texto pasa de ~200 KB se divide en partes `<id>--2`, `<id>--3`…
                 Cuando el original cambió (otro sha256), conserva la versión anterior en `anterior` para comparar.
- `relaciones_texto.json`, `analisis_texto.json`  lo que `textos.py` encontró en los textos, para `grafo.py agregar`.

Uso:
  python3 corpus.py --capturas capturas/ [--previo corpus_textos_previos/] --salida-dir corpus/
Solo usa la biblioteca estándar.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grafo  # noqa: E402

LIMITE = 200_000  # la base del tablero rechaza documentos de más de 256 KB


MAX_UNIDAD = 40_000  # caracteres; una sentencia sin artículos se divide en secciones de lectura


def dividir(u):
    """Divide una unidad muy larga en secciones que terminan en un punto. El texto no cambia: solo se reparte."""
    t = u["texto"]
    if len(t) <= MAX_UNIDAD:
        return [u]
    out, i, k = [], 0, 1
    while i < len(t):
        j = min(len(t), i + MAX_UNIDAD)
        if j < len(t):
            p = t.rfind(". ", i + MAX_UNIDAD // 2, j)
            j = p + 1 if p > 0 else j
        out.append({**u, "unidad": f"{u['unidad']} · sección {k}", "texto": t[i:j].strip(), "hash": grafo.h(u["hash"], k, n=16)})
        i, k = j, k + 1
    return out


def doc_key(doc_id):
    return re.sub(r"[^A-Za-z0-9_\-.~:@+]", "_", doc_id)[:180]


def construir(capturas, previo_dir=None):
    man = grafo.cargar(os.path.join(capturas, "manifiesto.json"))
    ultimo = {}
    for m in man:  # el manifiesto es acumulado: gana la última captura exitosa de cada documento
        if str(m.get("estado", "")).startswith("capturado"):
            ultimo[m["doc_id"]] = m
    filas, docs, rels, ans = [], {}, [], []
    for d, m in sorted(ultimo.items()):
        base = os.path.join(capturas, "por_doc", d)
        tx = grafo.cargar(os.path.join(base, "textos.json"))
        if not tx:
            continue
        rels += grafo.cargar(os.path.join(base, "relaciones.json"))
        ans += grafo.cargar(os.path.join(base, "analisis.json"))
        crudas = [{"unidad": t["unidad"], "texto": t["texto"], "hash": t["hash"], "notas_vigencia": t.get("notas_vigencia", [])} for t in tx]
        unidades = [{"n": i, **u} for i, u in enumerate(x for c in crudas for x in dividir(c))]
        chars = sum(len(u["texto"]) for u in unidades)
        filas.append({"doc_id": d, "sha256": m["sha256"], "fecha_captura": m["fecha_captura"], "metodo": m.get("metodo_extraccion", ""),
                      "unidades": len(unidades), "articulos": sum(1 for u in unidades if u["unidad"].startswith("Artículo") and "parágrafo" not in u["unidad"]),
                      "caracteres": chars, "notas_vigencia": sum(len(u["notas_vigencia"]) for u in unidades),
                      "estado": m["estado"], "aviso": m.get("nota", ""), "url": m["url"], "archivo": m.get("archivo", ""), "clave": doc_key(d)})
        anterior = None
        if previo_dir:
            pp = os.path.join(previo_dir, doc_key(d) + ".json")
            if os.path.exists(pp):
                prev = json.load(open(pp, encoding="utf-8"))
                if prev.get("sha256") and prev["sha256"] != m["sha256"]:
                    anterior = {"sha256": prev["sha256"], "fecha_captura": prev.get("fecha_captura", ""),
                                "unidades": [{"unidad": u["unidad"], "hash": u["hash"], "texto": u["texto"]} for u in prev.get("unidades", [])]}
                elif prev.get("anterior"):
                    anterior = prev["anterior"]
        meta = {"doc_id": d, "sha256": m["sha256"], "url": m["url"], "fecha_captura": m["fecha_captura"],
                "metodo": m.get("metodo_extraccion", ""), "aviso": m.get("nota", ""), "anterior": anterior}
        # partes de tamaño acotado
        partes, actual, tam = [], [], 0
        for u in unidades:
            n = len(json.dumps(u, ensure_ascii=False).encode("utf-8"))
            if actual and tam + n > LIMITE:
                partes.append(actual)
                actual, tam = [], 0
            actual.append(u)
            tam += n
        partes.append(actual)
        k = doc_key(d)
        for i, p in enumerate(partes):
            clave = k if i == 0 else f"{k}--{i + 1}"
            doc = {**meta, "parte": i + 1, "partes": len(partes), "unidades": p}
            if i:
                doc["anterior"] = None
            docs[clave] = doc
    return filas, docs, rels, ans


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--capturas", required=True)
    a.add_argument("--previo")
    a.add_argument("--salida-dir", required=True)
    x = a.parse_args()
    filas, docs, rels, ans = construir(x.capturas, x.previo)
    os.makedirs(os.path.join(x.salida_dir, "textos_db"), exist_ok=True)
    grafo.guardar(os.path.join(x.salida_dir, "corpus.json"), filas)
    for k, d in docs.items():
        json.dump(d, open(os.path.join(x.salida_dir, "textos_db", k + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    grafo.guardar(os.path.join(x.salida_dir, "relaciones_texto.json"), rels)
    grafo.guardar(os.path.join(x.salida_dir, "analisis_texto.json"), ans)
    e = grafo.validar("relacion", rels) + grafo.validar("analisis", ans)
    print(json.dumps({"documentos": len(filas), "partes_db": len(docs), "relaciones": len(rels), "analisis": len(ans), "errores": e[:10]}, ensure_ascii=False))
    sys.exit(1 if e else 0)


if __name__ == "__main__":
    main()
