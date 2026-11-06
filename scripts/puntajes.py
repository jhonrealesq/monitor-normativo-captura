#!/usr/bin/env python3
"""Puntajes automáticos de los proyectos dap, qbd, med, gpp y ot (reglas de references/relevancia.md).

Uso:
  python3 puntajes.py nuevos.json --salida nuevos.json            # solo capturados hoy
  python3 puntajes.py novedades.json --salida novedades.json --desde 2026-10-13
  python3 puntajes.py novedades.json --salida novedades.json --todos

No toca pm, cdae ni pi (se califican a mano). Después de correrlo, revisa a mano los registros
de relevancia alta: la regla es un punto de partida.
"""
import argparse, json, re
from datetime import date

URB = {"Derecho urbanístico", "Ordenamiento territorial"}
ADM = {"Derecho administrativo", "Empleo público", "Contratación estatal", "Derecho disciplinario", "Derecho procesal"}
SISMO = re.compile(r"sismo|desastre|emergencia|1261|1171|terremoto", re.I)

def reglas(r):
    A = {a.strip() for a in r["areas"].split(";") if a.strip()}
    alta = r["relevancia"] == "Alta"; nac = r["nivel"] == "Nacional"; t = r["territorio"]
    juris = r["categoria"] == "Jurisprudencia"
    txt = " ".join([r["titulo"], r["resumen"], r["nota"]])
    # DAP Envigado
    if t == "Envigado": dap = 3 if A & (URB | {"Hacienda pública", "Derecho administrativo", "Empleo público", "Servicios públicos", "Ambiental", "Educación", "Contratación estatal"}) else 2
    elif A & URB: dap = 3 if (nac and alta) else 2
    elif A & {"Servicios públicos", "Gestión del riesgo"}: dap = 2 if alta else 1
    elif A & ADM: dap = 2 if (alta and nac) else 1
    else: dap = 0
    # Centro Quibdoseños
    if t in ("Quibdó", "Chocó"): qbd = 3
    elif SISMO.search(txt) and nac: qbd = 3
    elif "Gestión del riesgo" in A: qbd = 2
    elif "Servicios públicos" in A: qbd = 2
    elif nac and A & {"Gobierno y políticas públicas", "Educación", "Salud"}: qbd = 1
    else: qbd = 0
    # Centro Medellinenses
    if t == "Medellín" and not juris: med = 3 if r["relevancia"] in ("Alta", "Media") else 1
    elif t == "Medellín": med = 0
    elif t == "Antioquia" and not juris: med = 1
    elif nac and A & (URB | {"Movilidad"}): med = 2 if alta else 1
    else: med = 0
    # Gobierno y Políticas Públicas
    if "Gobierno y políticas públicas" in A: gpp = 3 if alta else 2
    elif "Hacienda pública" in A: gpp = 2 if r["relevancia"] in ("Alta", "Media") else 1
    elif juris and alta and "Derecho constitucional" in A: gpp = 2
    elif A & {"Educación", "Salud"}: gpp = 1
    else: gpp = 0
    # Ordenamiento Territorial
    if "Ordenamiento territorial" in A: ot = 3
    elif A & {"Derecho urbanístico", "Gestión del riesgo"}: ot = 3 if alta else 2
    elif A & {"Ambiental", "Servicios públicos", "Movilidad"}: ot = 2 if alta else 1
    else: ot = 0
    return dict(dap=dap, qbd=qbd, med=med, gpp=gpp, ot=ot)



def main():
    p = argparse.ArgumentParser()
    p.add_argument("archivo"); p.add_argument("--salida", required=True)
    p.add_argument("--desde", default=date.today().isoformat()); p.add_argument("--todos", action="store_true")
    a = p.parse_args()
    datos = json.load(open(a.archivo, encoding="utf-8"))
    n = 0
    for r in datos:
        if a.todos or r.get("fecha_captura", "") >= a.desde:
            for k in ("titulo", "resumen", "nota", "areas", "relevancia", "nivel", "territorio", "categoria"):
                r.setdefault(k, "")
            r.update(reglas(r)); n += 1
    json.dump(datos, open(a.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{n} registros calificados de {len(datos)}")


if __name__ == "__main__":
    main()
