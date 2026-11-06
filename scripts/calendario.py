#!/usr/bin/env python3
"""Genera los periodos ORDINARIOS de sesiones de las corporaciones que sigue el monitor.

Uso:
  python3 calendario.py --anio 2026 > calendario_base.json

Reglas (verificadas el 13-oct-2026; ver references/corporaciones.md):
  Congreso      C.P. art. 138 (mod. A.L. 02 de 2023): 20 jul–16 dic y 16 feb–20 jun;
                en año de elecciones de Congreso el segundo periodo va del 16 mar al 20 jun.
  Asambleas     Ley 2200 de 2022 art. 23: 1er año 1 ene–último día de feb; años 2 a 4
                1 mar–30 abr; todos los años 1 jun–30 jul y 1 oct–30 nov.
  Concejos a)   Ley 136 de 1994 art. 23 lit. a (categorías especial, 1.ª y 2.ª): 1er año
                2 ene–último día de feb; luego 1 mar–30 abr; 1 jun–31 jul; 1 oct–30 nov.
  Concejos b)   Ley 136 art. 23 (categorías 3.ª a 6.ª): febrero, mayo, agosto y noviembre.
  Bogotá        Decreto Ley 1421 de 1993 art. 10: desde el 1 de feb, may, ago y nov,
                30 días prorrogables hasta 10 más.

Las extraordinarias NO se generan: solo se registran cuando hay convocatoria localizada.
Periodo constitucional de las corporaciones territoriales: 2024-2027, 2028-2031, ...
"""
import argparse
import calendar
import json
from datetime import date, timedelta

URL_LEY2200 = "https://www.cancilleria.gov.co/normograma/compilacion/docs/ley_2200_2022.htm"
URL_LEY136 = "https://normativa.colpensiones.gov.co/colpens/docs/ley_0136_1994.htm"
URL_DL1421 = "https://normas.cra.gov.co/gestor/docs/decreto_1421_1993.htm"
# Texto del Acto Legislativo 02 de 2023 (copia del texto oficial alojada por Ámbito Jurídico).
URL_CP = "https://ambitojuridico.com/sites/default/files/2023-07/AL-02-23%20%28PERIODO-LEGISLATIVO%29.pdf"
VERIF_CP = "V1 Texto oficial leído"

# Categoría asumida de cada concejo. Cambiar aquí si el decreto de categorización dice otra cosa.
CONCEJOS = [
    ("Concejo de Medellín", "Medellín", "a", "Distrito Especial; categoría especial."),
    ("Concejo de Envigado", "Envigado", "a",
     "Se asume categoría 1.ª o superior (literal a). Confirmar con el decreto de categorización vigente."),
    ("Concejo de Quibdó", "Quibdó", "b",
     "Se asume categoría 3.ª a 6.ª (regla de cuatro meses). Confirmar con el decreto de categorización vigente."),
]
ASAMBLEAS = [("Asamblea de Antioquia", "Antioquia"), ("Asamblea del Chocó", "Chocó")]


def ultimo_dia(anio, mes):
    return date(anio, mes, calendar.monthrange(anio, mes)[1])


def fila(corp, terr, ini, fin, base, nota, verif, url):
    return {
        "id": f"cal-{corp.lower().replace(' ', '-')}-{ini.isoformat()}",
        "corporacion": corp, "territorio": terr, "tipo_sesion": "Ordinaria",
        "inicio": ini.isoformat(), "fin": fin.isoformat(), "base_legal": base,
        "nota": nota, "verificacion": verif, "url": url,
    }


def generar(anio):
    filas = []
    primer_anio = (anio - 2024) % 4 == 0
    # Congreso (C.P. art. 138, modificado por el Acto Legislativo 02 de 2023)
    eleccion_congreso = (anio - 2026) % 4 == 0  # elecciones de Congreso: 2026, 2030, ...
    base_cp = "C.P. art. 138 (mod. Acto Legislativo 02 de 2023)"
    if eleccion_congreso:
        filas.append(fila("Congreso de la República", "Colombia", date(anio, 3, 16), date(anio, 6, 20), base_cp,
                          "Año de elecciones de Congreso: el segundo periodo inicia el 16 de marzo.",
                          VERIF_CP, URL_CP))
    else:
        filas.append(fila("Congreso de la República", "Colombia", date(anio, 2, 16), date(anio, 6, 20), base_cp,
                          "Entre el 16 de febrero y el 15 de marzo no se tramitan leyes estatutarias ni reformas constitucionales.",
                          VERIF_CP, URL_CP))
    filas.append(fila("Congreso de la República", "Colombia", date(anio, 7, 20), date(anio, 12, 16), base_cp,
                      "Primer periodo de la legislatura. Extraordinarias solo por convocatoria del Gobierno.",
                      VERIF_CP, URL_CP))
    # Asambleas
    for corp, terr in ASAMBLEAS:
        if primer_anio:
            filas.append(fila(corp, terr, date(anio, 1, 1), ultimo_dia(anio, 2), "Ley 2200 de 2022, art. 23",
                              "Primer año del periodo constitucional.", "V1 Texto oficial leído", URL_LEY2200))
        else:
            filas.append(fila(corp, terr, date(anio, 3, 1), date(anio, 4, 30), "Ley 2200 de 2022, art. 23",
                              "", "V1 Texto oficial leído", URL_LEY2200))
        filas.append(fila(corp, terr, date(anio, 6, 1), date(anio, 7, 30), "Ley 2200 de 2022, art. 23",
                          "", "V1 Texto oficial leído", URL_LEY2200))
        filas.append(fila(corp, terr, date(anio, 10, 1), date(anio, 11, 30), "Ley 2200 de 2022, art. 23",
                          "Además, hasta tres meses de extraordinarias por convocatoria del gobernador.",
                          "V1 Texto oficial leído", URL_LEY2200))
    # Concejos (Ley 136)
    for corp, terr, lit, nota in CONCEJOS:
        base = f"Ley 136 de 1994, art. 23 lit. {'a' if lit == 'a' else 'b'}"
        if lit == "a":
            if primer_anio:
                filas.append(fila(corp, terr, date(anio, 1, 2), ultimo_dia(anio, 2), base, nota,
                                  "V1 Texto oficial leído", URL_LEY136))
            else:
                n = nota + (" El texto legal dice 'segundo y tercer año' (periodo trienal original);"
                            " en el cuarto año se aplica igual, pero conviene verificarlo." if (anio - 2024) % 4 == 3 else "")
                filas.append(fila(corp, terr, date(anio, 3, 1), date(anio, 4, 30), base, n.strip(),
                                  "V1 Texto oficial leído", URL_LEY136))
            filas.append(fila(corp, terr, date(anio, 6, 1), ultimo_dia(anio, 7), base, nota,
                              "V1 Texto oficial leído", URL_LEY136))
            filas.append(fila(corp, terr, date(anio, 10, 1), date(anio, 11, 30), base,
                              (nota + " Prioridad: presupuesto municipal.").strip(), "V1 Texto oficial leído", URL_LEY136))
        else:
            for mes in (2, 5, 8, 11):
                filas.append(fila(corp, terr, date(anio, mes, 1), ultimo_dia(anio, mes), base, nota,
                                  "V1 Texto oficial leído", URL_LEY136))
    # Bogotá
    for mes in (2, 5, 8, 11):
        ini = date(anio, mes, 1)
        filas.append(fila("Concejo de Bogotá", "Bogotá", ini, ini + timedelta(days=29),
                          "Decreto Ley 1421 de 1993, art. 10",
                          "30 días prorrogables hasta 10 más. La página consultada remite a notas del editor no leídas.",
                          "V1 Texto oficial leído", URL_DL1421))
    return sorted(filas, key=lambda f: (f["inicio"], f["corporacion"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--anio", type=int, default=date.today().year)
    a = p.parse_args()
    print(json.dumps(generar(a.anio), ensure_ascii=False, indent=1))
