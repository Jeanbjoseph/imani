import os
import streamlit as st
import pandas as pd
import fitz
import re
from io import BytesIO
from time import time
from urllib.parse import quote_plus

from azure.storage.blob import BlobServiceClient
from azure.identity import ClientSecretCredential, DefaultAzureCredential

from extracao_pdf import ler_pdf_bytes
from utilidades import extrair_data, extrair_empresa, gerar_diagnostico
import azure_ia  # configure_azure() e extrair_recomendacoes_ia()

# ================================
# Configuração inicial do Streamlit
# ================================
st.set_page_config(page_title="IMANI: Analisador IA + Azure Blob via App Settings", layout="wide")
st.title("IMANI: Analisador de Relatórios utilizando IA")

# ================================
# 0. Checkbox para “Somente Diagnóstico”
# ================================
somente_diagnostico = st.sidebar.checkbox("🩺 Executar apenas Diagnóstico (sem IA)", value=False)

# ===================================
# 1. Expander “Sobre o IMANI”
# ===================================
with st.expander("ℹ️ Sobre o IMANI – Histórico e Propósito"):
    st.write(
        """
        O IMANI é um software desenvolvido para automatizar a extração de recomendações técnicas
        de relatórios em PDF, utilizando inteligência artificial (Azure OpenAI). O nome “IMANI”
        vem do termo Swahili que significa “confiança” ou “fé”, refletindo a ideia de que podemos
        confiar nas tecnologias para agilizar processos de revisão técnica.

        A origem do projeto remonta à necessidade de equipes de engenharia geotécnica e de mineração
        acessarem rapidamente insights de diversos relatórios, sem perder tempo com leitura manual
        extensiva. Com o IMANI, o usuário fornece os relatórios e um Excel de projetos, e a ferramenta
        faz varredura nos PDFs, extrai recomendações e gera diagnósticos detalhados, poupando horas
        de trabalho manual e garantindo consistência nas conclusões.

        🔹 **Somente Diagnóstico**: marque a opção “Executar apenas Diagnóstico” na barra lateral
        se você quiser gerar um arquivo de diagnóstico (por exemplo, conferindo quais arquivos não
        foram encontrados) sem acionar a IA para extrair recomendações.

        🔹 **Links para relatórios**: nos resultados, apresentamos um link que leva diretamente
        à pasta “Relatórios Técnicos/{Empresa}/Relatórios/” ou ao PDF encontrado. Caso o arquivo
        não exista, o link aponta para a pasta da empresa, para que você possa navegar manualmente.
        
        Lembre-se: o IMANI deve ser utilizado apenas como apoio. A decisão final sobre cada
        recomendação cabe sempre ao usuário.
        """
    )

# ================================================
# 2. Leitura das configurações do ambiente (App Settings Secrets)
# ================================================
azure_endpoint        = os.getenv("AZURE_OPENAI_ENDPOINT")
deployment_name       = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
account_url           = os.getenv("BLOB_ACCOUNT_URL")
container_name        = os.getenv("BLOB_CONTAINER_NAME")
auth_method           = os.getenv("BLOB_AUTH_METHOD", "azure_cli").lower()

# Para service principal:
client_id             = os.getenv("BLOB_CLIENT_ID")
client_secret         = os.getenv("BLOB_CLIENT_SECRET")
tenant_id             = os.getenv("BLOB_TENANT_ID")

# Validação de variáveis obrigatórias
missing = []
for var, val in {
    "AZURE_OPENAI_ENDPOINT": azure_endpoint,
    "AZURE_OPENAI_DEPLOYMENT_NAME": deployment_name,
    "BLOB_ACCOUNT_URL": account_url,
    "BLOB_CONTAINER_NAME": container_name,
    "BLOB_AUTH_METHOD": auth_method,
}.items():
    if not val:
        missing.append(var)
if auth_method == "service_principal":
    for sp in ("BLOB_CLIENT_ID", "BLOB_CLIENT_SECRET", "BLOB_TENANT_ID"):
        if not os.getenv(sp):
            missing.append(sp)
if missing:
    st.error(f"❌ Configuração de ambiente faltando: {', '.join(missing)}")
    st.stop()

# ===================================
# 3. Configurar Azure OpenAI
# ===================================
try:
    azure_ia.configure_azure(azure_endpoint.rstrip("/"), deployment_name)
except Exception as e:
    st.error(f"❌ Erro ao configurar Azure OpenAI: {e}")
    st.stop()
if azure_ia.client is None:
    st.error("❌ Falha ao inicializar o cliente Azure OpenAI. Confira suas configurações de App Settings.")
    st.stop()
else:
    st.sidebar.success("✅ Azure OpenAI configurado.")

# ===================================
# 4. Configurar Azure Blob Storage
# ===================================
try:
    if auth_method == "service_principal":
        cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
        st.sidebar.info("🔑 Autenticação Blob: Service Principal")
    elif auth_method == "username_password":
        from azure.identity import UsernamePasswordCredential
        cred = UsernamePasswordCredential(
            username=os.getenv("BLOB_USERNAME"),
            password=os.getenv("BLOB_PASSWORD"),
            tenant_id=tenant_id
        )
        st.sidebar.info("🔑 Autenticação Blob: Usuário/Senha")
    else:
        cred = DefaultAzureCredential()
        st.sidebar.info("🔑 Autenticação Blob: DefaultAzureCredential (Azure CLI / Managed Identity)")

    blob_service = BlobServiceClient(account_url.rstrip("/"), credential=cred)
    container_client = blob_service.get_container_client(container_name)
    container_client.get_container_properties()
    st.sidebar.success(f"✅ Conectado ao container `{container_name}`")
    st.session_state.container_client = container_client

except Exception as e:
    st.error(f"❌ Falha ao conectar no Blob Storage: {e}")
    st.stop()

# ===================================
# 5. Tudo configurado: upload do Excel
# ===================================
st.success("🚀 Configurações carregadas! Agora faça o upload do seu Excel para iniciar a análise.")

uploaded_file = st.file_uploader("📤 Envie o arquivo Excel com os projetos", type=[".xlsx"])
if not uploaded_file:
    st.info("📄 Faça o upload do arquivo Excel para começar a análise.")
    st.stop()

# (O restante do fluxo permanece inalterado: leitura do Excel, progressão, IA e diagnóstico.)
