#!/usr/bin/env python3
"""Captura del documento oficial original (v1.11) — corre donde haya salida a internet.

Para cada pendiente {doc_id, url}: descarga el archivo tal como lo publica la fuente oficial, lo conserva con su
sha256, extrae el texto (PDF con `pdftotext -layout` si está instalado; HTML con el analizador de la biblioteca
estándar) y lo segmenta en artículos con `textos.py`. Escribe un manifiesto con lo que pasó en cada documento,
incluidos los fallos: nada se marca como capturado si no se descargó.

Por qué existe: la sesión de Claude y la tarea programada no pueden descargar archivos de sitios .gov.co (el shell no
tiene salida y la lectura web devuelve citas de máximo 125 caracteres). Este script está pensado para GitHub Actions
(`.github/workflows/captura.yml`) o para el computador del usuario.

Uso:
  python3 captura.py --pendientes pendientes.json --dir capturas/ [--fecha 2026-11-05] [--max 20]
  pendientes.json = [{"doc_id": "...", "url": "https://..."}]
Salida en capturas/: originales/<sha256>.<ext>, textos/<doc_id>.txt, por_doc/<doc_id>/{textos,relaciones,analisis}.json,
manifiesto.json (acumulado).
"""
import argparse
import datetime
import hashlib
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
import urllib.robotparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import textos  # noqa: E402

AGENTE = "MonitorNormativo/1.11 (captura de documentos oficiales; uso jurídico no comercial)"
DOMINIOS_OFICIALES = re.compile(r"(\.gov\.co|\.gob\.co|\.edu\.co|secretariasenado\.gov\.co|camara\.gov\.co|senado\.gov\.co|ramajudicial\.gov\.co)$", re.I)


class _Texto(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.partes, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1
        if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self._skip:
            self._skip -= 1

    def handle_data(self, d):
        if not self._skip:
            self.partes.append(d)


def texto_html(b, charset):
    for enc in ([charset] if charset else []) + ["utf-8", "latin-1"]:
        try:
            s = b.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    p = _Texto()
    p.feed(s)
    return re.sub(r"\n\s*\n+", "\n\n", "".join(p.partes))


def texto_pdf(ruta):
    if not shutil.which("pdftotext"):
        return None, "pdftotext no está instalado"
    r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", ruta, "-"], capture_output=True, timeout=120)
    t = r.stdout.decode("utf-8", "replace")
    if len(re.sub(r"\s", "", t)) < 200:
        return t, "PDF sin capa de texto suficiente (posible escaneo): requiere OCR"
    return t, ""


_ROBOTS = {}


def permitido(url):
    """Respeta robots.txt: si el sitio lo prohíbe para este agente, no se descarga. Si robots.txt no se puede leer,
    se registra y se permite (comportamiento estándar de urllib.robotparser cuando el archivo no existe)."""
    pr = urllib.parse.urlparse(url)
    base = f"{pr.scheme}://{pr.netloc}"
    if base not in _ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(req, timeout=20) as resp:
                rp.parse(resp.read().decode("utf-8", "replace").splitlines())
            _ROBOTS[base] = (rp, "")
        except urllib.error.HTTPError as e:
            rp.parse([]) if e.code in (404, 410) else rp.parse(["User-agent: *", "Disallow: /"])
            _ROBOTS[base] = (rp, "" if e.code in (404, 410) else f"robots.txt respondió {e.code}: se trata como prohibido")
        except Exception as e:  # sin respuesta: no se fuerza
            rp.parse(["User-agent: *", "Disallow: /"])
            _ROBOTS[base] = (rp, f"robots.txt sin respuesta ({type(e).__name__}): no se fuerza el sitio")
    rp, nota = _ROBOTS[base]
    return rp.can_fetch(AGENTE, url), nota


BLOQUEO_RE = re.compile(rb"<title>[^<]*(bot manager|captcha|access denied|acceso denegado|attention required|just a moment|"
                        rb"request rejected|are you a robot|security check)[^<]*</title>", re.I)


def pagina_de_bloqueo(b, ct, url):
    """Detecta páginas de protección anti-bots o de desafío que el sitio entrega en lugar del documento. No se
    intenta eludirlas: se registra el bloqueo y el documento queda pendiente para consulta manual."""
    cabeza = b[:4096]
    m = BLOQUEO_RE.search(cabeza)
    if m:
        return f"el sitio entregó una página de protección («{m.group(1).decode('latin-1')}») en lugar del documento; no se elude"
    if urllib.parse.urlparse(url).path.lower().endswith(".pdf") and b[:5] != b"%PDF-" and "pdf" not in ct.lower():
        return "se pidió un PDF y el sitio devolvió otro contenido; no se conserva como original"
    return ""


def capturar(p, base, fecha):
    fila = {"doc_id": p["doc_id"], "url": p["url"], "fecha_captura": fecha, "estado": "", "sha256": "", "bytes": 0,
            "content_type": "", "archivo": "", "texto": "", "metodo_extraccion": "", "unidades": 0, "nota": ""}
    host = urllib.parse.urlparse(p["url"]).hostname or ""
    if not DOMINIOS_OFICIALES.search(host):
        fila.update(estado="omitido", nota=f"{host} no es un dominio oficial: no se conserva como original")
        return fila
    ok, nota_r = permitido(p["url"])
    if not ok:
        fila.update(estado="bloqueado por robots.txt", nota=nota_r or f"robots.txt de {host} no permite la descarga automática")
        return fila
    try:
        req = urllib.request.Request(p["url"], headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(req, timeout=60) as resp:
            b = resp.read()
            ct = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset()
    except Exception as e:  # el fallo se registra, no se oculta
        fila.update(estado="fallido", nota=f"{type(e).__name__}: {e}"[:300])
        return fila
    bloqueo = pagina_de_bloqueo(b, ct, p["url"])
    if bloqueo:  # no se guarda como original: no es el documento oficial
        fila.update(estado="bloqueado por protección anti-bots", bytes=len(b), content_type=ct, nota=bloqueo)
        return fila
    sha = hashlib.sha256(b).hexdigest()
    es_pdf = b[:5] == b"%PDF-" or "pdf" in ct.lower()
    ext = "pdf" if es_pdf else "html"
    os.makedirs(os.path.join(base, "originales"), exist_ok=True)
    ruta = os.path.join(base, "originales", f"{sha}.{ext}")
    if not os.path.exists(ruta):
        open(ruta, "wb").write(b)
    fila.update(sha256=sha, bytes=len(b), content_type=ct, archivo=os.path.relpath(ruta, base))
    if es_pdf:
        t, aviso = texto_pdf(ruta)
        fila["metodo_extraccion"] = "pdftotext -layout"
    else:
        t, aviso = texto_html(b, charset), ""
        fila["metodo_extraccion"] = "html.parser"
    if not t:
        fila.update(estado="original sin texto", nota=aviso)
        return fila
    os.makedirs(os.path.join(base, "textos"), exist_ok=True)
    rt = os.path.join(base, "textos", f"{p['doc_id']}.txt")
    open(rt, "w", encoding="utf-8").write(t)
    filas, rel, an = textos.procesar(p["doc_id"], t, p["url"], sha, fecha)
    d = os.path.join(base, "por_doc", p["doc_id"])
    os.makedirs(d, exist_ok=True)
    for n, x in (("textos", filas), ("relaciones", rel), ("analisis", an)):
        json.dump(x, open(os.path.join(d, f"{n}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fila.update(estado="capturado" if not aviso else "capturado con aviso", texto=os.path.relpath(rt, base), unidades=len(filas), nota=aviso)
    return fila


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--pendientes", required=True)
    a.add_argument("--dir", required=True)
    a.add_argument("--fecha", default=datetime.date.today().isoformat())
    a.add_argument("--max", type=int, default=20)
    x = a.parse_args()
    os.makedirs(x.dir, exist_ok=True)
    man_p = os.path.join(x.dir, "manifiesto.json")
    manif = json.load(open(man_p, encoding="utf-8")) if os.path.exists(man_p) else []
    hechos = {(m["doc_id"], m["sha256"]) for m in manif if m.get("sha256")}
    pend = json.load(open(x.pendientes, encoding="utf-8"))[: x.max]
    nuevas = []
    for p in pend:
        f = capturar(p, x.dir, x.fecha)
        if f.get("sha256") and (f["doc_id"], f["sha256"]) in hechos:
            f["nota"] = (f["nota"] + " | sin cambios desde la captura anterior").strip(" |")
        nuevas.append(f)
        print(f"{f['estado']:20} {f['doc_id'][:50]} {f['sha256'][:12]} {f['nota'][:80]}")
    json.dump(manif + nuevas, open(man_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
