#!/usr/bin/env python3
"""Herramientas de datos del Monitor Normativo (v1.8: vocabulario cerrado de `estado`).

Subcomandos:
  id        Genera el id estable de un registro de `novedades`.
  validar   Revisa un archivo JSON de registros contra el esquema.
  fusionar  Une registros nuevos con el repositorio existente (sin duplicar).
  resumen   Cuenta registros por categoría, nivel y relevancia desde una fecha.

Ejemplos:
  python3 registro.py id --tipo Decreto --numero 1493 --fecha 2026-10-06 --territorio Colombia
  python3 registro.py validar nuevos.json
  python3 registro.py fusionar --base novedades.json --nuevos nuevos.json --salida novedades.json
  python3 registro.py resumen novedades.json --desde 2026-10-06

Solo usa la biblioteca estándar: corre en cualquier sesión sin instalar nada.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date

CATEGORIAS = {"Norma", "Jurisprudencia", "Proyecto", "Agenda", "Noticia jurídica"}
NIVELES = {"Nacional", "Departamental", "Distrital/Municipal"}
RELEVANCIA = {"Alta", "Media", "Baja"}
VERIFICACION = ["V1 Texto oficial leído", "V2 Registro oficial leído", "V3 Fuente secundaria"]
# Series nacionales con numeración única: el emisor no hace parte del id.
SERIES_UNICAS = {"ley", "decreto", "decreto legislativo", "acto legislativo"}
AREAS = {
    "Derecho público", "Derecho constitucional", "Derecho administrativo", "Derecho urbanístico",
    "Ordenamiento territorial", "Gestión del riesgo", "Servicios públicos", "Gobierno y políticas públicas",
    "Hacienda pública", "Tributario", "Contratación estatal", "Derecho disciplinario",
    "Responsabilidad del Estado", "Reparación directa", "Responsabilidad civil", "Empleo público",
    "Derecho laboral", "Seguridad social", "Seguridad social docentes", "Pensiones", "Salud",
    "Insolvencia", "Societario", "Propiedad intelectual", "Derechos de autor", "Derecho procesal",
    "Derecho penal", "Familia", "Ambiental", "Educación", "Movilidad", "Cultura", "Electoral",
    "Financiero", "Comercio exterior", "Minas y energía",
}
# Proyectos del usuario: un puntaje 0-3 por proyecto (criterios en references/relevancia.md).
PROYECTOS = {
    "pm": "Plan Maestro", "cdae": "Con Derecho a Entender", "pi": "Perspectiva Integral",
    "dap": "DAP Envigado", "qbd": "Centro Quibdoseños", "med": "Centro Medellinenses",
    "gpp": "Gobierno y Políticas Públicas", "ot": "Ordenamiento Territorial",
}
# Grupo de presentación: así se segrega el boletín diario y el dashboard.
GRUPOS = [
    "Corte Constitucional", "Corte Suprema de Justicia", "Consejo de Estado",
    "Comisión Nacional de Disciplina Judicial", "Tribunales", "Juzgados",
    "Congreso de la República", "Presidencia y ministerios", "Entidades nacionales",
    "Órganos de control", "Antioquia", "Atlántico", "Chocó", "Bogotá", "Medellín", "Envigado",
    "Barranquilla", "Quibdó",
    "Otros territorios",
]
CAMPOS = [
    "id", "fecha", "fecha_captura", "categoria", "tipo", "numero", "nivel", "territorio",
    "grupo", "organo", "sala", "sector", "entidad",
    "titulo", "resumen", "areas", "relevancia", "pm", "cdae", "pi", "dap", "qbd", "med", "gpp", "ot",
    "accion", "estado", "url",
    "url_alterna", "fuente", "verificacion", "nota",
]
OBLIGATORIOS = ["id", "fecha_captura", "categoria", "tipo", "nivel", "territorio", "grupo", "organo",
                "entidad", "titulo", "resumen", "relevancia", "fuente", "verificacion"]
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Vocabulario cerrado de `estado` (v1.8). Se valida la base: el texto antes de " (". El detalle entre
# paréntesis es libre (fecha, comisión, votación, «según prensa»). La vigencia nunca es un estado.
ESTADOS = {
    "Norma": {"Expedida", "Sancionada", "Publicada", "Aprobada", "Reportada"},
    "Jurisprudencia": {"Decidida", "Publicada", "Pendiente de fallo"},
    "Proyecto": {"Publicado", "Publicado para comentarios", "Comentarios cerrados", "Radicado", "En estudio",
                 "En trámite", "Con ponentes asignados", "Con ponencia para primer debate", "En primer debate",
                 "Aprobado en comisión", "Aprobado en primer debate", "Con ponencia para segundo debate",
                 "Segundo debate programado", "Aprobado en segundo debate", "Aprobado en tercer debate",
                 "Aprobado en cuarto debate", "En conciliación", "Pasa a sanción", "Subsanación",
                 "Revisión de la Corte", "Sancionado", "Expedido", "Archivado", "Retirado"},
    "Agenda": {"Anunciada", "Programada", "En curso", "En estudio", "Realizada", "Aplazada", "Cancelada"},
    "Noticia jurídica": {"Anunciada", "En trámite", "Radicado", "Realizada"},
}


def estado_base(e):
    return re.split(r"\s+\(", (e or "").strip(), maxsplit=1)[0].strip()


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t


def emisor_canonico(entidad: str) -> str:
    """Toma la parte anterior a ' — ' y sus primeras cuatro palabras."""
    base = re.split(r"\s+[—-]{1,2}\s+", entidad or "")[0]
    return "-".join(slug(base).split("-")[:4])


def generar_id(tipo, numero, fecha, territorio, entidad="", titulo=""):
    anio = (fecha or "")[:4] or "s-f"
    partes = [slug(tipo)]
    if numero:
        partes.append(slug(numero))
    else:
        partes.append(hashlib.sha1(slug(titulo).encode()).hexdigest()[:8])
    partes.append(anio)
    partes.append(slug(territorio))
    if slug(tipo).replace("-", " ") not in SERIES_UNICAS or slug(territorio) != "colombia":
        em = emisor_canonico(entidad)
        if em:
            partes.append(em)
    return "-".join(p for p in partes if p)


def validar_registro(r, idx):
    errores, avisos = [], []
    pref = f"[{idx}] {r.get('id', '(sin id)')}: "
    for c in OBLIGATORIOS:
        if str(r.get(c, "")).strip() == "":
            errores.append(pref + f"falta '{c}'")
    for c in r:
        if c not in CAMPOS:
            avisos.append(pref + f"campo desconocido '{c}'")
    if r.get("categoria") and r["categoria"] not in CATEGORIAS:
        errores.append(pref + f"categoria inválida '{r['categoria']}'")
    if r.get("grupo") and r["grupo"] not in GRUPOS:
        errores.append(pref + f"grupo inválido '{r['grupo']}'")
    if r.get("categoria") == "Jurisprudencia" and r.get("grupo") in (
            "Presidencia y ministerios", "Congreso de la República"):
        errores.append(pref + "jurisprudencia con grupo de órgano no judicial")
    if r.get("categoria") in ESTADOS and r.get("estado") and estado_base(r["estado"]) not in ESTADOS[r["categoria"]]:
        errores.append(pref + f"estado fuera del vocabulario para {r['categoria']}: '{estado_base(r['estado'])}' "
                       f"(válidos: {', '.join(sorted(ESTADOS[r['categoria']]))}; el detalle va entre paréntesis)")
    if r.get("nivel") and r["nivel"] not in NIVELES:
        errores.append(pref + f"nivel inválido '{r['nivel']}'")
    if r.get("relevancia") and r["relevancia"] not in RELEVANCIA:
        errores.append(pref + f"relevancia inválida '{r['relevancia']}'")
    if r.get("verificacion") and r["verificacion"] not in VERIFICACION:
        errores.append(pref + f"verificacion inválida '{r['verificacion']}'")
    for c in ("fecha", "fecha_captura"):
        v = r.get(c, "")
        if v and not FECHA_RE.match(v):
            errores.append(pref + f"{c} no es AAAA-MM-DD: '{v}'")
        if v and FECHA_RE.match(v) and v > date.today().isoformat():
            errores.append(pref + f"{c} está en el futuro: '{v}'")
    for c in PROYECTOS:
        v = r.get(c, 0)
        if not isinstance(v, int) or not 0 <= v <= 3:
            errores.append(pref + f"{c} debe ser entero 0-3")
    for c in ("url", "url_alterna"):
        v = r.get(c, "")
        if v and not re.match(r"^https?://", v):
            errores.append(pref + f"{c} no es una URL: '{v}'")
    if r.get("verificacion", "").startswith(("V1", "V2")) and not r.get("url"):
        errores.append(pref + "V1/V2 exige 'url' oficial")
    for a in [x.strip() for x in str(r.get("areas", "")).split(";") if x.strip()]:
        if a not in AREAS:
            avisos.append(pref + f"área fuera de la taxonomía '{a}'")
    esperado = generar_id(r.get("tipo", ""), r.get("numero", ""), r.get("fecha", ""),
                          r.get("territorio", ""), r.get("entidad", ""), r.get("titulo", ""))
    # Los ids son estables: si la fecha se conoció después, el id conserva «s-f» y eso no es un error.
    if r.get("id") and r["id"] != esperado and r["id"].replace("-s-f-", "-" + (r.get("fecha") or "")[:4] + "-") != esperado:
        avisos.append(pref + f"id distinto al generado ('{esperado}')")
    return errores, avisos


def cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    if isinstance(datos, dict):
        datos = datos.get("rows") or datos.get("data") or datos.get("results") or []
    return datos


def normalizar(r):
    out = {c: r.get(c, 0 if c in PROYECTOS else "") for c in CAMPOS}
    if not out["id"]:
        out["id"] = generar_id(out["tipo"], out["numero"], out["fecha"], out["territorio"],
                               out["entidad"], out["titulo"])
    return out


def cmd_id(a):
    print(generar_id(a.tipo, a.numero, a.fecha, a.territorio, a.entidad, a.titulo))


def cmd_validar(a):
    regs = cargar(a.archivo)
    errores, avisos, ids = [], [], {}
    for i, r in enumerate(regs):
        e, w = validar_registro(r, i)
        errores += e
        avisos += w
        ids.setdefault(r.get("id"), []).append(i)
    for k, v in ids.items():
        if len(v) > 1:
            errores.append(f"id repetido '{k}' en posiciones {v}")
    for w in avisos:
        print("AVISO", w)
    for e in errores:
        print("ERROR", e)
    print(f"{len(regs)} registros · {len(errores)} errores · {len(avisos)} avisos")
    sys.exit(1 if errores else 0)


def rango(v):
    return VERIFICACION.index(v) if v in VERIFICACION else 99


def cmd_fusionar(a):
    base = [normalizar(r) for r in cargar(a.base)] if a.base else []
    nuevos = [normalizar(r) for r in cargar(a.nuevos)]
    por_id = {r["id"]: r for r in base}
    n_nuevos = n_act = 0
    for r in nuevos:
        if r["id"] not in por_id:
            por_id[r["id"]] = r
            n_nuevos += 1
            continue
        viejo = por_id[r["id"]]
        cambio = False
        for c in CAMPOS:
            if c in ("id",):
                continue
            if c == "fecha_captura":
                v = min(x for x in (viejo[c], r[c]) if x) if (viejo[c] or r[c]) else ""
            elif c == "verificacion":
                v = r[c] if rango(r[c]) < rango(viejo[c]) else viejo[c]
            else:
                v = r[c] if r[c] not in ("", None) else viejo[c]
            if v != viejo[c]:
                viejo[c] = v
                cambio = True
        n_act += cambio
    # Aviso de posibles duplicados con id distinto (mismo tipo + número + año).
    clave = {}
    for r in por_id.values():
        if r["numero"]:
            k = (slug(r["tipo"]), slug(r["numero"]), r["fecha"][:4], slug(r["territorio"]))
            clave.setdefault(k, []).append(r["id"])
    for k, v in clave.items():
        if len(v) > 1:
            print("AVISO posible duplicado:", ", ".join(v))
    salida = sorted(por_id.values(), key=lambda r: (r["fecha"] or r["fecha_captura"], r["id"]), reverse=True)
    with open(a.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)
    print(json.dumps({"total": len(salida), "nuevos": n_nuevos, "actualizados": n_act}))


def cmd_resumen(a):
    regs = cargar(a.archivo)
    sel = [r for r in regs if (r.get("fecha") or r.get("fecha_captura", "")) >= (a.desde or "")]
    def cuenta(c):
        d = {}
        for r in sel:
            d[r.get(c, "")] = d.get(r.get(c, ""), 0) + 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))
    print(json.dumps({"desde": a.desde, "registros": len(sel), "categoria": cuenta("categoria"),
                      "nivel": cuenta("nivel"), "relevancia": cuenta("relevancia"),
                      "verificacion": cuenta("verificacion")}, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    pi = s.add_parser("id")
    for c in ("tipo", "numero", "fecha", "territorio", "entidad", "titulo"):
        pi.add_argument("--" + c, default="")
    pi.set_defaults(f=cmd_id)
    pv = s.add_parser("validar")
    pv.add_argument("archivo")
    pv.set_defaults(f=cmd_validar)
    pf = s.add_parser("fusionar")
    pf.add_argument("--base", default="")
    pf.add_argument("--nuevos", required=True)
    pf.add_argument("--salida", required=True)
    pf.set_defaults(f=cmd_fusionar)
    pr = s.add_parser("resumen")
    pr.add_argument("archivo")
    pr.add_argument("--desde", default="")
    pr.set_defaults(f=cmd_resumen)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
