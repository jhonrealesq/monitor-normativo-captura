#!/usr/bin/env python3
"""Lista de documentos por capturar (v1.11).

Elige, del repositorio `novedades`, los registros cuyo enlace apunta a un dominio oficial y que aún no tienen texto
capturado (o cuya captura falló), con prioridad: V1, luego relevancia Alta, luego lo más reciente. Escribe
`pendientes.json` para `captura.py`. No descarga nada.

Uso:
  python3 pendientes.py --novedades novedades.json [--manifiesto capturas/manifiesto.json] [--dias 30] [--max 20] \
      [--hoy 2026-11-05] --salida pendientes.json
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import captura  # noqa: E402
import grafo  # noqa: E402

CATEGORIAS = ("Norma", "Jurisprudencia", "Proyecto")
REL = {"Alta": 0, "Media": 1, "Baja": 2}


def elegir(novedades, manifiesto, hoy, dias, maximo):
    hechos = {m["doc_id"] for m in manifiesto if str(m.get("estado", "")).startswith("capturado")}
    bloqueados = {m["doc_id"] for m in manifiesto if m.get("estado") in ("bloqueado por robots.txt", "omitido")}
    lim = (datetime.date.fromisoformat(hoy) - datetime.timedelta(days=dias)).isoformat()
    cand = []
    for r in novedades:
        if r.get("categoria") not in CATEGORIAS or r["id"] in hechos or r["id"] in bloqueados:
            continue
        url = next((u for u in (r.get("url"), r.get("url_alterna")) if u and captura.DOMINIOS_OFICIALES.search(captura.urllib.parse.urlparse(u).hostname or "")), "")
        if not url:
            continue
        if max(r.get("fecha_captura", ""), r.get("fecha", "")) < lim:
            continue
        cand.append((0 if str(r.get("verificacion", "")).startswith("V1") else 1, REL.get(r.get("relevancia"), 3),
                     "".join(chr(255 - ord(c)) for c in (r.get("fecha") or r.get("fecha_captura") or "")), r["id"], url))
    cand.sort()
    return [{"doc_id": d, "url": u} for *_, d, u in cand[:maximo]]


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--novedades", required=True)
    a.add_argument("--manifiesto")
    a.add_argument("--dias", type=int, default=30)
    a.add_argument("--max", type=int, default=20)
    a.add_argument("--hoy", default=datetime.date.today().isoformat())
    a.add_argument("--salida", required=True)
    x = a.parse_args()
    pend = elegir(grafo.cargar(x.novedades), grafo.cargar(x.manifiesto), x.hoy, x.dias, x.max)
    json.dump(pend, open(x.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(pend)} pendientes escritos en {x.salida}")


if __name__ == "__main__":
    main()
