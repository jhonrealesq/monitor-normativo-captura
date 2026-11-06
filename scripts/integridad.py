#!/usr/bin/env python3
"""Revisión de integridad entre los datasets del Monitor Normativo (v1.11).

Comprueba, sin modificar nada:
- ids únicos en cada dataset;
- que todo `doc_id`, `origen_id` y `destino_id` apunte a un registro existente de `novedades`;
- que `trazabilidad` cubra cada registro una sola vez y que su hash coincida con el registro actual;
- que las relaciones no apunten a sí mismas y que «Confirmada» venga solo de validación humana;
- fechas AAAA-MM-DD válidas y no futuras más allá de un margen (eventos de agenda y plazos sí pueden ser futuros);
- que cada `id` de fuente citado en `resultado_fuentes` de `corridas` exista en `fuentes`;
- que la corrida más reciente tenga `estado` y `tipo`;
- validación de esquema de `registro.py` (novedades) y de `grafo.py` (eventos, relaciones, análisis);
- (v1.11) coherencia de los estados de confiabilidad: «Verificado» exige texto completo y validación humana,
  «Extracción exitosa» exige texto completo; el corpus (`corpus.json`, opcional) solo cita registros existentes.

Uso:
  python3 integridad.py --dir carpeta_con_los_json [--hoy 2026-11-05]
Sale con código 1 si hay errores; los avisos no bloquean. Solo usa la biblioteca estándar.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grafo  # noqa: E402

FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def cargar(d, n):
    p = os.path.join(d, n + ".json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        x = json.load(fh)
    return x.get("rows", x.get("data", x)) if isinstance(x, dict) else x


def fecha_ok(s):
    if not FECHA.match(s or ""):
        return False
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def revisar(d, hoy, validar_registro=True):
    E, A = [], []
    ds = {n: cargar(d, n) for n in ("novedades", "corridas", "fuentes", "calendario", "eventos", "relaciones", "analisis", "historial", "trazabilidad")}
    faltan = [n for n, v in ds.items() if v is None]
    corpus = cargar(d, "corpus")
    if faltan:
        A.append(f"No se encontraron: {', '.join(faltan)} (se omiten sus revisiones)")
    nov = ds["novedades"] or []
    ids = [r["id"] for r in nov]
    S = set(ids)
    lim = (datetime.date.fromisoformat(hoy) + datetime.timedelta(days=2)).isoformat()

    for n, clave in (("novedades", "id"), ("corridas", "id"), ("fuentes", "id"), ("calendario", "id"), ("eventos", "id"),
                     ("relaciones", "id"), ("analisis", "id"), ("historial", "id"), ("trazabilidad", "doc_id")):
        xs = ds[n] or []
        vistos, dup = set(), set()
        for x in xs:
            k = x.get(clave)
            if k in vistos:
                dup.add(k)
            vistos.add(k)
        if dup:
            E.append(f"{n}: {len(dup)} {clave} duplicados (p. ej. {sorted(dup)[0]})")

    for r in nov:
        for k in ("fecha", "fecha_captura"):
            if r.get(k) and not fecha_ok(r[k]):
                E.append(f"novedades {r['id']}: {k} inválida «{r[k]}»")
        if r.get("fecha_captura") and r["fecha_captura"] > lim:
            E.append(f"novedades {r['id']}: fecha_captura en el futuro ({r['fecha_captura']})")
        if r.get("fecha") and r["fecha"] > lim and r.get("categoria") not in ("Agenda",):
            A.append(f"novedades {r['id']}: fecha del acto posterior a hoy ({r['fecha']})")

    for n, k in (("eventos", "doc_id"), ("analisis", "doc_id"), ("historial", "doc_id"), ("trazabilidad", "doc_id"), ("relaciones", "origen_id")):
        malos = [x.get(k) for x in (ds[n] or []) if x.get(k) not in S]
        if malos:
            (A if n == "relaciones" else E).append(f"{n}: {len(malos)} filas con {k} que no existe en novedades (p. ej. {malos[0]})")
    rel = ds["relaciones"] or []
    malos = [x["destino_id"] for x in rel if x.get("destino_id") and x["destino_id"] not in S]
    if malos:
        E.append(f"relaciones: {len(malos)} destino_id inexistentes (p. ej. {malos[0]})")
    yo = [x["id"] for x in rel if x.get("destino_id") and x["destino_id"] == x["origen_id"]]
    if yo:
        E.append(f"relaciones: {len(yo)} relaciones de un documento consigo mismo")
    conf = [x["id"] for x in rel if x.get("estado_validacion") == "Confirmada" and x.get("metodo") != "Validación humana"]
    if conf:
        E.append(f"relaciones: {len(conf)} «Confirmada» sin validación humana")

    for e in ds["eventos"] or []:
        if not fecha_ok(e.get("fecha")):
            E.append(f"eventos {e['id']}: fecha inválida")
        elif e["fecha"] > lim and e.get("tipo_evento") not in ("Sesión", "Debate programado", "Cierre de comentarios", "Hito"):
            A.append(f"eventos {e['id']}: {e['tipo_evento']} con fecha futura {e['fecha']}")

    tz = ds["trazabilidad"]
    if tz is not None:
        cub = {t["doc_id"] for t in tz}
        falt = S - cub
        if falt:
            E.append(f"trazabilidad: {len(falt)} registros sin fila (p. ej. {sorted(falt)[0]}): correr grafo.py procesar")
        porid = {r["id"]: r for r in nov}
        desfase = [t["doc_id"] for t in tz if t["doc_id"] in porid and t.get("hash_registro") != grafo.hash_registro(porid[t["doc_id"]])[:16]]
        if desfase:
            A.append(f"trazabilidad: {len(desfase)} registros cambiaron desde el último procesamiento (p. ej. {desfase[0]}): correr grafo.py procesar")

    if tz is not None:
        sin_estado = [t["doc_id"] for t in tz if "estado_confiabilidad" not in t]
        if sin_estado:
            A.append(f"trazabilidad: {len(sin_estado)} filas sin estado_confiabilidad (correr grafo.py v1.11)")
        for t in tz:
            e = t.get("estado_confiabilidad")
            if e is None:
                continue
            if e not in grafo.ESTADOS_DOC:
                E.append(f"trazabilidad {t['doc_id']}: estado_confiabilidad desconocido «{e}»")
            elif e == "Verificado" and (t.get("estado_extraccion") != "Texto completo" or not t.get("validado_por")):
                E.append(f"trazabilidad {t['doc_id']}: «Verificado» sin texto completo o sin validación humana")
            elif e == "Extracción exitosa" and t.get("estado_extraccion") != "Texto completo":
                E.append(f"trazabilidad {t['doc_id']}: «Extracción exitosa» sin texto completo")
    if corpus is not None:
        malos = [c.get("doc_id") for c in corpus if c.get("doc_id") not in S]
        if malos:
            E.append(f"corpus: {len(malos)} documentos que no existen en novedades (p. ej. {malos[0]})")
        sh = [c.get("doc_id") for c in corpus if not re.fullmatch(r"[0-9a-f]{64}", c.get("sha256") or "")]
        if sh:
            E.append(f"corpus: {len(sh)} documentos sin sha256 válido del original")
        if tz is not None:
            con_texto = {t["doc_id"] for t in tz if t.get("estado_extraccion") == "Texto completo"}
            falt = [c["doc_id"] for c in corpus if c.get("doc_id") in S and c["doc_id"] not in con_texto]
            if falt:
                A.append(f"corpus: {len(falt)} textos capturados que la trazabilidad aún no refleja (correr grafo.py --corpus)")

    fu = {f["id"] for f in ds["fuentes"] or []}
    co = ds["corridas"] or []
    if co:
        ult = sorted(co, key=lambda c: c["id"])[-1]
        for k in ("estado", "tipo", "resultado_fuentes"):
            if not ult.get(k):
                E.append(f"corridas {ult['id']}: falta {k} (correr bitacora.py)")
        citadas = set()
        for c in co:
            for parte in (c.get("resultado_fuentes") or "").split(";"):
                m = re.match(r"\s*([\w-]+):", parte)
                if m:
                    citadas.add(m.group(1))
        extra = citadas - fu
        if extra:
            E.append(f"corridas: resultado_fuentes cita fuentes que no existen: {sorted(extra)[:5]}")

    for c in ds["calendario"] or []:
        for k in ("inicio", "fin"):
            if c.get(k) and not fecha_ok(c[k]):
                E.append(f"calendario {c.get('id')}: {k} inválida")
        if c.get("inicio") and c.get("fin") and c["fin"] < c["inicio"]:
            E.append(f"calendario {c.get('id')}: fin antes de inicio")

    for t, n in (("evento", "eventos"), ("relacion", "relaciones"), ("analisis", "analisis")):
        if ds[n] is not None:
            e = grafo.validar(t, ds[n])
            if e:
                E.append(f"{n}: {len(e)} errores de esquema (p. ej. {e[0]})")
    reg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registro.py")
    if validar_registro and nov and os.path.exists(reg):
        r = subprocess.run([sys.executable, reg, "validar", os.path.join(d, "novedades.json")], capture_output=True, text=True)
        ult = (r.stdout.strip().splitlines() or [""])[-1]
        if r.returncode != 0 or " 0 errores" not in ult:
            E.append(f"novedades (registro.py validar): {ult}")
    resumen = {n: (len(v) if v is not None else None) for n, v in ds.items()}
    resumen["corpus"] = len(corpus) if corpus is not None else None
    return E, A, resumen


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", required=True)
    p.add_argument("--hoy", default=datetime.date.today().isoformat())
    a = p.parse_args()
    E, A, R = revisar(a.dir, a.hoy)
    print(json.dumps({"filas": R, "errores": E, "avisos": A[:30], "n_avisos": len(A)}, ensure_ascii=False, indent=1))
    sys.exit(1 if E else 0)


if __name__ == "__main__":
    main()
