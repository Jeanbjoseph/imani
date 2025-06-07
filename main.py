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
        cred = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        st.sidebar.info("🔑 Autenticação Blob: Service Principal")
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
# ===================================
# 8. Processar o Excel e rodar a análise (com ou sem IA)
# ===================================
try:
    xls = pd.ExcelFile(uploaded_file)
    abas = xls.sheet_names

    # Se houver mais de uma aba, a primeira (índice 0) é apenas informativa
    if len(abas) > 1:
        aba_escolhida = st.selectbox("Escolha a aba para analisar:", abas[1:], index=0)

        # ——— Montamos o DataFrame da aba “informativa” (índice 0) removendo NaNs e a última coluna ———
        aba_info = pd.read_excel(xls, sheet_name=abas[0])
        aba_info = aba_info.dropna(how="all", axis=0).dropna(how="all", axis=1)
        # Remove a última coluna inteira (conforme você pediu)
        if aba_info.shape[1] > 1:
            aba_info = aba_info.iloc[:, :-1]
        aba_info = aba_info.astype(str)

        with st.expander("ℹ️ Conteúdo da primeira aba (informativa)"):
            st.dataframe(aba_info, use_container_width=True)

    else:
        aba_escolhida = st.selectbox("Escolha a aba para analisar:", abas, index=0)

    # ——— Identifica, na aba escolhida, qual linha contém o cabeçalho “Empresa” ———
    df = pd.read_excel(xls, sheet_name=aba_escolhida, header=None)
    for i in range(10):
        if df.iloc[i].astype(str).str.contains("Empresa").any():
            df.columns = df.iloc[i].astype(str).str.strip()
            df = df[i + 1 :].reset_index(drop=True)
            break

    # ——— Limpa colunas “Unnamed” e converte tudo para string ———
    df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed", na=False)]
    df = df.dropna(axis=1, how="all")
    df = df.astype(str)

    empresa_col = "Empresa"
    arquivo_col = "Nome do arquivo salvo"
    empresas_disponiveis = sorted(df[empresa_col].dropna().unique())
    empresa_selecionada = st.selectbox("Selecione a empresa para análise:", empresas_disponiveis)

    # ——— Definimos um botão “Iniciar Análise” (ou “Somente Diagnóstico”) ———
    if st.button("🔍 Iniciar Análise"):

        st.write("📄 Processando... aguarde alguns segundos 🙂")

        df_filtrado = df[df[empresa_col] == empresa_selecionada].copy()
        container_client = st.session_state.container_client

        resultados: list[dict[str, str]] = []
        diagnosticos: list[dict[str, str]] = []
        total = len(df_filtrado)

        # ——— Barra de progresso e placeholder para status + ETA ———
        barra = st.progress(0)
        status_text = st.empty()

        tempo_inicio = time()

        for i, (_, row) in enumerate(df_filtrado.iterrows()):
            empresa = row[empresa_col].strip()
            nome_arquivo = row[arquivo_col].strip()
            nome_pdf = f"{nome_arquivo}.pdf"
            prefixo = f"Relatórios Técnicos/{empresa}/Relatórios/"

            # ——— Cálculo de ETA ———
            elapsed = time() - tempo_inicio
            avg_per_item = elapsed / (i + 1)
            remaining = avg_per_item * (total - (i + 1))
            remaining_h = int(remaining // 3600)
            remaining_m = int((remaining % 3600) // 60)
            remaining_s = int(remaining % 60)
            eta_str = f"{remaining_h:02d}:{remaining_m:02d}:{remaining_s:02d}"

            status_text.markdown(
                f"🔄 Processando **{empresa} – {nome_arquivo}** (`{i+1}`/`{total}`)  \n"
                f"⏱️ Tempo decorrido: **{elapsed:.1f}s**   |   ⏳ ETA: **{eta_str}**"
            )

            # ——— Tenta listar blobs no prefixo da empresa ———
            try:
                blobs = list(container_client.list_blobs(name_starts_with=prefixo))
            except TypeError as te:
                st.error(f"Erro ao chamar list_blobs(name_starts_with=...): {te}")
                blobs = []

            nomes_disponiveis = [b.name for b in blobs]
            match = [n for n in nomes_disponiveis if nome_pdf.lower() in n.lower()]

            # ——— Prepara o link para a pasta ou para o PDF encontrado ———
            # Note que usamos quote_plus para URL-encodar espaços ou caracteres especiais
            pasta_empresa_url = f"{account_url}/{container_name}/{quote_plus(prefixo)}"
            if match:
                # Se encontrou ao menos um blob cujo nome casa (match[0]), link direto para ele
                link_blob = f"{account_url}/{container_name}/{quote_plus(match[0])}"
            else:
                # Senão, link “genérico” para a pasta da empresa
                link_blob = pasta_empresa_url

            # ——— Executa somente diagnóstico ou diagnóstico + IA ———
            if somente_diagnostico:
                # Chama gerar_diagnostico em qualquer caso (com ou sem PDF)
                if match:
                    # se encontrou, baixa e gera diagnóstico com texto e doc
                    blob = container_client.get_blob_client(match[0])
                    pdf_bytes = blob.download_blob().readall()
                    texto, doc = ler_pdf_bytes(BytesIO(pdf_bytes))
                    diagnosticos.append(
                        gerar_diagnostico(nome_arquivo, match[0], texto, doc)
                    )
                    status = "✔️ Encontrado (diagnóstico)"
                else:
                    # se não encontrou, não há PDF para gerar texto, mas ainda faz diagnóstico “vazio”
                    diagnosticos.append(
                        gerar_diagnostico(nome_arquivo, "-", "", None)
                    )
                    status = "❌ Arquivo não encontrado (diagnóstico)"
                recomendacoes = []  # em somente diagnóstico, não queremos extrair recomendações via IA
            else:
                # Modo “normal”: tenta baixar, extrair texto e enviar pra IA
                if match:
                    blob = container_client.get_blob_client(match[0])
                    pdf_bytes = blob.download_blob().readall()
                    texto, doc = ler_pdf_bytes(BytesIO(pdf_bytes))
                    recomendacoes = azure_ia.extrair_recomendacoes_ia(texto)

                    if recomendacoes:
                        status = "✔️ Encontrado"
                    else:
                        status = "✔️ Encontrado (sem recomendações)"

                    if diagnostico_ativo:
                        diagnosticos.append(
                            gerar_diagnostico(nome_arquivo, match[0], texto, doc)
                        )
                else:
                    recomendacoes = []
                    texto = ""
                    status = "❌ Arquivo não encontrado"
                    if diagnostico_ativo:
                        diagnosticos.append(
                            gerar_diagnostico(nome_arquivo, "-", "", None)
                        )

            # ——— Monta a linha de resultado (empresa, arquivo, status, recomendações, link) ———
            resultados.append({
                "Empresa": empresa,
                "Arquivo": nome_arquivo,
                "Status": status,
                "Recomendações": "\n".join(recomendacoes) if (recomendacoes and not somente_diagnostico) else "-"
            })

            # Atualiza barra de progresso
            pct = int((i + 1) * 100 / total)
            barra.progress(pct)

        status_text.empty()

        # ——— 9. Exibe Tabela de Resultados ———
        st.subheader("🔍 Resultados da Análise")
        df_resultado = pd.DataFrame(resultados).astype(str)

        st.dataframe(df_resultado, use_container_width=True)

        # Botão para baixar resultado em Excel (incluindo a coluna “Link” em texto simples)
        buffer = BytesIO()
        df_resultado.to_excel(buffer, index=False)
        st.download_button(
            "📥 Baixar Resultado em Excel",
            data=buffer.getvalue(),
            file_name="resultado_ia.xlsx"
        )

        # ——— 10. Exibe Diagnóstico Detalhado (se ativado ou se “somente diagnóstico”) ———
        if diagnostico_ativo or somente_diagnostico:
            st.subheader("📋 Diagnóstico Detalhado")

            df_diag = pd.DataFrame(diagnosticos).astype(str)

            # — Remover as colunas indesejadas conforme a imagem (“Título”, “Data de Recebimento”, “Empresa Elaboradora”)
            for coluna_para_remover in ["Título", "Data de Recebimento", "Empresa Elaboradora"]:
                if coluna_para_remover in df_diag.columns:
                    df_diag = df_diag.drop(columns=[coluna_para_remover])

            st.dataframe(df_diag, use_container_width=True)

            buf_diag = BytesIO()
            df_diag.to_excel(buf_diag, index=False)
            st.download_button(
                "📥 Baixar Diagnóstico",
                data=buf_diag.getvalue(),
                file_name="diagnostico_ia.xlsx"
            )

        # ——— Tempo Total Gasto ———
        total_time = time() - tempo_inicio
        modo = "Somente Diagnóstico" if somente_diagnostico else "Análise completa"
        st.success(f"✅ {modo} concluído em **{total_time:.1f} segundos**.")

except Exception as e:
    st.error(f"❌ Erro ao processar arquivo Excel: {e}")
