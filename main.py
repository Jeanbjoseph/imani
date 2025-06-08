# main.py

import streamlit as st
import pandas as pd
import fitz
from io import BytesIO
from time import time
from urllib.parse import quote_plus

from azure.storage.blob import BlobServiceClient
# Changed from azure.identity import ClientSecretCredential, DefaultAzureCredential
# to import from st.secrets directly for credential handling
from azure.identity import ClientSecretCredential, DefaultAzureCredential, UsernamePasswordCredential # Import all necessary credentials

from extracao_pdf import ler_pdf_bytes
from utilidades import extrair_data, extrair_empresa, gerar_diagnostico
import azure_ia

# ================================
# Configuração inicial do Streamlit
# ================================
st.set_page_config(page_title="Analisador IA + Azure Blob via Streamlit Secrets", layout="wide") # Updated title
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

# ===================================
# 2. No more parse_dotenv or .env upload, using st.secrets directly
# ===================================

# ===================================
# 3. Access secrets directly from st.secrets
# ===================================
st.sidebar.header("1. Configurações de Acesso (via Streamlit Secrets)")

# Check if secrets are available
if not st.secrets:
    st.error("❌ As variáveis de ambiente (segredos) não estão configuradas. Por favor, configure-as no Streamlit Cloud ou em .streamlit/secrets.toml localmente.")
    st.stop()

# ===================================
# 4. Validação das chaves obrigatórias em st.secrets
# ===================================
chaves_obrigatorias = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
    "BLOB_ACCOUNT_URL",
    "BLOB_CONTAINER_NAME",
    "BLOB_AUTH_METHOD"
]
faltando = [c for c in chaves_obrigatorias if c not in st.secrets]
if faltando:
    st.error(f"❌ Variáveis obrigatórias faltando nos segredos do Streamlit: {', '.join(faltando)}")
    st.stop()

# ===================================
# 5. Configurar Azure OpenAI
# ===================================
azure_endpoint = st.secrets["AZURE_OPENAI_ENDPOINT"].rstrip("/")
deployment_name = st.secrets["AZURE_OPENAI_DEPLOYMENT_NAME"]
try:
    azure_ia.configure_azure(azure_endpoint, deployment_name)
except Exception as e:
    st.error(f"❌ Erro ao configurar Azure OpenAI: {e}")
    st.stop()

if azure_ia.client is None:
    st.error("❌ Falha ao inicializar o cliente Azure OpenAI. Confira seu endpoint e deployment.")
    st.stop()
else:
    st.sidebar.success("✅ Azure OpenAI configurado.")

# ===================================
# 6. Configurar Azure Blob Storage
# ===================================
account_url = st.secrets["BLOB_ACCOUNT_URL"].rstrip("/")
container_name = st.secrets["BLOB_CONTAINER_NAME"]
auth_method = st.secrets["BLOB_AUTH_METHOD"].lower()

try:
    if auth_method == "service_principal":
        client_id = st.secrets.get("BLOB_CLIENT_ID", "")
        client_secret = st.secrets.get("BLOB_CLIENT_SECRET", "")
        tenant_id = st.secrets.get("BLOB_TENANT_ID", "")
        if not client_id or not client_secret or not tenant_id:
            raise KeyError("BLOB_CLIENT_ID, BLOB_CLIENT_SECRET e BLOB_TENANT_ID devem estar nos segredos.")
        blob_credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        st.sidebar.info("🔑 Autenticação Blob: Service Principal")

    elif auth_method == "username_password":
        username = st.secrets.get("BLOB_USERNAME", "")
        password = st.secrets.get("BLOB_PASSWORD", "")
        tenant_id = st.secrets.get("BLOB_TENANT_ID", "")
        if not username or not password or not tenant_id:
            raise KeyError("BLOB_USERNAME, BLOB_PASSWORD e BLOB_TENANT_ID devem estar nos segredos.")
        blob_credential = UsernamePasswordCredential( # Correctly import UsernamePasswordCredential
            username=username,
            password=password,
            tenant_id=tenant_id
        )
        st.sidebar.info("🔑 Autenticação Blob: Usuário/Senha")

    else:  # azure_cli
        blob_credential = DefaultAzureCredential()
        st.sidebar.info("🔑 Autenticação Blob: Azure CLI (DefaultAzureCredential) - Pode exigir autenticação no ambiente de deploy.")

    # Instancia o BlobServiceClient e obtém o container_client
    blob_service_client = BlobServiceClient(
        account_url=account_url,
        credential=blob_credential
    )
    container_client = blob_service_client.get_container_client(container_name)
    container_client.get_container_properties()  # Verificação de existência
    st.sidebar.success(f"✅ Conectado ao container `{container_name}`")
    st.session_state.container_client = container_client

except KeyError as err_key:
    st.error(f"❌ Chave obrigatória faltando nos segredos do Streamlit: {err_key}")
    st.stop()
except Exception as e:
    st.error(f"❌ Falha ao conectar no Blob Storage: {e}")
    st.stop()

# ===================================
# 7. Tudo configurado: upload do Excel
# ===================================
st.success("🚀 Tudo configurado! Agora faça o upload do seu Excel para iniciar a análise.")

uploaded_file = st.file_uploader("📤 Envie o arquivo Excel com os projetos", type=[".xlsx"])
diagnostico_ativo = st.checkbox("🔎 Incluir Diagnóstico Detalhado?")

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
                f"⏱️ Tempo decorrido: **{elapsed:.1f}s** |   ⏳ ETA: **{eta_str}**"
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