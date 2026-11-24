"""
Genera facturas electrónicas argentinas FICTICIAS (con QR ARCA) para la demo.
Todas las empresas, CUITs y CAEs son inventados y cada PDF lleva la marca
"COMPROBANTE FICTICIO - DEMO".

Uso: python generar_muestras.py [carpeta_salida]
"""
import base64
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import qrcode
from reportlab.lib.colors import Color, black, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

TIPOS = {  # letra -> (código ARCA, discrimina IVA)
    "A": (1, True),
    "B": (6, False),
    "C": (11, False),
}


def cuit_valido(base10: str) -> str:
    """Completa un CUIT de 10 dígitos con su dígito verificador."""
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * p for d, p in zip(base10, pesos))
    dv = 11 - (s % 11)
    dv = 0 if dv == 11 else (9 if dv == 10 else dv)
    return base10 + str(dv)


def fmt_cuit(c: str) -> str:
    return f"{c[:2]}-{c[2:10]}-{c[10]}"


def fmt_ars(x: float) -> str:
    s = f"{x:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def qr_arca(datos: dict) -> ImageReader:
    payload = base64.b64encode(json.dumps(datos).encode()).decode()
    url = f"https://www.afip.gob.ar/fe/qr/?p={payload}"
    img = qrcode.make(url, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def generar(ruta: Path, f: dict):
    c = canvas.Canvas(str(ruta), pagesize=A4)
    W, H = A4
    cod, discrimina = TIPOS[f["letra"]]

    # Marca de agua
    c.saveState()
    c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.12))
    c.setFont("Helvetica-Bold", 54)
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "FICTICIO - DEMO")
    c.restoreState()

    # Encabezado
    c.setStrokeColor(black)
    c.rect(30, H - 175, W - 60, 145)
    c.line(W / 2, H - 175, W / 2, H - 80)
    c.rect(W / 2 - 25, H - 80, 50, 50, fill=0)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(W / 2, H - 65, f["letra"])
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, H - 76, f"COD. {cod:02d}")

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, H - 55, f["emisor_nombre"])
    c.setFont("Helvetica", 8)
    c.drawString(40, H - 100, f"Razón Social: {f['emisor_nombre']}")
    c.drawString(40, H - 112, f"Domicilio Comercial: {f['emisor_domicilio']}")
    c.drawString(40, H - 124, f"Condición frente al IVA: {f['emisor_iva']}")

    c.setFont("Helvetica-Bold", 16)
    c.drawString(W / 2 + 35, H - 55, "FACTURA")
    c.setFont("Helvetica", 9)
    c.drawString(W / 2 + 10, H - 100,
                 f"Punto de Venta: {f['pto_vta']:05d}   Comp. Nro: {f['nro']:08d}")
    c.drawString(W / 2 + 10, H - 113, f"Fecha de Emisión: {f['fecha'].strftime('%d/%m/%Y')}")
    c.drawString(W / 2 + 10, H - 126, f"CUIT: {fmt_cuit(f['emisor_cuit_impreso'])}")
    c.drawString(W / 2 + 10, H - 139, "Ingresos Brutos: Convenio Multilateral")
    c.drawString(W / 2 + 10, H - 152, "Fecha de Inicio de Actividades: 01/03/2015")

    # Receptor
    c.rect(30, H - 235, W - 60, 55)
    c.setFont("Helvetica", 9)
    c.drawString(40, H - 197, f"CUIT: {fmt_cuit(f['receptor_cuit'])}")
    c.drawString(220, H - 197, f"Apellido y Nombre / Razón Social: {f['receptor_nombre']}")
    c.drawString(40, H - 212, f"Condición frente al IVA: {f['receptor_iva']}")
    c.drawString(40, H - 227, "Condición de venta: Cuenta Corriente")

    # Ítems
    y = H - 265
    c.setFillColor(HexColor("#DDDDDD"))
    c.rect(30, y - 4, W - 60, 16, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(35, y, "Código")
    c.drawString(85, y, "Producto / Servicio")
    c.drawString(330, y, "Cantidad")
    c.drawString(390, y, "Precio Unit.")
    c.drawString(480, y, "Subtotal")
    c.setFont("Helvetica", 8)
    neto = 0.0
    for i, (desc, cant, pu) in enumerate(f["items"], 1):
        y -= 16
        sub = cant * pu
        neto += sub
        c.drawString(35, y, f"{i:03d}")
        c.drawString(85, y, desc)
        c.drawRightString(370, y, fmt_ars(cant))
        c.drawRightString(460, y, fmt_ars(pu))
        c.drawRightString(555, y, fmt_ars(sub))

    iva = round(neto * 0.21, 2) if discrimina else 0.0
    total_real = round(neto + iva, 2)
    total_impreso = f.get("total_impreso", total_real)
    iva_impreso = f.get("iva_impreso", iva)

    # Totales
    y = 230
    c.rect(330, y - 70, W - 360, 95)
    c.setFont("Helvetica-Bold", 9)
    if discrimina:
        c.drawString(340, y + 8, "Importe Neto Gravado: $")
        c.drawRightString(555, y + 8, fmt_ars(neto))
        c.drawString(340, y - 8, "IVA 21%: $")
        c.drawRightString(555, y - 8, fmt_ars(iva_impreso))
        c.drawString(340, y - 24, "Importe Otros Tributos: $")
        c.drawRightString(555, y - 24, fmt_ars(0))
    else:
        c.drawString(340, y + 8, "Subtotal: $")
        c.drawRightString(555, y + 8, fmt_ars(neto))
        c.drawString(340, y - 8, "Importe Otros Tributos: $")
        c.drawRightString(555, y - 8, fmt_ars(0))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(340, y - 50, "Importe Total: $")
    c.drawRightString(555, y - 50, fmt_ars(total_impreso))

    # CAE + QR
    c.setFont("Helvetica-Bold", 9)
    c.drawString(330, 110, f"CAE N°: {f['cae']}")
    c.drawString(330, 95, f"Fecha de Vto. de CAE: {f['vto_cae'].strftime('%d/%m/%Y')}")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(330, 75, "COMPROBANTE FICTICIO - DEMO. Datos inventados.")

    if f.get("con_qr", True):
        datos_qr = {
            "ver": 1,
            "fecha": f["fecha"].isoformat(),
            "cuit": int(f["emisor_cuit"]),
            "ptoVta": f["pto_vta"],
            "tipoCmp": cod,
            "nroCmp": f["nro"],
            "importe": f.get("total_qr", total_real),
            "moneda": "PES",
            "ctz": 1,
            "tipoDocRec": 80,
            "nroDocRec": int(f["receptor_cuit"]),
            "tipoCodAut": "E",
            "codAut": int(f["cae"]),
        }
        c.drawImage(qr_arca(datos_qr), 40, 40, width=120, height=120)

    c.showPage()
    c.save()


def muestras():
    hoy = date(2026, 11, 20)
    emisor1 = cuit_valido("3071234567")
    emisor2 = cuit_valido("3070998877")
    mono = cuit_valido("2033445566")
    cliente = cuit_valido("3071555444")
    base = dict(
        receptor_cuit=cliente, receptor_nombre="ESTUDIO CONTABLE EJEMPLO S.A.",
        receptor_iva="IVA Responsable Inscripto",
    )
    sa = dict(emisor_nombre="DISTRIBUIDORA DEMO S.R.L.", emisor_cuit=emisor1,
              emisor_cuit_impreso=emisor1, emisor_domicilio="Av. Ficticia 123 - Chivilcoy",
              emisor_iva="IVA Responsable Inscripto")
    lista = [
        ("01_factura_A_ok.pdf", dict(**base, **sa, letra="A", pto_vta=3, nro=1234,
            fecha=hoy, cae="76452198734512", vto_cae=hoy + timedelta(days=10),
            items=[("Resma papel A4 75g", 20, 8500), ("Tóner compatible", 3, 42000)])),
        ("02_factura_B_ok.pdf", dict(**base, emisor_nombre="SERVICIOS TECNICOS DEMO S.A.",
            emisor_cuit=emisor2, emisor_cuit_impreso=emisor2,
            emisor_domicilio="Calle Inventada 456 - Luján", emisor_iva="IVA Responsable Inscripto",
            letra="B", pto_vta=1, nro=567, fecha=hoy - timedelta(days=3), cae="76451122334455",
            vto_cae=hoy + timedelta(days=7), items=[("Mantenimiento mensual equipos", 1, 185000)])),
        ("03_factura_C_ok.pdf", dict(**base, emisor_nombre="PEREZ JUAN (DEMO)", emisor_cuit=mono,
            emisor_cuit_impreso=mono, emisor_domicilio="Pasaje Demo 78 - Mercedes",
            emisor_iva="Responsable Monotributo", letra="C", pto_vta=2, nro=89,
            fecha=hoy - timedelta(days=1), cae="76459988776655", vto_cae=hoy + timedelta(days=9),
            items=[("Diseño de logo", 1, 120000), ("Tarjetas personales", 500, 60)])),
        ("04_factura_A_total_no_coincide.pdf", dict(**base, **sa, letra="A", pto_vta=3, nro=1240,
            fecha=hoy, cae="76452198734599", vto_cae=hoy + timedelta(days=10),
            items=[("Silla de oficina", 4, 95000)], total_impreso=469800.00)),
        ("05_factura_A_iva_mal_calculado.pdf", dict(**base, **sa, letra="A", pto_vta=3, nro=1241,
            fecha=hoy, cae="76452198734600", vto_cae=hoy + timedelta(days=10),
            items=[("Monitor 24 pulgadas", 2, 210000)], iva_impreso=42000.00)),
        ("06_factura_A_cuit_emisor_invalido.pdf", dict(**base, **dict(sa, emisor_cuit_impreso="30712345670"
            if emisor1[-1] != "0" else "30712345671"), letra="A", pto_vta=3, nro=1242,
            fecha=hoy, cae="76452198734601", vto_cae=hoy + timedelta(days=10),
            items=[("Cable HDMI 2m", 10, 7500)])),
        ("07_factura_A_vto_cae_inconsistente.pdf", dict(**base, **sa, letra="A", pto_vta=3, nro=1243,
            fecha=hoy, cae="76450000111222", vto_cae=hoy - timedelta(days=5),
            items=[("Escritorio", 1, 230000)])),
        ("08_factura_B_sin_qr.pdf", dict(**base, emisor_nombre="SERVICIOS TECNICOS DEMO S.A.",
            emisor_cuit=emisor2, emisor_cuit_impreso=emisor2,
            emisor_domicilio="Calle Inventada 456 - Luján", emisor_iva="IVA Responsable Inscripto",
            letra="B", pto_vta=1, nro=570, fecha=hoy, cae="76451122334499",
            vto_cae=hoy + timedelta(days=10), items=[("Visita técnica", 2, 45000)], con_qr=False)),
    ]
    return lista


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "muestras")
    out.mkdir(parents=True, exist_ok=True)
    for nombre, datos in muestras():
        generar(out / nombre, datos)
        print("generado", out / nombre)
