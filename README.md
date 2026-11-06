# Monitor Normativo — captura de documentos oficiales

Descarga el documento oficial de cada registro pendiente (respetando robots.txt), guarda su sha256, extrae el texto y
lo segmenta por artículos. La corrida del Monitor Normativo escribe `pendientes.json` y lee `capturas/`.

- `.github/workflows/captura.yml`: corre con cada cambio de `pendientes.json`, a las 5:20 a. m. y 5:20 p. m. (Bogotá) y a demanda.
- `scripts/`: los mismos scripts del proyecto Monitor Normativo (v1.11).
- `tests/`: pruebas que corren antes de cada captura.

Nada se marca capturado si no se descargó. Los textos son normas y providencias oficiales públicas.
