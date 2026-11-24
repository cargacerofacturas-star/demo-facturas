"""
Extracción y validación de facturas electrónicas argentinas.

Estrategia de doble fuente:
  1. QR de ARCA: datos fiscales firmados (CUIT, tipo, pto. vta., número,
     fecha, importe, CAE). Se decodifica desde la imagen del PDF.
  2. Texto del PDF: los mismos campos + detalle (ítems, neto, IVA, razón social).
Cada campo se cruza entre ambas fuentes y se aplican validaciones de negocio.
Resultado por comprobante: VERDE (ok), AMARILLO (revisar) o ROJO (error).
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import pdfplumber
import pymupdf

TIPO_A_LETRA = {1: "A", 6: "B", 11: "C", 51: "M"}
ALICUOTAS_IVA = (0.21, 0.105, 0.27, 0.05, 0.025)
TOLERANCIA = 1.0  # pesos


# ---------------------------------------------------------------- utilidades
def cuit_ok(cuit: str | None) -> bool:
    if not cuit or not re.fullmatch(r"\d{11}", cuit):
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * p for d, p in zip(cuit[:10], pesos))
    dv = 11 - (s % 11)
    dv = 0 if dv == 11 else (9 if dv == 10 else dv)
    return dv == int(cuit[10])


def num_ar(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def ars(x) -> str:
    if x is None:
        return "-"
    return "$ " + f"{float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def solo_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


# ---------------------------------------------------------------- modelos
@dataclass
class Check:
    regla: str
    resultado: str  # OK / ERROR / ALERTA
    detalle: str = ""


@dataclass
class Comprobante:
    archivo: str
    letra: str | None = None
    tipo_cmp: int | None = None
    pto_vta: int | None = None
    numero: int | None = None
    fecha: date | None = None
    emisor_cuit: str | None = None
    emisor_razon_social: str | None = None
    emisor_condicion_iva: str | None = None
    receptor_cuit: str | None = None
    receptor_razon_social: str | None = None
    neto: float | None = None
    iva: float | None = None
    otros_tributos: float | None = None
    total: float | None = None
    cae: str | None = None
    vto_cae: date | None = None
    qr_presente: bool = False
    items: list[dict] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    estado: str = "VERDE"
    confianza: str = "ALTA"

    def errores(self):
        return [c for c in self.checks if c.resultado == "ERROR"]

    def alertas(self):
        return [c for c in self.checks if c.resultado == "ALERTA"]

    def observaciones(self) -> str:
        return " | ".join(c.detalle for c in self.checks if c.resultado != "OK")


# ---------------------------------------------------------------- QR
def leer_qr(pdf_path: Path) -> dict | None:
    """Renderiza cada página y busca el QR de ARCA. Devuelve el JSON decodificado."""
    det = cv2.QRCodeDetector()
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            for zoom in (2, 3, 4):
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
                ok, textos, _, _ = det.detectAndDecodeMulti(img)
                for t in (textos if ok else []):
                    datos = decodificar_url_qr(t)
                    if datos:
                        return datos
    return None


def decodificar_url_qr(url: str) -> dict | None:
    if not url or "afip.gob.ar/fe/qr" not in url and "arca.gob.ar/fe/qr" not in url:
        return None
    p = parse_qs(urlparse(url).query).get("p", [None])[0]
    if not p:
        return None
    p += "=" * (-len(p) % 4)
    try:
        return json.loads(base64.b64decode(p).decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- texto
def leer_texto(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        partes = []
        for page in pdf.pages:
            # descarta texto rotado (marcas de agua, sellos)
            limpio = page.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
            partes.append(limpio.extract_text() or "")
    return "\n".join(partes)


RX_CUIT = r"(\d{2}-?\d{8}-?\d)"
RX_MONTO = r"\$?\s*([\d\.]+,\d{2})"


def parsear_texto(texto: str, comp: Comprobante):
    def buscar(patron, flags=re.I):
        m = re.search(patron, texto, flags)
        return m.group(1).strip() if m else None

    m = re.search(r"\b([ABCM])\s+FACTURA|FACTURA\s+([ABCM])\b|COD\.\s*(\d{2})", texto)
    letra = None
    if m:
        letra = m.group(1) or m.group(2)
        if not letra and m.group(3):
            letra = TIPO_A_LETRA.get(int(m.group(3)))
    cod = buscar(r"COD\.\s*(\d{2})")
    comp.letra = letra
    comp.tipo_cmp = int(cod) if cod else None

    pv = buscar(r"Punto de Venta:\s*(\d+)")
    nro = buscar(r"Comp\.\s*Nro:?\s*(\d+)")
    comp.pto_vta = int(pv) if pv else None
    comp.numero = int(nro) if nro else None

    f = buscar(r"Fecha de Emisi[oó]n:\s*(\d{2}/\d{2}/\d{4})")
    comp.fecha = datetime.strptime(f, "%d/%m/%Y").date() if f else None
    v = buscar(r"Vto\.? de CAE:\s*(\d{2}/\d{2}/\d{4})")
    comp.vto_cae = datetime.strptime(v, "%d/%m/%Y").date() if v else None
    comp.cae = buscar(r"CAE\s*N[°º]?:?\s*(\d{14})")

    # CUITs: el del receptor va junto a "Apellido y Nombre / Razón Social"
    rec = re.search(r"CUIT:\s*" + RX_CUIT + r"\s+Apellido y Nombre\s*/\s*Raz[oó]n Social:\s*(.+)", texto)
    if rec:
        comp.receptor_cuit = solo_digitos(rec.group(1))
        comp.receptor_razon_social = rec.group(2).strip()
    todos = [solo_digitos(c) for c in re.findall(r"CUIT:\s*" + RX_CUIT, texto)]
    emisores = [c for c in todos if c != comp.receptor_cuit]
    comp.emisor_cuit = emisores[0] if emisores else None

    comp.emisor_razon_social = buscar(r"Raz[oó]n Social:\s*(.+?)(?:\s+Punto de Venta|$)", re.I | re.M)
    comp.emisor_condicion_iva = buscar(r"Condici[oó]n frente al IVA:\s*(.+?)(?:\s+CUIT:|$)", re.I | re.M)

    comp.neto = _monto(texto, r"(?:Importe Neto Gravado|Subtotal):\s*" + RX_MONTO)
    comp.iva = _monto(texto, r"IVA\s*[\d,\.]+%:\s*" + RX_MONTO)
    comp.otros_tributos = _monto(texto, r"Importe Otros Tributos:\s*" + RX_MONTO)
    comp.total = _monto(texto, r"Importe Total:\s*" + RX_MONTO)

    # Ítems: código, descripción, cantidad, precio unitario, subtotal
    for m in re.finditer(r"^(\d{3})\s+(.+?)\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})\s+([\d\.]+,\d{2})$",
                         texto, re.M):
        comp.items.append(dict(codigo=m.group(1), descripcion=m.group(2),
                               cantidad=num_ar(m.group(3)), precio_unitario=num_ar(m.group(4)),
                               subtotal=num_ar(m.group(5))))


def _monto(texto, patron):
    m = re.search(patron, texto, re.I)
    return num_ar(m.group(1)) if m else None


# ---------------------------------------------------------------- validación
def validar(comp: Comprobante, qr: dict | None):
    ch = comp.checks.append

    # --- cruce con QR
    if qr is None:
        ch(Check("QR ARCA", "ALERTA", "Sin QR legible: datos solo desde texto, requiere revisión manual"))
        comp.confianza = "MEDIA"
    else:
        comp.qr_presente = True
        ch(Check("QR ARCA", "OK", "QR decodificado"))
        cruces = [
            ("CUIT emisor", comp.emisor_cuit, str(qr.get("cuit"))),
            ("CUIT receptor", comp.receptor_cuit, str(qr.get("nroDocRec"))),
            ("Tipo de comprobante", comp.tipo_cmp, qr.get("tipoCmp")),
            ("Punto de venta", comp.pto_vta, qr.get("ptoVta")),
            ("Número", comp.numero, qr.get("nroCmp")),
            ("Fecha", comp.fecha.isoformat() if comp.fecha else None, qr.get("fecha")),
            ("CAE", comp.cae, str(qr.get("codAut"))),
        ]
        for nombre, txt, q in cruces:
            if txt == q:
                ch(Check(f"{nombre} texto = QR", "OK"))
            else:
                ch(Check(f"{nombre} texto = QR", "ERROR", f"{nombre}: PDF dice {txt}, QR dice {q}"))
        q_imp = qr.get("importe")
        if comp.total is not None and q_imp is not None and abs(comp.total - float(q_imp)) <= TOLERANCIA:
            ch(Check("Total texto = QR", "OK"))
        else:
            ch(Check("Total texto = QR", "ERROR",
                     f"Total impreso {ars(comp.total)} vs QR {ars(float(q_imp or 0))}"))
        # Si falta algún dato del texto, lo completa el QR (fuente fiscal)
        comp.emisor_cuit = comp.emisor_cuit or str(qr.get("cuit"))
        comp.cae = comp.cae or str(qr.get("codAut"))

    # --- campos obligatorios
    faltan = [n for n, v in [("tipo", comp.letra), ("pto. vta.", comp.pto_vta), ("número", comp.numero),
                             ("fecha", comp.fecha), ("CUIT emisor", comp.emisor_cuit),
                             ("total", comp.total), ("CAE", comp.cae)] if v in (None, "")]
    if faltan:
        ch(Check("Campos obligatorios", "ERROR", "No se pudo extraer: " + ", ".join(faltan)))
    else:
        ch(Check("Campos obligatorios", "OK"))

    # --- CUITs
    for rol, c in (("emisor", comp.emisor_cuit), ("receptor", comp.receptor_cuit)):
        if c is None:
            continue
        if cuit_ok(c):
            ch(Check(f"CUIT {rol} válido", "OK"))
        else:
            ch(Check(f"CUIT {rol} válido", "ERROR", f"CUIT {rol} {c} con dígito verificador inválido"))

    # --- aritmética
    if comp.items and comp.neto is not None:
        suma = round(sum(i["subtotal"] for i in comp.items), 2)
        if abs(suma - comp.neto) <= TOLERANCIA:
            ch(Check("Suma de ítems = neto", "OK"))
        else:
            ch(Check("Suma de ítems = neto", "ERROR", f"Ítems suman {ars(suma)} y el neto es {ars(comp.neto)}"))

    if comp.letra == "A":
        if comp.iva is None:
            ch(Check("IVA discriminado", "ERROR", "Factura A sin IVA discriminado"))
        elif comp.neto:
            if any(abs(comp.neto * a - comp.iva) <= TOLERANCIA for a in ALICUOTAS_IVA):
                ch(Check("IVA = alícuota × neto", "OK"))
            else:
                ch(Check("IVA = alícuota × neto", "ERROR",
                         f"IVA {ars(comp.iva)} no corresponde a ninguna alícuota sobre neto {ars(comp.neto)}"))
    elif comp.letra in ("B", "C") and comp.iva:
        ch(Check("IVA no discriminado", "ALERTA", f"Factura {comp.letra} con IVA discriminado"))

    if None not in (comp.neto, comp.total):
        esperado = round(comp.neto + (comp.iva or 0) + (comp.otros_tributos or 0), 2)
        if abs(esperado - comp.total) <= TOLERANCIA:
            ch(Check("Neto + IVA + tributos = total", "OK"))
        else:
            ch(Check("Neto + IVA + tributos = total", "ERROR",
                     f"Componentes suman {ars(esperado)} y el total impreso es {ars(comp.total)}"))

    # --- fechas / CAE
    if comp.fecha and comp.vto_cae:
        if comp.vto_cae >= comp.fecha:
            ch(Check("Vto. CAE ≥ fecha emisión", "OK"))
        else:
            ch(Check("Vto. CAE ≥ fecha emisión", "ERROR",
                     f"Vto. CAE {comp.vto_cae:%d/%m/%Y} anterior a la emisión {comp.fecha:%d/%m/%Y}"))
    if comp.cae and not re.fullmatch(r"\d{14}", comp.cae):
        ch(Check("Formato CAE", "ERROR", "El CAE debe tener 14 dígitos"))

    # --- coherencia letra / condición IVA del emisor
    cond = (comp.emisor_condicion_iva or "").lower()
    if comp.letra == "C" and "inscripto" in cond:
        ch(Check("Letra vs condición IVA", "ALERTA", "Factura C emitida por Responsable Inscripto"))
    if comp.letra == "A" and "monotributo" in cond:
        ch(Check("Letra vs condición IVA", "ERROR", "Monotributista no puede emitir Factura A"))

    # --- estado final
    if comp.errores():
        comp.estado = "ROJO"
    elif comp.alertas():
        comp.estado = "AMARILLO"
    else:
        comp.estado = "VERDE"


# ---------------------------------------------------------------- API pública
def procesar_pdf(pdf_path: str | Path) -> Comprobante:
    pdf_path = Path(pdf_path)
    comp = Comprobante(archivo=pdf_path.name)
    try:
        parsear_texto(leer_texto(pdf_path), comp)
        qr = leer_qr(pdf_path)
    except Exception as e:  # PDF dañado, protegido, etc.
        comp.checks.append(Check("Lectura del PDF", "ERROR", f"No se pudo leer: {e}"))
        comp.estado, comp.confianza = "ROJO", "BAJA"
        return comp
    validar(comp, qr)
    return comp


def procesar_lote(paths) -> list[Comprobante]:
    comps = [procesar_pdf(p) for p in paths]
    # duplicados dentro del lote
    vistos = {}
    for c in comps:
        clave = (c.emisor_cuit, c.tipo_cmp, c.pto_vta, c.numero)
        if None in clave:
            continue
        if clave in vistos:
            c.checks.append(Check("Duplicado", "ERROR", f"Mismo comprobante que {vistos[clave]}"))
            c.estado = "ROJO"
        else:
            vistos[clave] = c.archivo
    return comps


if __name__ == "__main__":
    import sys
    for c in procesar_lote(sorted(Path(sys.argv[1]).glob("*.pdf"))):
        print(f"{c.estado:9} {c.archivo:45} total={c.total} | {c.observaciones()}")
