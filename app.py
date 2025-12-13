import streamlit as st
import pandas as pd
import plotly.express as px
import re

# ==========================================
# ⚙️ CONFIGURAÇÃO DAS COLUNAS (AJUSTE AQUI!)
# ==========================================
# Busca a URL dentro dos segredos (ou coloque direto se for rodar local sem secrets)
try:
    SHEET_URL = st.secrets["SHEET_URL"]
except:
    # Fallback caso não tenha configurado secrets localmente
    st.error("Configure o SHEET_URL no arquivo .streamlit/secrets.toml")
    st.stop()

# Indique o número da coluna (A=0, B=1, C=2, D=3, E=4, ... I=8, ... R=17)
COL_TICKER = 0   # Coluna A (Onde estão os códigos)
COL_VP = 11       # Coluna B (Vem do Script)
COL_QTD = 5      # <--- AJUSTE ISTO! (Onde está a Quantidade? Ex: Coluna D = 3)
COL_PM = 9       # <--- AJUSTE ISTO! (Onde está o Preço Médio? Ex: Coluna E = 4)
COL_PRECO = 8    # Coluna I (Vem do GoogleFinance)
COL_DY = 17      # Coluna R (Vem do Script)
# ==========================================

st.set_page_config(page_title="Carteira Inteligente FIIs", layout="wide", page_icon="🏢")

# CSS Ajustado
st.markdown("""
<style>
    .metric-card { background-color: #f9f9f9; border-radius: 8px; padding: 15px; border: 1px solid #eee; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; color: #0068c9; }
    /* Botão de copiar estilo */
    .stCode { font-family: monospace; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def carregar_dados():
    try:
        df = pd.read_csv(SHEET_URL, header=None)
        dados_limpos = []

        for index, row in df.iterrows():
            try:
                raw_ticker = str(row[COL_TICKER]).strip().upper()
                # Validação Regex
                if not re.match(r'^[A-Z]{4}11[B]?$', raw_ticker): continue

                def get_float(val):
                    if pd.isna(val) or str(val).strip() == "": return 0.0
                    s = str(val).replace("R$", "").replace("%", "").replace(" ", "")
                    s = s.replace(".", "").replace(",", ".")
                    try: return float(s)
                    except: return 0.0

                item = {
                    "Ticker": raw_ticker,
                    "Qtd": get_float(row[COL_QTD]),
                    "Preço Médio": get_float(row[COL_PM]),
                    "Preço Atual": get_float(row[COL_PRECO]),
                    "VP": get_float(row[COL_VP]),
                    "DY (12m)": get_float(row[COL_DY]),
                    # Link Automático para o Investidor10
                    "Link": f"https://investidor10.com.br/fiis/{raw_ticker.lower()}/"
                }
                
                if item["Qtd"] > 0:
                    dados_limpos.append(item)
            except: continue

        df_final = pd.DataFrame(dados_limpos)
        if df_final.empty: return df_final

        # Remover Duplicatas
        df_final = df_final.drop_duplicates(subset=["Ticker"], keep="first")

        # Cálculos
        df_final["Total Investido"] = df_final["Qtd"] * df_final["Preço Médio"]
        df_final["Valor Atual"] = df_final["Qtd"] * df_final["Preço Atual"]
        df_final["Lucro R$"] = df_final["Valor Atual"] - df_final["Total Investido"]
        df_final["Var %"] = ((df_final["Valor Atual"] / df_final["Total Investido"]) - 1)
        df_final["P/VP"] = df_final["Preço Atual"] / df_final["VP"]
        
        # Ajuste DY e Renda
        df_final["DY (12m)"] = df_final["DY (12m)"].apply(lambda x: x/100 if x > 2 else x) 
        df_final["Renda Mensal Est."] = (df_final["Valor Atual"] * df_final["DY (12m)"]) / 12

        return df_final
    except Exception as e:
        st.error(f"Erro: {e}")
        return pd.DataFrame()

# --- SIDEBAR: CONSULTOR IA ---
with st.sidebar:
    st.header("🤖 Consultor IA")
    st.info("Gere um prompt detalhado com seus dados para colar no ChatGPT ou Gemini.")
    
    if st.button("🧠 Gerar Análise da Carteira"):
        st.session_state['gerar_ia'] = True
    
    if st.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()

# --- APP PRINCIPAL ---
st.title("🏢 Dashboard FIIs Pro")

df = carregar_dados()

if not df.empty:
    # LÓGICA DO CONSULTOR IA (Aparece no topo se clicado)
    if st.session_state.get('gerar_ia'):
        with st.expander("🧠 Copie este texto e cole no ChatGPT/Gemini:", expanded=True):
            # Prepara os dados resumidos para a IA não se perder
            resumo_ia = df[["Ticker", "Qtd", "Preço Médio", "Preço Atual", "P/VP", "DY (12m)"]].to_markdown(index=False)
            total_val = df["Valor Atual"].sum()
            
            prompt = f"""
Atue como um Consultor Financeiro Especialista em Fundos Imobiliários (FIIs) brasileiros.
Analise a minha carteira abaixo e me dê um feedback crítico e sugestões de otimização.

DADOS DA CARTEIRA:
Patrimônio Total: R$ {total_val:,.2f}
{resumo_ia}

PEDIDOS:
1. Analise a diversificação (risco concentrado?).
2. Identifique oportunidades (FIIs baratos com P/VP < 1.0 e bons fundamentos).
3. Identifique sinais de alerta (P/VP muito alto ou DY suspeito).
4. Sugira 3 ações práticas para melhorar a carteira.
            """
            st.code(prompt, language="text")
            st.success("Texto gerado! Copie acima (ícone no canto direito do bloco) e cole na sua IA favorita.")

    # KPI's
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    rentabilidade = (lucro / investido)
    renda_est = df["Renda Mensal Est."].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio", f"R$ {patrimonio:,.2f}")
    c2.metric("Lucro / Prejuízo", f"R$ {lucro:,.2f}", delta=f"{rentabilidade:.2%}")
    c3.metric("Renda Mensal (Est.)", f"R$ {renda_est:,.2f}")
    # Mostra o DY Médio Ponderado da carteira
    dy_medio_ponderado = (df["Renda Mensal Est."].sum() * 12) / patrimonio
    c4.metric("DY Carteira (Anual)", f"{dy_medio_ponderado:.2%}")

    st.divider()

    # GRÁFICOS
    g1, g2 = st.columns([2, 1])
    with g1:
        st.subheader("Oportunidades (P/VP x DY)")
        # Gráfico de dispersão avançado
        fig = px.scatter(df, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ticker",
                         hover_name="Ticker", text="Ticker", 
                         title="Quadrante Mágico: Busque P/VP < 1 e DY Alto")
        fig.add_hline(y=df["DY (12m)"].mean(), line_dash="dot", annotation_text="Média DY")
        fig.add_vline(x=1, line_dash="dot", annotation_text="Valor Justo")
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        st.subheader("Peso na Carteira")
        fig2 = px.pie(df, values='Valor Atual', names='Ticker', hole=0.6)
        st.plotly_chart(fig2, use_container_width=True)

    # TABELA INTERATIVA (COM LINKS!)
    st.subheader("📋 Detalhamento (Clique no Globo para ver o site)")
    
    # Configuração das Colunas Especiais
    st.dataframe(
        df,
        column_order=("Link", "Ticker", "Preço Atual", "P/VP", "DY (12m)", "Qtd", "Valor Atual", "Var %"),
        column_config={
            "Link": st.column_config.LinkColumn(
                "Site", 
                display_text="🌐", # Mostra um globo em vez da URL feia
                help="Clique para abrir no Investidor10"
            ),
            "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
            "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
            "P/VP": st.column_config.NumberColumn(format="%.2f"),
            "DY (12m)": st.column_config.NumberColumn(format="%.2%"),
            "Var %": st.column_config.NumberColumn(format="%.2%"),
        },
        hide_index=True,
        use_container_width=True
    )

else:
    st.info("Aguardando dados... Verifique a conexão com a planilha.")