"""Exporta los comprobantes procesados a un Excel con semáforo verde/amarillo/rojo."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLORES = {"VERDE": "C6EFCE", "AMARILLO": "FFEB9C", "ROJO": "FFC7CE",
           "OK": "C6EFCE", "ALERTA": "FFEB9C", "ERROR": "FFC7CE"}
HEADER = PatternFill("solid", fgColor="1F3864")
FMT_ARS = '"$" #,##0.00'


def _hoja(ws, encabezados, filas, col_estado=None, cols_monto=(), anchos=None):
    ws.append(encabezados)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for f in filas:
        ws.append(f)
    for row in ws.iter_rows(min_row=2):
        if col_estado is not None:
            est = row[col_estado].value
            if est in COLORES:
                row[col_estado].fill = PatternFill("solid", fgColor=COLORES[est])
                row[col_estado].font = Font(bold=True)
        for i in cols_monto:
            row[i].number_format = FMT_ARS
    for i, w in enumerate(anchos or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def a_excel(comps) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "Comprobantes"
    _hoja(ws,
          ["Estado", "Confianza", "Archivo", "Tipo", "Pto. Vta.", "Número", "Fecha", "CUIT emisor",
           "Razón social emisor", "CUIT receptor", "Neto / Subtotal", "IVA", "Total", "CAE",
           "Vto. CAE", "QR", "Observaciones"],
          [[c.estado, c.confianza, c.archivo, f"Factura {c.letra}" if c.letra else None, c.pto_vta,
            c.numero, c.fecha, c.emisor_cuit, c.emisor_razon_social, c.receptor_cuit, c.neto, c.iva,
            c.total, c.cae, c.vto_cae, "Sí" if c.qr_presente else "No", c.observaciones()]
           for c in comps],
          col_estado=0, cols_monto=(10, 11, 12),
          anchos=[11, 11, 38, 11, 9, 10, 12, 14, 32, 14, 16, 14, 16, 17, 12, 6, 80])
    for row in ws.iter_rows(min_row=2):
        for i in (6, 14):
            row[i].number_format = "DD/MM/YYYY"

    ws2 = wb.create_sheet("Validaciones")
    _hoja(ws2, ["Archivo", "Regla", "Resultado", "Detalle"],
          [[c.archivo, k.regla, k.resultado, k.detalle] for c in comps for k in c.checks],
          col_estado=2, anchos=[38, 32, 11, 90])

    ws3 = wb.create_sheet("Ítems")
    _hoja(ws3, ["Archivo", "CUIT emisor", "Código", "Descripción", "Cantidad", "Precio unitario", "Subtotal"],
          [[c.archivo, c.emisor_cuit, i["codigo"], i["descripcion"], i["cantidad"],
            i["precio_unitario"], i["subtotal"]] for c in comps for i in c.items],
          cols_monto=(5, 6), anchos=[38, 14, 8, 36, 10, 16, 16])

    ws4 = wb.create_sheet("Resumen")
    tot = len(comps)
    resumen = [[e, sum(c.estado == e for c in comps)] for e in ("VERDE", "AMARILLO", "ROJO")]
    _hoja(ws4, ["Estado", "Cantidad"], resumen + [["TOTAL", tot]], col_estado=0, anchos=[14, 12])
    ws4.append([])
    ws4.append(["Importe total procesado", sum(c.total or 0 for c in comps)])
    ws4.append(["Importe total en estado VERDE", sum(c.total or 0 for c in comps if c.estado == "VERDE")])
    for r in (ws4.max_row - 1, ws4.max_row):
        ws4.cell(r, 2).number_format = FMT_ARS
        ws4.cell(r, 1).font = Font(bold=True)
    ws4.column_dimensions["A"].width = 32
    ws4.column_dimensions["B"].width = 18

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
