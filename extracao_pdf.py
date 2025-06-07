# extracao_pdf.py
import fitz

def ler_pdf_bytes(pdf_bytes):
    try:
        doc = fitz.open("pdf", pdf_bytes)
        texto = "\n".join(page.get_text() for page in doc)
        return texto, doc
    except Exception as e:
        return f"[Erro ao ler o PDF: {e}]", None
