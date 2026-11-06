#!/usr/bin/env python3
"""Grafo jurídico, cronología y trazabilidad del Monitor Normativo (v1.11).

Construye, a partir de `novedades.json`, cinco archivos derivados y mantiene los que agregan las corridas:

- `eventos.json`      Cronología: expedición, sanción, publicación, radicación, debates, decisión judicial, captura…
- `relaciones.json`   Grafo: modifica, adiciona, sustituye, deroga, reglamenta, declara exequible, se convirtió en…
- `analisis.json`     Afirmaciones sobre un documento (ponente, expediente, problema jurídico, decisión, regla)
                      cada una con su fragmento de soporte y su fuente.
- `historial.json`    Cambios de cada registro (campo, antes, después, fecha, corrida).
- `trazabilidad.json` Una fila por registro: hash del registro, fechas, estado de extracción y de validación.

Reglas de honestidad que el script hace cumplir:
- Nada se infiere de la nada: cada evento o relación lleva `origen` (registro, campo o fuente) y `metodo`.
- Tres estados de validación: «Confirmada» (la validó una persona), «Sugerida por IA» (identificada por la
  corrida o por patrón sobre texto oficial, con fragmento), «Pendiente de revisión» (soporte débil: prensa,
  resumen propio, título descriptivo o verbo ambiguo). «Descartada» la pone solo una persona.
- `fragmento_literal` = "sí" solo cuando el fragmento es texto oficial transcrito (epígrafe oficial o cita de la
  fuente). Un resumen propio nunca es literal.
- La vigencia no se infiere: no hay evento de «Entrada en vigencia» sin fragmento que lo diga.
- Lo derivado se regenera en cada corrida con ids estables; lo agregado por una corrida o por una persona
  se conserva. Las validaciones humanas (`validaciones.json`, exportado de la base de la página) siempre ganan.

Uso:
  python3 grafo.py procesar --novedades novedades.json [--anterior novedades_previo.json] \
      [--eventos eventos.json] [--relaciones relaciones.json] [--analisis analisis.json] \
      [--historial historial.json] [--validaciones validaciones.json] \
      --fecha 2026-11-05 --corrida 2026-11-05-1 --salida-dir salida/
  python3 grafo.py agregar --tipo relacion|evento|analisis --base relaciones.json --nuevos nuevas.json --salida relaciones.json
  python3 grafo.py validar --tipo relacion|evento|analisis archivo.json
Solo usa la biblioteca estándar.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata

# ----------------------------------------------------------------- vocabularios cerrados
TIPOS_EVENTO = [
    "Expedición", "Sanción", "Promulgación", "Publicación", "Entrada en vigencia", "Aprobación",
    "Decisión judicial", "Radicación", "Publicación para comentarios", "Cierre de comentarios",
    "Ponentes asignados", "Ponencia", "Debate programado", "Aprobación en comisión", "Aprobación en primer debate",
    "Aprobación en segundo debate", "Aprobación en tercer debate", "Aprobación en cuarto debate", "Conciliación",
    "Paso a sanción", "Objeción", "Subsanación", "Revisión de la Corte", "Archivo", "Retiro", "Sesión", "Hito",
    "Noticia", "Reporte en prensa", "Modificación", "Derogatoria", "Captura",
]
TIPOS_RELACION = [
    "Modifica", "Adiciona", "Sustituye", "Subroga", "Deroga", "Reglamenta", "Compila", "Prorroga", "Suspende",
    "Corrige", "Propone modificar", "Propone adicionar", "Propone sustituir", "Propone subrogar", "Propone derogar",
    "Propone reglamentar", "Declara exequible", "Declara exequible condicionado", "Declara inexequible",
    "Se inhibe", "Declara nulidad", "Suspende provisionalmente", "Cita o aplica norma", "Cita providencia",
    "Se convirtió en", "Expedido mediante", "Hito de", "Relacionado",
]
ESTADOS_VALIDACION = ["Confirmada", "Sugerida por IA", "Pendiente de revisión", "Descartada"]
METODOS = [
    "Validación humana", "Extracción por IA de fuente oficial", "Patrón sobre epígrafe oficial",
    "Patrón sobre título descriptivo", "Patrón sobre resumen del registro", "Estado del registro",
    "Nota del registro", "Fecha del registro", "Coincidencia de número", "Captura de texto completo",
]
TIPOS_ANALISIS = [
    "Magistrado ponente", "Expediente", "Radicado", "Tipo de providencia", "Problema jurídico", "Decisión",
    "Regla jurídica", "Fundamento", "Precedente citado", "Norma aplicada", "Autor", "Ponente", "Comisión",
    "Instrumento territorial", "Plazo de comentarios", "Memoria justificativa", "Análisis de impacto normativo",
    "Regla de vigencia", "Respuesta a comentarios",
]
ESTADO_EXTRACCION = ["Solo metadatos", "Fragmentos literales", "Texto parcial", "Texto completo"]
ESTADO_REGISTRO = ["Pendiente", "Capturado", "Procesado", "Validado"]

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "sept": 9,
         "oct": 10, "nov": 11, "dic": 12, "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "")) if unicodedata.category(c) != "Mn").lower()


def h(*partes, n=12):
    return hashlib.sha256("|".join(str(p) for p in partes).encode("utf-8")).hexdigest()[:n]


def estado_base(e):
    return re.split(r"\s+\(", (e or "").strip(), maxsplit=1)[0].strip()


def detalle(e):
    m = re.search(r"\((.*)\)\s*$", e or "")
    return m.group(1) if m else ""


FECHA_CORTA = re.compile(r"\b(\d{1,2})[-\s](?:de\s+)?(ene|feb|mar|abr|may|jun|jul|ago|sept?|oct|nov|dic)[a-z]*\.?[-\s](?:de\s+)?(\d{4})\b", re.I)


def fechas_en(texto):
    """Fechas explícitas como 4-nov-2026, 29 oct 2026 o 4 de noviembre de 2026 → AAAA-MM-DD."""
    out = []
    for d, m, a in FECHA_CORTA.findall(texto or ""):
        mm = MESES.get(sin_tildes(m)[:4].rstrip("."), MESES.get(sin_tildes(m)[:3]))
        if mm and 1 <= int(d) <= 31:
            out.append(f"{a}-{mm:02d}-{int(d):02d}")
    return out


# ----------------------------------------------------------------- referencias normativas
TIPO_NORMA = (r"(?P<tipo>Decreto\s+(?:Ley|Legislativo|Único\s+Reglamentario(?:\s+del\s+Sector\s+[A-ZÁÉÍÓÚ][\w ,]*?)?,?(?:\s+Decreto)?)"
              r"|Decreto|Ley(?:es)?(?:\s+(?:Estatutaria|Orgánica))?|Acto\s+Legislativo|Resoluci[oó]n|Acuerdo(?:\s+(?:Municipal|Metropolitano|Distrital|Local))?"
              r"|Ordenanza|Circular(?:\s+Externa)?)")
NORMA_REF = re.compile(
    TIPO_NORMA + r"\s+(?:No\.?\s*|n[úu]mero\s+)?(?P<num>\d[\d.]*)"
    r"(?:\s+(?:del?|de)\s+(?:(?:(?:\d{1,2}\s+(?:de\s+)?)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+(?:de|del)\s+)|(?:\d{1,2}/\d{1,2}/))?(?P<anio>(?:19|20)\d{2}))?",
    re.I)
CONSTITUCION_REF = re.compile(r"art[íi]culos?\s+(?P<arts>[\d, y]+?)\s+de\s+la\s+Constituci[oó]n(?:\s+Pol[íi]tica)?", re.I)
ARTICULO_PREVIO = re.compile(r"(?P<parte>(?:el|los|un|una)?\s*(?:art(?:[íi]culo)?s?\.?|par[áa]grafo|numeral|inciso|literal|cap[íi]tulo|t[íi]tulo|secci[oó]n|parte|libro)\b[^;]{0,120}?)\s+(?:del?|de\s+la|al)\s*$", re.I)
PROVIDENCIA_REF = re.compile(r"\b(SU|C|T|A)\s?-\s?(\d{1,4})(?:\s*/\s*|\s+de\s+)(\d{2}(?:\d{2})?)\b")

VERBOS = [
    ("Modifica", r"modific|modif[íi]qu"), ("Adiciona", r"adicion|adici[óo]n"), ("Sustituye", r"sustitu|sustit[úu]y"),
    ("Subroga", r"subrog|subr[óo]g"), ("Deroga", r"derog|der[óo]g"), ("Reglamenta", r"reglament|regl[áa]ment"),
    ("Compila", r"compil"), ("Prorroga", r"prorrog|prorr[óo]g"), ("Suspende", r"suspend"), ("Corrige", r"corrig|corr[íi]j"),
]
VERBO_RE = re.compile(r"\b(" + "|".join(p for _, p in VERBOS) + r")([a-záéíóúñ]*)", re.I)
PARTICIPIO = re.compile(r"(ad[oa]s?|id[oa]s?|ando|endo|iendo|ador(?:a|es)?)$", re.I)
CONECTOR = re.compile(r"^[\s,;:]*(?:(?:y|e|o|el|la|los|las|del|de|al|en|así como|igualmente|también)\b[\s,;:]*)*$", re.I)


def tipo_base_norma(t):
    t = sin_tildes(t)
    for k in ("acto legislativo", "ley", "decreto", "resolucion", "ordenanza", "circular", "acuerdo"):
        if t.startswith(k):
            return k
    return t.split()[0] if t else ""


def clave_norma(tipo, num, anio):
    return f"{tipo_base_norma(tipo)}|{re.sub(r'[^0-9]', '', num or '').lstrip('0')}|{anio or ''}"


def nombre_norma(tipo, num, anio):
    t = re.sub(r"\s+", " ", tipo).strip()
    t = {"ley": "Ley", "decreto": "Decreto", "resolucion": "Resolución", "ordenanza": "Ordenanza", "circular": "Circular",
         "acuerdo": "Acuerdo", "acto legislativo": "Acto Legislativo"}.get(tipo_base_norma(t), t)
    if sin_tildes(tipo).startswith("decreto ley"):
        t = "Decreto Ley"
    elif sin_tildes(tipo).startswith("decreto legislativo"):
        t = "Decreto Legislativo"
    return f"{t} {num.rstrip('.')}" + (f" de {anio}" if anio else "")


BLOQUEO = re.compile(r"en el marco d|declarad[ao]s? (?:mediante|por|en)|con fundamento en|de que trata|previst[ao]s? en|establecid[ao]s? en|conforme a|de acuerdo con|financiad|con cargo a|en virtud d|expedid[ao]s? (?:mediante|por)", re.I)


def verbos_en(texto):
    out = []
    ult = None
    for m in VERBO_RE.finditer(texto):
        if not PARTICIPIO.search(m.group(0)):
            ult = m
    if ult and BLOQUEO.search(texto[ult.end():]):
        return out
    for m in VERBO_RE.finditer(texto):
        palabra = m.group(0)
        if PARTICIPIO.search(palabra):
            continue
        tipo = next(t for t, p in VERBOS if re.match(p, palabra, re.I))
        if tipo not in out:
            out.append(tipo)
    return out


def referencias(texto):
    """[(inicio, fin, nombre, clave, parte)] de normas citadas en el texto, en orden."""
    refs = []
    for m in NORMA_REF.finditer(texto or ""):
        tipo, num, anio = m.group("tipo"), m.group("num"), m.group("anio") or ""
        if "único reglamentario" in tipo.lower() or "unico reglamentario" in sin_tildes(tipo):
            tipo = "Decreto"
        if tipo.lower().startswith("leyes"):
            tipo = "Ley"
        previo = texto[max(0, m.start() - 140):m.start()]
        pa = ARTICULO_PREVIO.search(previo)
        parte = re.sub(r"\s+", " ", pa.group("parte")).strip() if pa else ""
        refs.append((m.start(), m.end(), nombre_norma(tipo, num, anio), clave_norma(tipo, num, anio), parte))
    for m in CONSTITUCION_REF.finditer(texto or ""):
        refs.append((m.start(), m.end(), "Constitución Política", "constitucion||1991", "art. " + m.group("arts").strip()))
    refs.sort()
    return refs


def relaciones_por_verbo(texto):
    """Para cada norma citada, los verbos que la gobiernan (el más cercano antes, heredado si solo hay conectores)."""
    out, prev_fin, prev_verbos = [], 0, []
    for ini, fin, nombre, clave, parte in referencias(texto):
        ventana = texto[prev_fin:ini]
        vs = verbos_en(ventana)
        if not vs:
            sin_partes = ARTICULO_PREVIO.sub("", ventana)
            vs = prev_verbos if (prev_verbos and CONECTOR.match(re.sub(r"\b(?:art(?:[íi]culo)?s?\.?|par[áa]grafo|numeral|inciso|literal|cap[íi]tulo|t[íi]tulo|secci[oó]n|parte|libro)\b[\w\s.°º,]*", "", sin_partes))) else []
        frag_ini = max(0, texto.rfind(",", 0, max(prev_fin, ini - 160)) + 1, prev_fin if vs and vs != prev_verbos else max(0, ini - 160))
        fragmento = texto[frag_ini:fin].strip(" ,;")
        out.append({"nombre": nombre, "clave": clave, "parte": parte, "verbos": vs, "fragmento": fragmento})
        prev_fin, prev_verbos = fin, vs or prev_verbos
    return out


# ----------------------------------------------------------------- derivación desde novedades
ESTADO_A_EVENTO = {
    "Expedida": "Expedición", "Expedido": "Expedición", "Sancionada": "Sanción", "Sancionado": "Sanción",
    "Publicada": "Publicación", "Publicado": "Publicación", "Aprobada": "Aprobación", "Reportada": "Reporte en prensa",
    "Decidida": "Decisión judicial", "Pendiente de fallo": "Hito", "Radicado": "Radicación",
    "Publicado para comentarios": "Publicación para comentarios", "Comentarios cerrados": "Cierre de comentarios",
    "Con ponentes asignados": "Ponentes asignados", "Con ponencia para primer debate": "Ponencia",
    "Con ponencia para segundo debate": "Ponencia", "En primer debate": "Debate programado",
    "Segundo debate programado": "Debate programado", "Aprobado en comisión": "Aprobación en comisión",
    "Aprobado en primer debate": "Aprobación en primer debate", "Aprobado en segundo debate": "Aprobación en segundo debate",
    "Aprobado en tercer debate": "Aprobación en tercer debate", "Aprobado en cuarto debate": "Aprobación en cuarto debate",
    "En conciliación": "Conciliación", "Pasa a sanción": "Paso a sanción", "Subsanación": "Subsanación",
    "Revisión de la Corte": "Revisión de la Corte", "Archivado": "Archivo", "Retirado": "Retiro",
    "Anunciada": "Hito", "Programada": "Sesión", "En curso": "Sesión", "Realizada": "Sesión", "Aplazada": "Sesión",
    "Cancelada": "Sesión", "En estudio": "Hito", "En trámite": "Hito",
}
VIGENCIA_TXT = re.compile(r"\brige\b|regir|vigen|a partir d|desde el", re.I)
DEBIL = re.compile(r"seg[úu]n (la )?prensa|se reporta|reportad|seg[úu]n la fuente|no confirmad|por confirmar|sin confirmar", re.I)


def evento_de_fecha(r):
    """Qué fue lo que pasó en `fecha` según la categoría y el estado (esquema: expedición, sanción, decisión o radicación)."""
    base = estado_base(r.get("estado"))
    cat, tipo = r.get("categoria"), r.get("tipo", "")
    if cat == "Jurisprudencia":
        return "Decisión judicial"
    if cat == "Agenda":
        return "Sesión"
    if cat == "Noticia jurídica":
        return "Noticia"
    if tipo == "Hito":
        return ESTADO_A_EVENTO.get(base, "Hito")
    if cat == "Proyecto":
        if r.get("fecha") and r.get("fecha") in fechas_en(r.get("estado")):
            return ESTADO_A_EVENTO.get(base, "Hito")
        if re.match(r"Proyecto de (decreto|resoluci)", tipo, re.I):
            return "Publicación para comentarios"
        return "Radicación"
    return ESTADO_A_EVENTO.get(base, "Expedición")


def nuevo_evento(doc, tipo, fecha, descripcion, metodo, origen, r, debil=False):
    return {
        "id": "ev-" + h(doc, tipo, fecha, origen), "doc_id": doc, "fecha": fecha, "tipo_evento": tipo,
        "descripcion": descripcion, "fuente_url": r.get("url") or r.get("url_alterna") or "",
        "verificacion": str(r.get("verificacion", ""))[:2], "metodo": metodo, "origen": origen,
        "estado_validacion": "Pendiente de revisión" if debil or str(r.get("verificacion", "")).startswith("V3") else "Sugerida por IA",
    }


def eventos_de(r):
    doc, out = r["id"], []
    if r.get("fecha"):
        t = evento_de_fecha(r)
        out.append(nuevo_evento(doc, t, r["fecha"], f"{t} según el registro ({r.get('tipo','')} {r.get('numero','')})".strip(),
                                "Fecha del registro", "novedades.fecha", r))
    det = detalle(r.get("estado"))
    base = estado_base(r.get("estado"))
    # Una fecha de vigencia escrita en el estado («rige desde…») no es un evento del trámite y no se infiere.
    for f in ([] if VIGENCIA_TXT.search(det) else fechas_en(det)):
        t = ESTADO_A_EVENTO.get(base, "Hito")
        if not any(e["fecha"] == f and e["tipo_evento"] == t for e in out):
            out.append(nuevo_evento(doc, t, f, f"{base}: {det}", "Estado del registro", "novedades.estado", r, bool(DEBIL.search(det))))
    for m in re.finditer(r"\[(\d{1,2}-[a-z]{3}-\d{4}): estado normalizado; antes «(.+?)»\.\]", r.get("nota") or ""):
        previo = m.group(2)
        for f in ([] if VIGENCIA_TXT.search(previo) else fechas_en(previo)):
            t = ESTADO_A_EVENTO.get(estado_base(previo), None) or next((v for k, v in ESTADO_A_EVENTO.items() if sin_tildes(previo).startswith(sin_tildes(k))), "Hito")
            if not any(e["fecha"] == f and e["tipo_evento"] == t for e in out):
                out.append(nuevo_evento(doc, t, f, f"Estado anterior: {previo}", "Nota del registro", "novedades.nota", r, bool(DEBIL.search(previo))))
    if r.get("fecha_captura"):
        out.append(nuevo_evento(doc, "Captura", r["fecha_captura"], "Primera captura por el monitor", "Fecha del registro", "novedades.fecha_captura", r))
        out[-1]["estado_validacion"] = "Sugerida por IA"
    return out


def nueva_relacion(origen, destino_id, destino_ref, tipo, fragmento, literal, url, metodo, estado, nota="", parte=""):
    return {
        "id": "rel-" + h(origen, tipo, destino_ref, parte), "origen_id": origen, "destino_id": destino_id or "",
        "destino_ref": destino_ref, "parte": parte, "tipo": tipo, "fragmento": (fragmento or "")[:400],
        "fragmento_literal": "sí" if literal else "no", "fuente_url": url or "", "metodo": metodo,
        "estado_validacion": estado, "nota": nota,
    }


def indice_normas(novedades):
    idx = {}
    for r in novedades:
        if r.get("categoria") not in ("Norma",) or not r.get("numero"):
            continue
        num = r["numero"].split("/")[0]
        anio = (r.get("fecha") or "")[:4] or (re.search(r"(19|20)\d{2}", r.get("id", "")) or [""])[0]
        idx.setdefault(clave_norma(r.get("tipo", ""), num, anio), r["id"])
    return idx


def indice_providencias(novedades):
    idx = {}
    for r in novedades:
        m = PROVIDENCIA_REF.search((r.get("numero") or "").replace(" ", ""))
        if r.get("categoria") == "Jurisprudencia" and m:
            idx[f"{m.group(1)}-{int(m.group(2))}/{m.group(3)[-2:]}"] = r["id"]
    return idx


def relaciones_de(r, idx_n, idx_p):
    out, doc = [], r["id"]
    cat, tit, ver = r.get("categoria"), r.get("titulo") or "", str(r.get("verificacion", ""))
    url = r.get("url") or r.get("url_alterna") or ""
    descriptivo = "título descriptivo" in tit.lower() or ver.startswith("V3")
    # 1) Epígrafe: modifica, adiciona, deroga, reglamenta…
    if cat in ("Norma", "Proyecto"):
        for ref in relaciones_por_verbo(tit):
            if ref["clave"].split("|")[0] == tipo_base_norma(r.get("tipo", "")) and ref["clave"] == clave_norma(r.get("tipo", ""), (r.get("numero") or "").split("/")[0], (r.get("fecha") or "")[:4]):
                continue  # la norma se nombra a sí misma
            for v in ref["verbos"]:
                tipo = v if cat == "Norma" else "Propone " + {"Modifica": "modificar", "Adiciona": "adicionar", "Sustituye": "sustituir", "Subroga": "subrogar", "Deroga": "derogar", "Reglamenta": "reglamentar"}.get(v, "")
                if tipo == "Propone ":
                    tipo = "Relacionado"
                metodo = "Patrón sobre título descriptivo" if descriptivo else "Patrón sobre epígrafe oficial"
                estado = "Pendiente de revisión" if descriptivo else "Sugerida por IA"
                out.append(nueva_relacion(doc, idx_n.get(ref["clave"]), ref["nombre"], tipo, ref["fragmento"], not descriptivo, url, metodo, estado, parte=ref["parte"]))
    # 2) Estado del proyecto: se convirtió en ley o se expidió mediante decreto.
    if cat == "Proyecto":
        det = detalle(r.get("estado"))
        for ref in referencias(det):
            base = estado_base(r.get("estado"))
            tipo = "Se convirtió en" if base in ("Sancionado",) else "Expedido mediante" if base in ("Expedido",) else ""
            if tipo:
                out.append(nueva_relacion(doc, idx_n.get(ref[3]), ref[2], tipo, r.get("estado"), False, url, "Estado del registro",
                                          "Pendiente de revisión" if DEBIL.search(det) or ver.startswith("V3") else "Sugerida por IA"))
    # 3) Providencias: qué decide sobre qué norma, y qué providencias cita (desde el resumen propio: nunca literal).
    if cat == "Jurisprudencia":
        texto = r.get("resumen") or ""
        for clausula in re.split(r"(?<=[.;])\s+(?=[A-ZÁÉÍÓÚ¿«(])|;\s+", texto):
            s = sin_tildes(clausula)
            if "inexequib" in s:
                tipo = "Declara inexequible"
            elif "condicionad" in s or "en el entendido" in s:
                tipo = "Declara exequible condicionado"
            elif "exequib" in s:
                tipo = "Declara exequible"
            elif "inhib" in s:
                tipo = "Se inhibe"
            elif "nulidad" in s or "nulo" in s or "anula" in s:
                tipo = "Declara nulidad"
            elif "suspend" in s and "provisional" in s:
                tipo = "Suspende provisionalmente"
            else:
                tipo = "Cita o aplica norma"
            clave_dec = {"Declara inexequible": r"inexequib", "Declara exequible condicionado": r"exequib|condicionad", "Declara exequible": r"exequib",
                         "Se inhibe": r"inhib", "Declara nulidad": r"nulidad|nulo|anula", "Suspende provisionalmente": r"suspend"}.get(tipo)
            pos = [m.end() for m in re.finditer(clave_dec, sin_tildes(clausula))] if clave_dec else []
            usado = False
            for ini, fin, nombre, clave, parte in referencias(clausula):
                # La decisión recae sobre la primera norma citada poco después de la palabra que decide; las demás se citan o aplican.
                t = tipo
                if clave_dec:
                    cerca = any(0 <= ini - p_ <= 90 for p_ in pos)
                    t = tipo if (cerca and not usado) else "Cita o aplica norma"
                    usado = usado or t == tipo
                out.append(nueva_relacion(doc, idx_n.get(clave), nombre, t, clausula.strip(), False, url, "Patrón sobre resumen del registro",
                                          "Pendiente de revisión", nota="Identificada en el resumen del monitor, no en el texto de la providencia.", parte=parte))
        propio = (r.get("numero") or "").replace(" ", "")
        for m in PROVIDENCIA_REF.finditer(texto + " " + tit):
            k = f"{m.group(1)}-{int(m.group(2))}/{m.group(3)[-2:]}"
            if k.replace("/", "") in propio.replace("/", "") or k == propio:
                continue
            out.append(nueva_relacion(doc, idx_p.get(k), f"Sentencia {k}", "Cita providencia", texto, False, url, "Patrón sobre resumen del registro",
                                      "Pendiente de revisión", nota="Cita mencionada en el resumen; no se ha leído la providencia citante."))
    # Sin duplicados (mismo id)
    vistos, unicas = set(), []
    for x in out:
        if x["id"] not in vistos:
            vistos.add(x["id"])
            unicas.append(x)
    return unicas


def analisis_de(r):
    """Datos de la providencia que el registro ya trae (exp., M. P.), con su origen; nunca se completan de memoria."""
    out, doc = [], r["id"]
    texto = (r.get("resumen") or "") + " " + (r.get("nota") or "")
    debil = str(r.get("verificacion", "")).startswith("V3")
    if r.get("categoria") != "Jurisprudencia":
        return out
    m = re.search(r"M\.\s?P\.?:?\s+((?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)(?:\s+(?:de\s+la\s+|del\s+|de\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,4})", texto)
    if m and not re.search(r"Jur[íi]dic|Corte|Consejo|Sala|Secci[óo]n|Tribunal|Ministerio|Rep[úu]blica", m.group(1)):
        out.append(_an(doc, "Magistrado ponente", m.group(1).rstrip(".,)"), m.group(0), r, debil))
    m = re.search(r"\bexp(?:ediente)?\.?\s+([A-Z]{1,3}-?\s?[\d.]+(?:\s+(?:y|AC|acumulad[oa]s?)[^,;)]*)?)", texto)
    if m:
        out.append(_an(doc, "Expediente", m.group(1).strip().rstrip(".,"), m.group(0), r, debil))
    num = (r.get("numero") or "").replace(" ", "")
    tp = {"C": "Sentencia de constitucionalidad", "T": "Sentencia de tutela", "SU": "Sentencia de unificación", "A": "Auto"}
    mm = re.match(r"^(SU|C|T|A)-", num)
    if mm:
        out.append(_an(doc, "Tipo de providencia", tp[mm.group(1)], f"Prefijo del número {num}", r, False, metodo="Coincidencia de número"))
    elif re.fullmatch(r"\d{20,23}", num):
        out.append(_an(doc, "Radicado", num, "Número del registro", r, False, metodo="Coincidencia de número"))
    return out


def _an(doc, tipo, valor, fragmento, r, debil, metodo="Patrón sobre resumen del registro"):
    return {"id": "an-" + h(doc, tipo, valor), "doc_id": doc, "tipo": tipo, "valor": valor, "fragmento": fragmento,
            "fragmento_literal": "no", "fuente_url": r.get("url") or "", "metodo": metodo,
            "estado_validacion": "Pendiente de revisión" if debil else "Sugerida por IA", "nota": ""}


INSTRUMENTOS = [
    ("POT", r"\bplan de ordenamiento territorial\b|\bPOT\b"), ("PBOT", r"\bPBOT\b|plan b[aá]sico de ordenamiento"),
    ("EOT", r"\bEOT\b|esquema de ordenamiento"), ("Plan de desarrollo", r"plan de desarrollo"),
    ("Plan parcial", r"plan parcial"), ("Plan maestro", r"plan maestro"), ("Norma urbanística", r"norma(s)? urban[íi]stic|licencia|curadur|urbanismo|espacio p[úu]blico"),
    ("Presupuesto", r"presupuest|vigencias futuras|emprést"), ("Planta de personal", r"planta (global )?de (cargos|personal)|manual (espec[íi]fico )?de funciones"),
    ("Tributario territorial", r"impuesto|estatuto tributario|predial|tasa|contribuci[oó]n"),
]


def instrumento(r):
    if r.get("nivel") == "Nacional" or r.get("categoria") not in ("Norma", "Proyecto"):
        return ""
    t = (r.get("titulo") or "") + " " + (r.get("resumen") or "")
    for nombre, pat in INSTRUMENTOS:
        if re.search(pat, t, re.I):
            return nombre
    return "Acto administrativo territorial"


# ----------------------------------------------------------------- historial y trazabilidad
CAMPOS_HASH = ["id", "categoria", "tipo", "numero", "fecha", "organo", "sala", "titulo", "resumen", "estado", "url",
               "url_alterna", "verificacion"]


def hash_registro(r):
    return hashlib.sha256(json.dumps({k: r.get(k, "") for k in CAMPOS_HASH}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def historial_de_notas(r):
    out = []
    for m in re.finditer(r"\[(\d{1,2}-[a-z]{3}-\d{4}): estado normalizado; antes «(.+?)»\.\]", r.get("nota") or ""):
        f = (fechas_en(m.group(1).replace("-", " ")) or [""])[0]
        out.append({"id": "hi-" + h(r["id"], "estado", f, m.group(2)), "doc_id": r["id"], "fecha": f, "corrida": "",
                    "campo": "estado", "antes": m.group(2), "despues": "(normalizado a la lista cerrada)",
                    "origen": "Nota del registro"})
    return out


def historial_diff(prev, nuevo, fecha, corrida):
    out = []
    p = {r["id"]: r for r in prev}
    for r in nuevo:
        a = p.get(r["id"])
        if not a:
            continue
        for k in sorted(set(a) | set(r)):
            if k in ("nota",) or str(a.get(k, "")) == str(r.get(k, "")):
                continue
            out.append({"id": "hi-" + h(r["id"], k, fecha, corrida, a.get(k, "")), "doc_id": r["id"], "fecha": fecha, "corrida": corrida,
                        "campo": k, "antes": str(a.get(k, ""))[:300], "despues": str(r.get(k, ""))[:300], "origen": "Comparación entre corridas"})
    return out


ESTADOS_DOC = ("Capturado", "Procesado", "Extracción exitosa", "Verificado", "Pendiente de confirmación")


def _host(u):
    m = re.match(r"https?://([^/?#\s]+)", u or "")
    return m.group(1).lower().removeprefix("www.") if m else ""


def trazabilidad(novedades, eventos, relaciones, analisis, historial, validaciones, fecha, corpus=None):
    """Una fila por registro. `estado_validacion` se conserva (compatibilidad) y se agregan, por reglas fijas:
    `estado_confiabilidad` (Capturado, Procesado, Extracción exitosa, Verificado, Pendiente de confirmación),
    `corroboracion` (dominios distintos que respaldan el registro) y `limitaciones` (texto corto)."""
    por = lambda xs, k: {d: [x for x in xs if x.get(k) == d] for d in {x.get(k) for x in xs}}
    ev, re_, an, hi = por(eventos, "doc_id"), por(relaciones, "origen_id"), por(analisis, "doc_id"), por(historial, "doc_id")
    val = {v["id"]: v for v in validaciones if v.get("objeto") == "registro"}
    cor = {c["doc_id"]: c for c in (corpus or []) if str(c.get("estado", "")).startswith("capturado")}
    out = []
    for r in novedades:
        d = r["id"]
        lit = any(x.get("fragmento_literal") == "sí" and x.get("metodo") in ("Extracción por IA de fuente oficial", "Captura de texto completo") for x in re_.get(d, []) + an.get(d, []))
        c = cor.get(d)
        ext = "Texto completo" if c or any(x.get("metodo") == "Captura de texto completo" for x in an.get(d, [])) else "Fragmentos literales" if lit else "Solo metadatos"
        v = val.get(d)
        validado = bool(v and v.get("decision") == "validado")
        pendiente = str(r.get("verificacion", "")).startswith("V3") or not (r.get("url") or "").startswith("http")
        if validado:
            est = "Validado"
        elif pendiente:
            est = "Pendiente"
        elif ext != "Solo metadatos":
            est = "Procesado"
        else:
            est = "Capturado"
        derivados = len(re_.get(d, [])) + len(an.get(d, [])) + sum(1 for x in ev.get(d, []) if x.get("tipo_evento") != "Captura")
        if pendiente:
            conf = "Pendiente de confirmación"
        elif ext == "Texto completo" and validado and str(r.get("verificacion", "")).startswith(("V1", "V2")):
            conf = "Verificado"
        elif ext == "Texto completo":
            conf = "Extracción exitosa"
        elif derivados:
            conf = "Procesado"
        else:
            conf = "Capturado"
        hosts = {x for x in (_host(r.get("url")), _host(r.get("url_alterna"))) if x}
        hosts |= {_host(x.get("fuente_url")) for x in re_.get(d, []) + an.get(d, []) + ev.get(d, []) if _host(x.get("fuente_url"))}
        lim = []
        if ext != "Texto completo":
            lim.append("Sin texto completo del documento oficial: lo que se afirma sale de metadatos y fragmentos.")
        if str(r.get("verificacion", "")).startswith("V3"):
            lim.append("Fuente secundaria (prensa o reporte): falta confirmar en la fuente oficial.")
        if not (r.get("url") or "").startswith("http"):
            lim.append("Sin enlace al documento original.")
        if len(hosts) < 2:
            lim.append("Una sola fuente: no corroborado por otra independiente.")
        if validado and ext != "Texto completo":
            lim.append("Validado por una persona sin texto completo capturado: no alcanza «Verificado».")
        out.append({"doc_id": d, "hash_registro": hash_registro(r)[:16], "fecha_captura": r.get("fecha_captura", ""),
                    "fecha_publicacion": r.get("fecha", ""), "fecha_procesamiento": fecha, "estado_extraccion": ext,
                    "estado_validacion": est, "estado_confiabilidad": conf, "corroboracion": len(hosts),
                    "validado_por": (v or {}).get("por", ""), "validado_el": (v or {}).get("at", "")[:10],
                    "n_eventos": len(ev.get(d, [])), "n_relaciones": len(re_.get(d, [])), "n_analisis": len(an.get(d, [])),
                    "n_cambios": len(hi.get(d, [])), "hash_original": (c or {}).get("sha256", ""), "archivo_original": (c or {}).get("archivo", ""),
                    "limitaciones": " ".join(lim),
                    "nota": ("Texto capturado del original el " + c.get("fecha_captura", "") + " (" + c.get("metodo", "") + ").") if c else
                            "Hash del registro (metadatos), no del archivo original: el archivo aún no se conserva."})
    return out


# ----------------------------------------------------------------- validación y fusión
REQ = {
    "relacion": ["id", "origen_id", "destino_ref", "tipo", "fragmento", "fragmento_literal", "fuente_url", "metodo", "estado_validacion"],
    "evento": ["id", "doc_id", "fecha", "tipo_evento", "descripcion", "metodo", "origen", "estado_validacion"],
    "analisis": ["id", "doc_id", "tipo", "valor", "fragmento", "fragmento_literal", "fuente_url", "metodo", "estado_validacion"],
}


def validar(tipo, filas):
    errores = []
    for i, x in enumerate(filas):
        for k in REQ[tipo]:
            if k not in x or (x[k] in ("", None) and k not in ("fragmento", "fuente_url")):
                errores.append(f"{i} {x.get('id','?')}: falta {k}")
        if x.get("estado_validacion") not in ESTADOS_VALIDACION:
            errores.append(f"{i} {x.get('id','?')}: estado_validacion fuera de lista ({x.get('estado_validacion')})")
        if x.get("metodo") not in METODOS:
            errores.append(f"{i} {x.get('id','?')}: método fuera de lista ({x.get('metodo')})")
        if tipo == "relacion" and x.get("tipo") not in TIPOS_RELACION:
            errores.append(f"{i} {x.get('id','?')}: tipo de relación fuera de lista ({x.get('tipo')})")
        if tipo == "evento":
            if x.get("tipo_evento") not in TIPOS_EVENTO:
                errores.append(f"{i} {x.get('id','?')}: tipo de evento fuera de lista ({x.get('tipo_evento')})")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x.get("fecha") or ""):
                errores.append(f"{i} {x.get('id','?')}: fecha inválida")
            if x.get("tipo_evento") == "Entrada en vigencia" and not x.get("fragmento"):
                errores.append(f"{i} {x.get('id','?')}: la entrada en vigencia exige fragmento de la norma que la fija")
        if tipo == "analisis" and x.get("tipo") not in TIPOS_ANALISIS:
            errores.append(f"{i} {x.get('id','?')}: tipo de análisis fuera de lista ({x.get('tipo')})")
        if tipo in ("relacion", "analisis"):
            if x.get("metodo") == "Extracción por IA de fuente oficial":
                if x.get("fragmento_literal") != "sí" or not x.get("fragmento") or not (x.get("fuente_url") or "").startswith("http"):
                    errores.append(f"{i} {x.get('id','?')}: lo extraído por IA exige fragmento literal y URL de la fuente")
            if tipo == "analisis" and x.get("tipo") == "Regla jurídica" and x.get("fragmento_literal") != "sí":
                errores.append(f"{i} {x.get('id','?')}: una regla jurídica exige fragmento literal de la providencia")
            if x.get("estado_validacion") == "Confirmada" and x.get("metodo") != "Validación humana":
                errores.append(f"{i} {x.get('id','?')}: «Confirmada» solo con validación humana")
    return errores


DERIVADOS = {"Fecha del registro", "Estado del registro", "Nota del registro", "Patrón sobre epígrafe oficial",
             "Patrón sobre título descriptivo", "Patrón sobre resumen del registro", "Coincidencia de número"}


def fusionar(base, nuevos):
    """Une por id; lo nuevo reemplaza lo viejo, salvo que lo viejo tenga validación humana."""
    out = {x["id"]: x for x in base}
    for x in nuevos:
        v = out.get(x["id"])
        if v and v.get("metodo") == "Validación humana":
            continue
        out[x["id"]] = x
    return list(out.values())


def aplicar_validaciones(filas, validaciones, objeto):
    val = {v["id"]: v for v in validaciones if v.get("objeto") == objeto}
    for x in filas:
        v = val.get(x["id"])
        if not v:
            continue
        if v.get("decision") in ("confirmada", "descartada"):
            x["estado_validacion"] = "Confirmada" if v["decision"] == "confirmada" else "Descartada"
            x["metodo_original"] = x.get("metodo_original") or x.get("metodo")
            x["metodo"] = "Validación humana"
            x["validado_el"] = (v.get("at") or "")[:10]
            if v.get("nota"):
                x["nota"] = (x.get("nota", "") + " | Validación: " + v["nota"]).strip(" |")
    return filas


def cargar(p, defecto=None):
    if not p or not os.path.exists(p):
        return [] if defecto is None else defecto
    d = json.load(open(p, encoding="utf-8"))
    return d.get("rows", d.get("data", d)) if isinstance(d, dict) else d


def guardar(p, filas):
    json.dump(filas, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def procesar(a):
    nov = cargar(a.novedades)
    idx_n, idx_p = indice_normas(nov), indice_providencias(nov)
    vals = cargar(a.validaciones)
    # Derivados (se regeneran) + agregados por corridas o personas (se conservan)
    ev_prev, re_prev, an_prev = cargar(a.eventos), cargar(a.relaciones), cargar(a.analisis)
    ev = [x for x in ev_prev if x.get("metodo") not in DERIVADOS]
    rel = [x for x in re_prev if x.get("metodo") not in DERIVADOS and x.get("metodo_original") not in DERIVADOS]
    an = [x for x in an_prev if x.get("metodo") not in DERIVADOS]
    hum_rel = {x["id"]: x for x in re_prev if x.get("metodo") == "Validación humana"}
    d_ev, d_rel, d_an = [], [], []
    for r in nov:
        d_ev += eventos_de(r)
        d_rel += relaciones_de(r, idx_n, idx_p)
        d_an += analisis_de(r)
        ins = instrumento(r)
        if ins:
            d_an.append(_an(r["id"], "Instrumento territorial", ins, "Clasificación por palabras del título y el resumen", r, False, metodo="Patrón sobre resumen del registro"))
    ev = fusionar(d_ev, ev)
    rel = fusionar(d_rel, rel)
    rel = [hum_rel.get(x["id"], x) for x in rel] + [x for k, x in hum_rel.items() if k not in {y["id"] for y in rel}]
    an = fusionar(d_an, an)
    rel = aplicar_validaciones(rel, vals, "relacion")
    ev = aplicar_validaciones(ev, vals, "evento")
    an = aplicar_validaciones(an, vals, "analisis")
    # Las relaciones con origen que ya no existe se conservan pero se marcan
    ids = {r["id"] for r in nov}
    for x in rel:
        if x["origen_id"] not in ids:
            x["nota"] = (x.get("nota", "") + " | Origen ausente del repositorio").strip(" |")
    hist = cargar(a.historial)
    vistos = {x["id"] for x in hist}
    nuevos_h = [x for r in nov for x in historial_de_notas(r)]
    if a.anterior:
        nuevos_h += historial_diff(cargar(a.anterior), nov, a.fecha, a.corrida)
    hist += [x for x in nuevos_h if x["id"] not in vistos]
    tz = trazabilidad(nov, ev, rel, an, hist, vals, a.fecha, cargar(getattr(a, 'corpus', None)))
    ev.sort(key=lambda x: (x["fecha"], x["doc_id"], x["tipo_evento"]), reverse=True)
    rel.sort(key=lambda x: (x["origen_id"], x["tipo"], x["destino_ref"]))
    an.sort(key=lambda x: (x["doc_id"], x["tipo"]))
    hist.sort(key=lambda x: (x["fecha"], x["doc_id"]), reverse=True)
    errores = validar("evento", ev) + validar("relacion", rel) + validar("analisis", an)
    os.makedirs(a.salida_dir, exist_ok=True)
    for nombre, filas in (("eventos", ev), ("relaciones", rel), ("analisis", an), ("historial", hist), ("trazabilidad", tz)):
        guardar(os.path.join(a.salida_dir, nombre + ".json"), filas)
    from collections import Counter
    print(json.dumps({
        "eventos": len(ev), "relaciones": len(rel), "analisis": len(an), "historial": len(hist), "trazabilidad": len(tz),
        "relaciones_por_estado": dict(Counter(x["estado_validacion"] for x in rel)),
        "relaciones_por_tipo": dict(Counter(x["tipo"] for x in rel).most_common(12)),
        "relaciones_con_destino_en_repositorio": sum(1 for x in rel if x["destino_id"]),
        "registros_por_estado": dict(Counter(x["estado_validacion"] for x in tz)),
        "registros_por_confiabilidad": dict(Counter(x["estado_confiabilidad"] for x in tz)),
        "errores": errores[:20], "n_errores": len(errores),
    }, ensure_ascii=False, indent=1))
    return 1 if errores else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    q = s.add_parser("procesar")
    q.add_argument("--novedades", required=True)
    q.add_argument("--anterior")
    for k in ("eventos", "relaciones", "analisis", "historial", "validaciones", "corpus"):
        q.add_argument("--" + k)
    q.add_argument("--fecha", required=True)
    q.add_argument("--corrida", default="")
    q.add_argument("--salida-dir", required=True)
    g = s.add_parser("agregar")
    g.add_argument("--tipo", required=True, choices=["relacion", "evento", "analisis"])
    g.add_argument("--base", required=True)
    g.add_argument("--nuevos", required=True)
    g.add_argument("--salida", required=True)
    v = s.add_parser("validar")
    v.add_argument("--tipo", required=True, choices=["relacion", "evento", "analisis"])
    v.add_argument("archivo")
    a = p.parse_args()
    if a.cmd == "procesar":
        sys.exit(procesar(a))
    if a.cmd == "validar":
        e = validar(a.tipo, cargar(a.archivo))
        print(f"{len(cargar(a.archivo))} filas · {len(e)} errores")
        print("\n".join(e[:50]))
        sys.exit(1 if e else 0)
    if a.cmd == "agregar":
        nuevos = cargar(a.nuevos)
        for x in nuevos:
            if not x.get("id"):
                base_id = x.get("origen_id") or x.get("doc_id")
                x["id"] = {"relacion": "rel-", "evento": "ev-", "analisis": "an-"}[a.tipo] + h(base_id, x.get("tipo") or x.get("tipo_evento"), x.get("destino_ref") or x.get("fecha") or x.get("valor"), x.get("parte", ""))
        e = validar(a.tipo, nuevos)
        if e:
            print("No se agregó nada:\n" + "\n".join(e[:50]))
            sys.exit(1)
        out = fusionar(cargar(a.base), nuevos)
        guardar(a.salida, out)
        print(f"{len(nuevos)} agregadas o actualizadas · {len(out)} en total")


if __name__ == "__main__":
    main()
