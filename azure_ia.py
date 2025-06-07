# azure_ia.py
import streamlit as st
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# Variáveis globais que serão configuradas via main.py
client = None
deployment = None

def configure_azure(azure_endpoint: str, deployment_name: str):
    """
    Inicializa o cliente AzureOpenAI com o endpoint e deployment informados.
    Deve ser chamado antes de chamar extrair_recomendacoes_ia().
    """
    try:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default"
        )
        global client, deployment
        deployment = deployment_name
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=token_provider,
            api_version="2025-01-01-preview",
        )
    except Exception as e:
        st.error(f"❌ Falha ao configurar Azure OpenAI: {e}")
        client = None
        deployment = None

def extrair_recomendacoes_ia(texto: str) -> list[str]:
    """
    Extrai recomendações técnicas do texto (usando AzureOpenAI).
    Antes de chamar esta função, é obrigatório ter chamado configure_azure().
    """
    if client is None or deployment is None:
        st.error("❌ Azure IA não está configurado. Informe o endpoint e o deployment na sidebar.")
        return []

    prompt = [
        {
            "role": "system",
            "content": "Você é um especialista em engenharia que extrai recomendações técnicas de documentos."
        },
        {
            "role": "user",
            "content": (
                "Leia o relatório técnico a seguir e extraia todas as recomendações técnicas presentes, "
                "principalmente nas conclusões. Apresente-as de forma clara e objetiva, "
                "utilizando bullet points para facilitar a cópia e organização no Excel:\n\n"
                f"{texto}"
            )
        }
    ]

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=prompt,
            max_tokens=4096,
            top_p=1.0,
            temperature=1.0
        )
        resultado = response.choices[0].message.content.strip()
        # Cada linha que começa com "-" ou "•" vira um item da lista
        return [linha.strip("-• ").strip() for linha in resultado.split("\n") if linha.strip()]
    except Exception as e:
        st.error(f"❌ Erro ao chamar AzureOpenAI: {e}")
        return []
