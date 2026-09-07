import base64
import io
import json
import fitz  # PyMuPDF para manejar PDFs escaneados
import pandas as pd
import pdfplumber
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="AutoExtract", layout="wide")
st.title("📄 AutoExtract - Procesador de Facturas")


# --- ESTILOS CSS PERSONALIZADOS ---
st.markdown(
    """
    <style>
    /* Ocultar elementos nativos de Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Contenedores y botones */
    .stButton>button {
        width: 100%;
        background-color: #2563eb;
        color: white;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: 600;
        border: none;
    }
    .stButton>button:hover {
        background-color: #1d4ed8;
        color: white;
    }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    </style>
""",
    unsafe_allow_html=True,
)


# --- SISTEMA DE AUTENTICACIÓN ---
def check_password():
    """Verifica si el usuario ha introducido la contraseña correcta."""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔒 AutoExtract - Acceso Clientes")
        user_password = st.text_input("Introduce tu clave de acceso:", type="password")
        if st.button("Entrar"):
            # Compara la contraseña con la guardada en Secrets
            correct_password = st.secrets.get("CLIENT_PASSWORD", "cliente1")
            if user_password == correct_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("🔑 Clave incorrecta. Contacta con soporte.")
        return False
    return True

if not check_password():
    st.stop()  # Detiene la ejecución si no ha puesto la contraseña
# ---------------------------------

# Recuperar la API Key directamente de la nube
api_key = st.secrets.get("OPENAI_API_KEY")

st.title("📄 AutoExtract - Procesador de Facturas")
st.success("Sesión iniciada correctamente")

st.sidebar.header("Configuración")
api_key = st.sidebar.text_input("OpenAI API Key (sk-...)", type="password")

uploaded_files = st.file_uploader(
    "Arrastra o selecciona facturas en PDF",
    type=["pdf"],
    accept_multiple_files=True,
)


def extract_text_from_pdf(pdf_file):
  """Intenta extraer texto de un PDF nativo."""
  text = ""
  with pdfplumber.open(pdf_file) as pdf:
    for page in pdf.pages:
      extracted = page.extract_text()
      if extracted:
        text += extracted + "\n"
  return text.strip()


def convert_pdf_to_base64_image(pdf_file):
  """Convierte la primera página de un PDF escaneado a imagen para la Visión de OpenAI."""
  pdf_file.seek(0)
  doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
  page = doc[0]
  pix = page.get_pixmap(dpi=150)
  img_bytes = pix.tobytes("png")
  return base64.b64encode(img_bytes).decode("utf-8")


def parse_invoice_text(text, client):
  """Procesa texto directo con gpt-4o-mini."""
  prompt = f"""
    Extrae los datos clave de la siguiente factura.
    Responde ÚNICAMENTE con un objeto JSON estricto con esta estructura:
    {{
        "cif_emisor": "NIF/CIF del emisor o N/A",
        "proveedor": "Nombre o Razón Social del emisor",
        "fecha": "YYYY-MM-DD",
        "base_imponible": 0.00,
        "iva": 0.00,
        "total": 0.00
    }}

    Texto de la factura:
    {text}
    """
  response = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{"role": "user", "content": prompt}],
      response_format={"type": "json_object"},
      temperature=0.0,
  )
  return json.loads(response.choices[0].message.content)


def parse_invoice_image(base64_img, client):
  """Procesa facturas escaneadas usando Visión por IA."""
  response = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[{
          "role": "user",
          "content": [
              {
                  "type": "text",
                  "text": (
                      "Extrae los datos clave de esta imagen de factura."
                      " Responde ÚNICAMENTE con un objeto JSON estricto:"
                      ' {"cif_emisor": "NIF/CIF o N/A", "proveedor": "Nombre'
                      ' emisor", "fecha": "YYYY-MM-DD", "base_imponible": 0.00,'
                      ' "iva": 0.00, "total": 0.00}'
                  ),
              },
              {
                  "type": "image_url",
                  "image_url": {
                      "url": f"data:image/png;base64,{base64_img}",
                      "detail": "high",
                  },
              },
          ],
      }],
      response_format={"type": "json_object"},
      temperature=0.0,
  )
  return json.loads(response.choices[0].message.content)


if uploaded_files and api_key:
  if st.button("🚀 Procesar Facturas Ahora"):
    client = OpenAI(api_key=api_key)
    results = []
    errors = []

    with st.spinner("Procesando documentos..."):
      for file in uploaded_files:
        try:
          text = extract_text_from_pdf(file)
          if text:
            # Modo rápido de texto
            data = parse_invoice_text(text, client)
          else:
            # Modo visión para PDFs escaneados / imágenes
            base64_img = convert_pdf_to_base64_image(file)
            data = parse_invoice_image(base64_img, client)

          data["archivo"] = file.name
          results.append(data)

        except Exception as e:
          errors.append({"archivo": file.name, "motivo": str(e)})

    if results:
        # --- LÓGICA DE CÁLCULO Y LIMPIEZA AUTOMÁTICA DE DATOS ---
        for factura in results:
            # Convertir/asegurar valores numéricos
            try:
                total = float(factura.get("total") or 0)
            except (ValueError, TypeError):
                total = 0.0

            try:
                base = float(factura.get("base_imponible") or 0)
            except (ValueError, TypeError):
                base = 0.0

            try:
                iva = float(factura.get("iva") or 0)
            except (ValueError, TypeError):
                iva = 0.0

            # Si hay un total positivo pero falta la base o el IVA (asumimos 21% IVA en España)
            if total > 0 and (base == 0 or iva == 0):
                base = round(total / 1.21, 2)
                iva = round(total - base, 2)
                factura["base_imponible"] = base
                factura["iva"] = iva

            # Si no había total pero sí base e IVA, aseguramos el cálculo del total
            elif total == 0 and (base > 0 or iva > 0):
                total = round(base + iva, 2)
                factura["total"] = total

            # Limpieza visual del CIF/NIF si el documento carece de él
            cif = str(factura.get("cif_emisor") or "").strip()
            if not cif or cif.upper() in ["N/A", "NONE", "NULL", "0"]:
                factura["cif_emisor"] = "Sin CIF / No consta"

        # --- CONSTRUCCIÓN DEL DATAFRAME ---
        df = pd.DataFrame(results)
        cols = [
            "archivo",
            "proveedor",
            "cif_emisor",
            "fecha",
            "base_imponible",
            "iva",
            "total",
        ]
        df = df[[c for c in cols if c in df.columns]]

        # --- 1. TARJETAS DE MÉTRICAS (KPIs) ---
        st.subheader("📊 Resumen del Procesamiento")
        col1, col2, col3, col4 = st.columns(4)

        total_docs = len(df)
        suma_bases = df["base_imponible"].sum() if "base_imponible" in df else 0
        suma_ivas = df["iva"].sum() if "iva" in df else 0
        suma_totales = df["total"].sum() if "total" in df else 0

        col1.metric("Facturas Procesadas", f"{total_docs} uds")
        col2.metric("Base Imponible", f"{suma_bases:,.2f} €")
        col3.metric("Total IVA", f"{suma_ivas:,.2f} €")
        col4.metric("Importe Total", f"{suma_totales:,.2f} €")

        st.divider()

        # --- 2. TABLA DE DATOS ---
        st.subheader("📋 Detalle de Documentos")
        st.dataframe(df, use_container_width=True, hide_index=True)

        # --- 3. BOTÓN DE DESCARGA EN EXCEL ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Facturas")

        st.download_button(
            label="📥 Descargar Reporte Completo en Excel (.xlsx)",
            data=output.getvalue(),
            file_name="facturas_procesadas.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    if errors:
      st.warning("⚠️ Documentos con errores:")
      st.table(pd.DataFrame(errors))

elif not api_key and uploaded_files:
  st.warning(
      "👈 Introduce tu API Key de OpenAI en la barra lateral para procesar."
  )
