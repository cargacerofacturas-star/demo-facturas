"""
Demo: Facturas ARCA -> Excel validado.
Ejecutar:  streamlit run app.py
"""
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from extractor import procesar_lote, ars
from exportar import a_excel

st.set_page_config(page_title="CargaCero · Demo", page_icon="✅", layout="wide")

EMOJI = {"VERDE": "🟢", "AMARILLO": "🟡", "ROJO": "🔴"}
MUESTRAS = Path(__file__).parent / "muestras"

st.title("CargaCero · Facturas electrónicas → Excel validado")
st.caption(
    "Subí facturas en PDF (A, B o C). Se extraen los datos del texto y del **QR de ARCA**, "
    "se cruzan entre sí y se aplican validaciones de negocio. Resultado: semáforo por comprobante "
    "y un Excel listo para cargar."
)

col1, col2 = st.columns([3, 1])
with col1:
    archivos = st.file_uploader("Facturas PDF", type="pdf", accept_multiple_files=True)
with col2:
    st.write("")
    st.write("")
    usar_muestras = st.button("Probar con 8 facturas de ejemplo", width="stretch",
                              disabled=not MUESTRAS.exists())

paths = []
if archivos:
    tmp = Path(tempfile.mkdtemp())
    for a in archivos:
        p = tmp / a.name
        p.write_bytes(a.getbuffer())
        paths.append(p)
elif usar_muestras or st.session_state.get("muestras"):
    st.session_state["muestras"] = True
    paths = sorted(MUESTRAS.glob("*.pdf"))

if not paths:
    st.info("Subí PDFs o probá con las facturas de ejemplo (ficticias).")
    st.stop()

with st.spinner(f"Procesando {len(paths)} comprobantes..."):
    comps = procesar_lote(paths)

# --- métricas
n = {e: sum(c.estado == e for c in comps) for e in EMOJI}
m = st.columns(5)
m[0].metric("Comprobantes", len(comps))
m[1].metric("🟢 OK", n["VERDE"])
m[2].metric("🟡 A revisar", n["AMARILLO"])
m[3].metric("🔴 Con errores", n["ROJO"])
m[4].metric("Importe OK", ars(sum(c.total or 0 for c in comps if c.estado == "VERDE")))

# --- tabla
df = pd.DataFrame([{
    "Estado": f"{EMOJI[c.estado]} {c.estado}",
    "Archivo": c.archivo,
    "Tipo": f"Factura {c.letra}" if c.letra else "-",
    "Comprobante": f"{c.pto_vta:05d}-{c.numero:08d}" if c.pto_vta and c.numero else "-",
    "Fecha": c.fecha.strftime("%d/%m/%Y") if c.fecha else "-",
    "Emisor": c.emisor_razon_social,
    "CUIT emisor": c.emisor_cuit,
    "Total": ars(c.total),
    "QR": "✅" if c.qr_presente else "—",
    "Observaciones": c.observaciones() or "Sin observaciones",
} for c in comps])
st.dataframe(df, width="stretch", hide_index=True)

st.download_button("⬇️ Descargar Excel", a_excel(comps), file_name="facturas_validadas.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                   type="primary")

st.caption("¿Querés probarlo con tus facturas reales? Escribinos a cargacero.facturas@gmail.com")

# --- detalle
st.subheader("Detalle por comprobante")
for c in comps:
    with st.expander(f"{EMOJI[c.estado]} {c.archivo}  —  {ars(c.total)}"):
        a, b = st.columns(2)
        with a:
            st.markdown("**Datos extraídos**")
            st.json({
                "tipo": c.letra, "punto_venta": c.pto_vta, "numero": c.numero,
                "fecha": str(c.fecha), "emisor": c.emisor_razon_social, "cuit_emisor": c.emisor_cuit,
                "cuit_receptor": c.receptor_cuit, "neto": c.neto, "iva": c.iva, "total": c.total,
                "cae": c.cae, "vto_cae": str(c.vto_cae), "fuente": "texto + QR" if c.qr_presente else "solo texto",
            })
        with b:
            st.markdown("**Validaciones**")
            for k in c.checks:
                icono = {"OK": "✅", "ALERTA": "⚠️", "ERROR": "❌"}[k.resultado]
                st.write(f"{icono} {k.regla}" + (f" — {k.detalle}" if k.detalle else ""))
        if c.items:
            st.markdown("**Ítems**")
            st.dataframe(pd.DataFrame(c.items), hide_index=True, width="stretch")
