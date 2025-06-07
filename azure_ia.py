import streamlit as st
from openai import AzureOpenAI
from azure.identity import ClientSecretCredential

# Variáveis globais para o cliente e deployment
client = None
deployment = None

def configure_azure(azure_endpoint: str, deployment_name: str):
    """
    Inicializa o cliente AzureOpenAI usando credenciais armazenadas em st.secrets.
    Remove qualquer hard-coded secret do código para evitar alertas de detecção.
    """
    try:
        # Credenciais sem hard-code, lidas do Streamlit Secrets
        tenant_id = st.secrets["BLOB_TENANT_ID"]
        client_id = st.secrets["BLOB_CLIENT_ID"]
        client_secret = st.secrets["BLOB_CLIENT_SECRET"]

        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )

        global client, deployment
        deployment = deployment_name
        client = AzureOpenAI(
            endpoint=azure_endpoint,
            deployment_name=deployment_name,
            credential=credential,
            api_version="2025-01-01-preview"
        )
        st.sidebar.success("✅ Azure OpenAI configurado com Service Principal sem expor secrets no código.")
    except Exception as e:
        st.error(f"❌ Falha ao configurar Azure OpenAI: {e}")
        client = None
        deployment = None


def extrair_recomendacoes_ia(texto: str) -> list[str]:
    """
    Extrai recomendações técnicas usando o cliente AzureOpenAI configurado.
    """
    if client is None or deployment is None:
        st.error("❌ AzureOpenAI não está configurado. Verifique suas chaves em st.secrets.")
        return []

    prompt = [
        {"role": "system", "content": "Você é um especialista em engenharia que extrai recomendações técnicas."},
        {"role": "user",   "content": f"Extraia as recomendações técnicas (bullets) do texto a seguir:\n\n{texto}"}
    ]
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=prompt,
            max_tokens=1024,
            temperature=0.7
        )
        raw = resp.choices[0].message.content or ""
        return [item.strip("-• ") for item in raw.split("\n") if item.strip()]
    except Exception as e:
        st.error(f"❌ Erro ao chamar AzureOpenAI: {e}")
        return []
