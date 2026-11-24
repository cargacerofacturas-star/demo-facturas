# CargaCero · Facturas electrónicas → Excel validado

Demo que procesa facturas electrónicas argentinas (A, B y C) en PDF y devuelve un Excel listo para cargar, con semáforo por comprobante:

- 🟢 **VERDE**: todos los datos coinciden y pasan las validaciones
- 🟡 **AMARILLO**: se puede cargar, pero conviene revisarlo (por ejemplo, no tiene QR legible)
- 🔴 **ROJO**: tiene inconsistencias que hay que corregir antes de cargarlo

## Cómo funciona

1. **Doble fuente de datos.** Se lee el texto del PDF y, además, se decodifica el **QR de ARCA**, que trae los datos fiscales del comprobante (CUIT, tipo, punto de venta, número, fecha, importe y CAE).
2. **Cruce de campos.** Cada dato del texto se compara contra el QR. Si el PDF dice una cosa y el QR otra, se marca.
3. **Validaciones de negocio:**
   - dígito verificador de los CUIT de emisor y receptor
   - suma de los ítems = neto
   - IVA = alícuota (21 %, 10,5 %, 27 %, etc.) × neto, en las Factura A
   - neto + IVA + otros tributos = total
   - vencimiento del CAE posterior a la fecha de emisión
   - coherencia entre la letra y la condición frente al IVA del emisor
   - comprobantes duplicados dentro del lote
4. **Salida en Excel** con cuatro hojas: Comprobantes, Validaciones, Ítems y Resumen.

## Cómo correrla

```bash
pip install -r requirements.txt
python generar_muestras.py muestras   # 8 facturas ficticias con distintos casos
streamlit run app.py
```

En la app podés subir tus propios PDFs o tocar **"Probar con 8 facturas de ejemplo"**.

Para usarla sin interfaz: `python extractor.py carpeta_con_pdfs`

### Publicarla gratis (para compartir el link en propuestas)

1. Subí esta carpeta a un repo público de GitHub (incluida `muestras/`).
2. Entrá a share.streamlit.io, elegí el repo y `app.py`.
3. Vas a tener una URL pública para poner en Fiverr, Upwork y LinkedIn.

## Facturas de ejemplo

Todas son **ficticias** (empresas, CUIT y CAE inventados) y llevan la marca "FICTICIO - DEMO".

| Archivo | Caso | Resultado esperado |
|---|---|---|
| 01_factura_A_ok | Factura A correcta | 🟢 |
| 02_factura_B_ok | Factura B correcta | 🟢 |
| 03_factura_C_ok | Factura C de monotributista | 🟢 |
| 04_factura_A_total_no_coincide | Total impreso distinto del QR | 🔴 |
| 05_factura_A_iva_mal_calculado | IVA que no corresponde a ninguna alícuota | 🔴 |
| 06_factura_A_cuit_emisor_invalido | CUIT con dígito verificador inválido y distinto del QR | 🔴 |
| 07_factura_A_vto_cae_inconsistente | Vencimiento del CAE anterior a la emisión | 🔴 |
| 08_factura_B_sin_qr | Sin QR: datos solo desde el texto | 🟡 |

## Limitaciones actuales y próximos pasos

- **Formato del PDF.** El parser de texto está pensado para el formato estándar de factura que genera ARCA. Las facturas emitidas por sistemas de gestión con diseño propio necesitan un paso extra. Para esos casos, el próximo módulo es un fallback con **Azure Document Intelligence** (modelo prebuilt-invoice o un modelo entrenado por cliente) o con un LLM. Ese fallback se activa solo cuando el parser no logra extraer los campos obligatorios.
- **PDFs escaneados.** Hoy el QR se lee igual desde una imagen, pero el texto requiere OCR. Lo resuelve el mismo fallback.
- **Constatación online.** Se puede agregar la verificación del CAE contra el web service de constatación de comprobantes de ARCA (WSCDC), que requiere certificado digital del cliente.
- **Integración.** El Excel puede reemplazarse por una carga directa al sistema contable, una base de datos o Google Sheets.
