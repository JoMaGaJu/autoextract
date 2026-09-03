import base64
import io
import json
import fitz  # PyMuPDF para manejar PDFs escaneados
import pandas as pd
import pdfplumber
import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="AutoExtract B2B", layout="wide")
st.title("📄 AutoExtract B2B - Procesador de Facturas (Texto y Escaneadas)")

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
      st.subheader("📊 Datos Extraídos")
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
      st.dataframe(df, use_container_width=True)

      output = io.BytesIO()
      with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Facturas")

      st.download_button(
          label="📥 Descargar Resultado en Excel (.xlsx)",
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