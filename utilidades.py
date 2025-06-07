# utilidades.py
import re

def extrair_data(texto):
    match = re.search(r"\d{2}/\d{2}/\d{4}", texto)
    return match.group(0) if match else "-"

def extrair_empresa(texto):
    for linha in texto.split("\n"):
        if "elaborado por" in linha.lower() or "responsável" in linha.lower():
            return linha.strip()
    return "-"

def gerar_diagnostico(nome_excel, nome_blob, texto, doc):
    return {
        "Nome no Excel": nome_excel,
        "Nome Encontrado": nome_blob.split("/")[-1],
        "Match Exato": "Sim" if nome_excel + ".pdf" == nome_blob.split("/")[-1] else "Não",
        "Título": texto.split("\n")[0][:100] if texto else "-",
        "Data de Recebimento": extrair_data(texto),
        "Empresa Elaboradora": extrair_empresa(texto),
        "Páginas": doc.page_count if doc else "-"
    }
