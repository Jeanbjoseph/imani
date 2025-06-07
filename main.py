import streamlit as st
import pandas as pd
import fitz
from io import BytesIO
from time import time
from urllib.parse import quote_plus

from azure.storage.blob import BlobServiceClient
from azure.identity import ClientSecretCredential, DefaultAzureCredential

from extracao_pdf import ler_pdf_bytes
from utilidades import extrair_data, extrair_empresa, gerar_diagnostico
import azure_ia  # configure_azure(...) e extrair_recomendacoes_ia(...)

# ================================
# Configurações via Streamlit Secrets
# ================================
secrets = st.secrets

# Azure OpenAI
azure_endpoint = secrets["AZURE_OPENAI_ENDPOINT"].rstrip("/")
deployment_name = secrets["AZURE_OPENAI_DEPLOYMENT_NAME"]
azure_ia.configure_azure(azure_endpoint, deployment_name)
if azure_ia.client is None:
    st.error("❌ Falha ao inicializar o cliente Azure OpenAI. Confira seu endpoint e deployment.")
    st.stop()
else:
    st.sidebar.success("✅ Azure OpenAI configurado.")

# Azure Blob Storage
account_url = secrets["BLOB_ACCOUNT_URL"].rstrip("/")
container_name = secrets["BLOB_CONTAINER_NAME"]
auth_method = secrets.get("BLOB_AUTH_METHOD", "service_principal").lower()

try:
    if auth_method == "service_principal":
        blob_credential = ClientSecretCredential(
            tenant_id=secrets["BLOB_TENANT_ID"],
            client_id=secrets["BLOB_CLIENT_ID"],
            client_secret=secrets["BLOB_CLIENT_SECRET"],
        )
        st.sidebar.info("🔑 Autenticação Blob: Service Principal")
    elif auth_method == "azure_cli":
        blob_credential = DefaultAzureCredential()
        st.sidebar.info("🔑 Autenticação Blob: Azure CLI (DefaultAzureCredential)")
    else:
        raise KeyError(f"Método de autenticação desconhecido: {auth_method}")

    blob_service_client = BlobServiceClient(
        account_url=account_url,
        credential=blob_credential
    )
    container_client = blob_service_client.get_container_client(container_name)
    container_client.get_container_properties()
    st.sidebar.success(f"✅ Conectado ao container `{container_name}`")
    st.session_state.container_client = container_client

except Exception as e:
    st.error(f"❌ Falha ao conectar no Blob Storage: {e}")
    st.stop()

# ================================
# Interface do IMANI
# ================================
st.set_page_config(page_title="IMANI: Analisador IA + Azure Blob", layout="wide")
st.title("📂 IMANI: Analisador de Relatórios utilizando IA")

somente_diagnostico = st.sidebar.checkbox("🩺 Executar apenas Diagnóstico (sem IA)", value=False)

diagnostico_ativo = st.sidebar.checkbox("🔎 Incluir Diagnóstico Detalhado?", value=False)

# upload do Excel
uploaded_file = st.file_uploader("📤 Envie o arquivo Excel com os projetos", type=[".xlsx"])
if not uploaded_file:
    st.info("📄 Faça o upload do arquivo Excel para começar a análise.")
    st.stop()

# processamento do Excel e análise
try:
    xls = pd.ExcelFile(uploaded_file)
    abas = xls.sheet_names
    
    # Seleção de aba
    if len(abas) > 1:
        aba_escolhida = st.selectbox("Escolha a aba para analisar:", abas[1:], index=0)
        # mostrar primeira aba informativa
        aba_info = pd.read_excel(xls, sheet_name=abas[0])
        aba_info = aba_info.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if aba_info.shape[1] > 1:
            aba_info = aba_info.iloc[:, :-1]
        aba_info = aba_info.astype(str)
        with st.expander("ℹ️ Conteúdo da primeira aba (informativa)"):
            st.dataframe(aba_info, use_container_width=True)
    else:
        aba_escolhida = st.selectbox("Escolha a aba para analisar:", abas, index=0)

    # leitura e limpeza de dados
    df = pd.read_excel(xls, sheet_name=aba_escolhida, header=None)
    for i in range(10):
        if df.iloc[i].astype(str).str.contains("Empresa").any():
            df.columns = df.iloc[i].astype(str).str.strip()
            df = df[i+1:].reset_index(drop=True)
            break
    df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed", na=False)]
    df = df.dropna(axis=1, how="all").astype(str)

    empresa_col = "Empresa"
    arquivo_col = "Nome do arquivo salvo"
    empresas_disponiveis = sorted(df[empresa_col].dropna().unique())
    empresa_selecionada = st.selectbox("Selecione a empresa para análise:", empresas_disponiveis)

    if st.button("🔍 Iniciar Análise"):
        st.write("📄 Processando... aguarde alguns segundos 🙂")
        df_filtrado = df[df[empresa_col] == empresa_selecionada].copy()
        total = len(df_filtrado)
        barra = st.progress(0)
        status_text = st.empty()
        tempo_inicio = time()
        resultados = []
        diagnosticos = []

        for i, (_, row) in enumerate(df_filtrado.iterrows()):
            empresa = row[empresa_col].strip()
            nome_arquivo = row[arquivo_col].strip()
            nome_pdf = f"{nome_arquivo}.pdf"
            prefixo = f"Relatórios Técnicos/{empresa}/Relatórios/"

            elapsed = time() - tempo_inicio
            avg = elapsed/(i+1)
            rem = avg*(total-(i+1))
            eta = f"{int(rem//3600):02d}:{int((rem%3600)//60):02d}:{int(rem%60):02d}"
            status_text.markdown(
                f"🔄Processando **{empresa} – {nome_arquivo}** (`{i+1}`/`{total}`)  ⏳ ETA: **{eta}**"
            )

            # busca no Blob
            blobs = list(container_client.list_blobs(name_starts_with=prefixo))
            nomes = [b.name for b in blobs]
            match = [n for n in nomes if nome_pdf.lower() in n.lower()]

            pasta_url = f"{account_url}/{container_name}/{quote_plus(prefixo)}"
            if match:
                link_blob = f"{account_url}/{container_name}/{quote_plus(match[0])}"
            else:
                link_blob = pasta_url

            # somente diagnóstico
            if somente_diagnostico:
                if match:
                    blob = container_client.get_blob_client(match[0])
                    pdf_bytes = blob.download_blob().readall()
                    texto, doc = ler_pdf_bytes(BytesIO(pdf_bytes))
                    diagnosticos.append(gerar_diagnostico(nome_arquivo, match[0], texto, doc))
                    status = "✔️ Encontrado (diagnóstico)"
                else:
                    diagnosticos.append(gerar_diagnostico(nome_arquivo, "-", "", None))
                    status = "❌ Arquivo não encontrado (diagnóstico)"
                recomendacoes = []
            else:
                if match:
                    blob = container_client.get_blob_client(match[0])
                    pdf_bytes = blob.download_blob().readall()
                    texto, doc = ler_pdf_bytes(BytesIO(pdf_bytes))
                    recomendacoes = azure_ia.extrair_recomendacoes_ia(texto)
                    status = "✔️ Encontrado" if recomendacoes else "✔️ Encontrado (sem recomendações)"
                    if diagnostico_ativo:
                        diagnosticos.append(gerar_diagnostico(nome_arquivo, match[0], texto, doc))
                else:
                    recomendacoes = []
                    status = "❌ Arquivo não encontrado"
                    if diagnostico_ativo:
                        diagnosticos.append(gerar_diagnostico(nome_arquivo, "-", "", None))

            resultados.append({
                "Empresa": empresa,
                "Arquivo": nome_arquivo,
                "Status": status,
                "Recomendações": "\n".join(recomendacoes) if recomendacoes else "-"
            })
            barra.progress(int((i+1)*100/total))
        status_text.empty()

        # exibir resultados
        st.subheader("🔍 Resultados da Análise")
        df_res = pd.DataFrame(resultados).astype(str)
        st.dataframe(df_res, use_container_width=True)
        buf = BytesIO(); df_res.to_excel(buf, index=False)
        st.download_button("📥 Baixar Resultado em Excel", buf.getvalue(), "resultado_ia.xlsx")

        if diagnostico_ativo or somente_diagnostico:
            st.subheader("📋 Diagnóstico Detalhado")
            df_diag = pd.DataFrame(diagnosticos).astype(str)
            for col in ["Título","Data de Recebimento","Empresa Elaboradora"]:
                if col in df_diag.columns:
                    df_diag = df_diag.drop(columns=[col])
            st.dataframe(df_diag, use_container_width=True)
            buf2 = BytesIO(); df_diag.to_excel(buf2, index=False)
            st.download_button("📥 Baixar Diagnóstico", buf2.getvalue(), "diagnostico.xlsx")

        st.success(f"✅ Análise concluída em {time()-tempo_inicio:.1f}s")

except Exception as e:
    st.error(f"❌ Erro ao processar arquivo Excel: {e}")
