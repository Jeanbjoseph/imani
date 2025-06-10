import streamlit as st
from azure.identity import ClientSecretCredential
from openai import AzureOpenAI

# Globais para cliente e deployment
client = None
deployment = None

def configure_azure(azure_endpoint: str, deployment_name: str):
    """
    Inicializa o cliente AzureOpenAI usando Service Principal (AAD) via ClientSecretCredential.
    """
    try:
        # Lê credenciais do AAD de st.secrets
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
            azure_api_base=azure_endpoint,
            azure_api_version="2025-01-01-preview",
            deployment_name=deployment_name,
            credential=credential
        )
        st.sidebar.success("✅ Azure OpenAI configurado (AAD Service Principal)")
    except Exception as e:
        st.error(f"❌ Falha ao configurar Azure OpenAI: {e}")
        client = None
        deployment = None


def extrair_recomendacoes_ia(texto: str) -> list[str]:
    """
    Extrai recomendações técnicas do texto usando AzureOpenAI.
    """
    if client is None or not deployment:
        st.error("❌ AzureOpenAI não está configurado. Verifique suas chaves em st.secrets.")
        return []

      prompt = [
        {
            "role": "system",
            "content": "Você é um especialista em engenharia que extrai recomendações técnicas de documentos."
        },
        {
            "role": "user",
            "content": (
                "Leia o relatório técnico a seguir e extraia APENAS as recomendações  técnicas obligatórios presentes, "
                "principalmente nas conclusões. Apresente-as de forma clara e objetiva, "
                "utilizando bullet points para facilitar a cópia e organização no Excel:"
                "Não apresente as recomendações que são sugestões"
                "Apresente cada recomendação em uma linha numerada: 1. , 2. , etc"
                "Não utilizar símbolos (*, $, #) nem pontuação especial além da numeração e texto limpo"
                "Alem nas conslusões,Sempre olhar no corpo do texto para verificar se tem recomendações"
                "Os texto que você vai receber pode estar em qualquer lingua"
                " Sempre listar as recomendações encontradas na lingua portugues formal e tecnica \n\n"
                f"{texto}"
            )
        }
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
