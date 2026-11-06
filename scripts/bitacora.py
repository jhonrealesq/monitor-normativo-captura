#!/usr/bin/env python3
"""Bitácora por fuente del Monitor Normativo (v1.11).

Lee `corridas.json` y `fuentes.json` y calcula, de forma determinista:

- En cada fuente: `frecuencia` (si falta), `ultima_ejecucion`, `ultima_lectura`, `fallas_consecutivas`
  y `resultado_ultima` (leída, parcial, fallida, no revisada).
- En cada corrida: `resultado_fuentes` (texto «id: resultado; …»), `estado` (completada, parcial o fallida)
  y `tipo` (Mañana, Tarde, A demanda; se deduce de la nota cuando falta).

Una fuente se cuenta «leída» si su id aparece en `fuentes_ok`, «fallida» si aparece en `fuentes_fallidas`
(salvo en una cláusula que diga «no revisado», que la deja como no revisada),
«parcial» si aparece en ambos (p. ej., el índice falló pero el buscador sí trajo resultados) y «no revisada»
si no aparece. Los ids se buscan como palabra completa, así `camara` no confunde `camara-comisiones`.

Regla de estado de la corrida: «parcial» si alguna fuente de frecuencia alta quedó fallida o parcial;
«completada» si no. Las fuentes de consulta manual (bloqueadas o sin sitio oficial) no cuentan: su falla es
conocida y se declara siempre. «fallida» solo la escribe la corrida misma cuando no pudo publicar.

Desde la v1.11 la corrida deja constancia de sus controles en su propia fila con `--anotar campo=valor`
(se puede repetir): `grafo`, `integridad`, `version_anterior`, `captura`. Solo se aceptan esos campos.

Uso:
  python3 bitacora.py --corridas corridas.json --fuentes fuentes.json \
      --salida-corridas corridas.json --salida-fuentes fuentes.json \
      [--corrida 2026-11-05-2] [--anotar "grafo=546 eventos · 64 relaciones" --anotar "integridad=0 errores · 0 avisos"]
Solo usa la biblioteca estándar.
"""
import argparse
import json
import re

ALTA = {
    "dapre-decretos", "dapre-leyes", "cc-comunicados", "cc-relatoria", "csj-portal", "ce-boletines", "ce-noticias",
    "camara", "senado", "senado-orden-dia", "gaceta-congreso", "alcaldia-medellin", "concejo-medellin",
    "gob-antioquia", "gob-atlantico-gaceta", "alcaldia-barranquilla", "concejo-envigado", "concejo-envigado-agenda",
    "bogota-regimen",
}
ANOTABLES = {"grafo", "integridad", "version_anterior", "captura"}
MANUAL = {"Bloqueada para lectura automática", "Sin fuente oficial localizada"}


def frecuencia(f):
    if f.get("estado") in MANUAL:
        return "manual"
    if f["id"] in ALTA:
        return "alta"
    if f.get("seccion") == "Noticias" or f.get("organo") == "Referencias":
        return "baja"
    return "media"


def aparece(fid, texto):
    return re.search(r"(?<![\w-])" + re.escape(fid) + r"(?![\w-])", texto or "", re.I) is not None


NO_REVISADA = re.compile(r"no revisad", re.I)


def partir_fallidas(texto):
    """Separa `fuentes_fallidas` en (texto de fallas, texto de no revisadas) por cláusulas «;».
    Una cláusula que dice «no revisado(s)» no es una falla: la fuente no se intentó."""
    fallas, no_rev = [], []
    for cl in (texto or "").split(";"):
        (no_rev if NO_REVISADA.search(cl) else fallas).append(cl)
    return ";".join(fallas), ";".join(no_rev)


def tipo_de(c):
    if c.get("tipo"):
        return c["tipo"]
    n = (c.get("nota") or "").lower()
    if n.startswith("a demanda"):
        return "A demanda"
    if n.startswith("tarde"):
        return "Tarde"
    return "Mañana"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corridas", required=True)
    p.add_argument("--fuentes", required=True)
    p.add_argument("--salida-corridas", required=True)
    p.add_argument("--salida-fuentes", required=True)
    p.add_argument("--corrida", help="id de la corrida a anotar (por defecto, la más reciente)")
    p.add_argument("--anotar", action="append", default=[], help="campo=valor; campos: " + ", ".join(sorted(ANOTABLES)))
    a = p.parse_args()
    K = json.load(open(a.corridas, encoding="utf-8"))
    F = json.load(open(a.fuentes, encoding="utf-8"))
    for f in F:
        if not f.get("frecuencia"):
            f["frecuencia"] = frecuencia(f)
    alta = {f["id"] for f in F if f["frecuencia"] == "alta"}
    hist = {f["id"]: {"ultima_ejecucion": "", "ultima_lectura": "", "fallas_consecutivas": 0, "resultado_ultima": "no revisada"} for f in F}
    # De la más antigua a la más reciente.
    for c in sorted(K, key=lambda c: c["id"]):
        res = []
        peor = False
        for f in F:
            fid = f["id"]
            fallas_txt, _ = partir_fallidas(c.get("fuentes_fallidas"))
            ok, mal = aparece(fid, c.get("fuentes_ok")), aparece(fid, fallas_txt)
            r = "parcial" if ok and mal else "leída" if ok else "fallida" if mal else "no revisada"
            h = hist[fid]
            if r != "no revisada":
                h["ultima_ejecucion"] = c["fecha"]
                h["resultado_ultima"] = r
            if r in ("leída", "parcial"):
                h["ultima_lectura"] = c["fecha"]
            if r == "fallida":
                h["fallas_consecutivas"] += 1
            elif r in ("leída", "parcial"):
                h["fallas_consecutivas"] = 0
            if r != "no revisada":
                res.append(f"{fid}: {r}")
            if fid in alta and r in ("fallida", "parcial"):
                peor = True
        c["resultado_fuentes"] = "; ".join(res)
        if c.get("estado") != "fallida":
            c["estado"] = "parcial" if peor else "completada"
        c["tipo"] = tipo_de(c)
    for f in F:
        f.update(hist[f["id"]])
    if a.anotar:
        obj = next((c for c in K if c["id"] == a.corrida), None) if a.corrida else max(K, key=lambda c: c["id"])
        if obj is None:
            raise SystemExit(f"No existe la corrida {a.corrida}")
        for kv in a.anotar:
            k, _, v = kv.partition("=")
            if k.strip() not in ANOTABLES:
                raise SystemExit(f"Campo no anotable: {k}. Use: {', '.join(sorted(ANOTABLES))}")
            obj[k.strip()] = v.strip()
    K.sort(key=lambda c: c["id"], reverse=True)
    json.dump(K, open(a.salida_corridas, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(F, open(a.salida_fuentes, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(json.dumps({"corridas": dict(Counter(c["estado"] for c in K)),
                      "frecuencia": dict(Counter(f["frecuencia"] for f in F)),
                      "degradadas": sorted(f["id"] for f in F if f["fallas_consecutivas"] >= 3 and f["frecuencia"] != "manual")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
