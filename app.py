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

# Configuração inicial do Streamlit
st.set_page_config(page_title="Carteira FIIs Master", layout="wide", page_icon="🏢")

# CSS para métricas e tabelas
st.markdown("""
<style>
    .metric-card { background-color: #f9f9f9; border-radius: 8px; padding: 15px; border: 1px solid #eee; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; color: #0068c9; }
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
                    "Link": f"https://investidor10.com.br/fiis/{raw_ticker.lower()}/"
                }
                
                if item["Qtd"] > 0:
                    dados_limpos.append(item)
            except: continue

        df_final = pd.DataFrame(dados_limpos)
        if df_final.empty: return df_final

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("Ferramentas")
    if st.button("🧠 Gerar Prompt para IA"):
        st.session_state['gerar_ia'] = True
    
    st.divider()
    if st.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()

# --- APP PRINCIPAL ---
st.title("🏢 Dashboard FIIs Integrado")

df = carregar_dados()

if not df.empty:
    # --- ÁREA DE IA (Correção do Erro) ---
    if st.session_state.get('gerar_ia'):
        with st.expander("🧠 Copie para o ChatGPT/Gemini:", expanded=True):
            # Tenta usar markdown se tabulate estiver instalado, senão usa string simples
            try:
                resumo_ia = df[["Ticker", "Qtd", "Preço Médio", "Preço Atual", "P/VP", "DY (12m)"]].to_markdown(index=False)
            except ImportError:
                resumo_ia = df[["Ticker", "Qtd", "Preço Médio", "Preço Atual", "P/VP", "DY (12m)"]].to_string(index=False)
                st.warning("Dica: Adicione 'tabulate' ao requirements.txt para uma formatação melhor.")

            prompt = f"""
Atue como Consultor Financeiro. Analise minha carteira de FIIs:
Patrimônio: R$ {df["Valor Atual"].sum():,.2f}
{resumo_ia}
1. Analise a diversificação.
2. Aponte FIIs descontados (P/VP < 1) mas sólidos.
3. Sugira otimizações.
            """
            st.code(prompt, language="text")

    # --- KPIs ---
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    rentabilidade = (lucro / investido)
    renda_est = df["Renda Mensal Est."].sum()
    dy_medio_ponderado = (renda_est * 12) / patrimonio

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio", f"R$ {patrimonio:,.2f}")
    c2.metric("Lucro / Prejuízo", f"R$ {lucro:,.2f}", delta=f"{rentabilidade:.2%}")
    c3.metric("Renda Mensal (Est.)", f"R$ {renda_est:,.2f}")
    c4.metric("DY Carteira (Anual)", f"{dy_medio_ponderado:.2%}")

    st.divider()

    # --- GRÁFICOS (RESTAURADOS E NOVOS) ---
    # Usando abas para manter organizado
    tab1, tab2, tab3 = st.tabs(["📊 Alocação (Barras)", "💠 Oportunidades (Scatter)", "🍩 Distribuição (Pizza)"])

    with tab1:
        st.subheader("Quanto tenho em cada fundo?")
        # O gráfico de barras horizontal que você gostava
        fig_bar = px.bar(df.sort_values("Valor Atual", ascending=True), 
                         x="Valor Atual", y="Ticker", orientation='h', text_auto='.2s',
                         title="Patrimônio por Ativo")
        st.plotly_chart(fig_bar, use_container_width=True)

    with tab2:
        st.subheader("Quadrante Mágico: Barato vs Rentável")
        # O novo gráfico de bolhas
        fig_scat = px.scatter(df, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ticker",
                         hover_name="Ticker", text="Ticker")
        fig_scat.add_hline(y=df["DY (12m)"].mean(), line_dash="dot", annotation_text="Média DY")
        fig_scat.add_vline(x=1, line_dash="dot", annotation_text="Preço Justo")
        st.plotly_chart(fig_scat, use_container_width=True)

    with tab3:
        st.subheader("Peso na Carteira")
        fig_pie = px.pie(df, values='Valor Atual', names='Ticker', hole=0.6)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()

    # --- TABELAS ---
    
    # 1. RADAR (Restaurado e melhorado)
    st.subheader("🔎 Radar: Oportunidades (P/VP < 1.0)")
    df_baratos = df[df["P/VP"] < 1.0].sort_values("P/VP")[["Ticker", "Preço Atual", "VP", "P/VP", "DY (12m)"]]
    
    if not df_baratos.empty:
        st.dataframe(
            df_baratos.style.format({
                "Preço Atual": "R$ {:.2f}", "VP": "R$ {:.2f}", "P/VP": "{:.2f}", "DY (12m)": "{:.2%}"
            }).background_gradient(subset=["P/VP"], cmap="Greens_r"),
            use_container_width=True
        )
    else:
        st.success("Nenhum fundo descontado no momento.")

    # 2. CARTEIRA DETALHADA (Com Links)
    st.subheader("📋 Carteira Detalhada (Clique no 🌐 para abrir o site)")
    st.dataframe(
        df,
        column_order=("Link", "Ticker", "Preço Atual", "P/VP", "DY (12m)", "Qtd", "Valor Atual", "Var %"),
        column_config={
            "Link": st.column_config.LinkColumn("Site", display_text="🌐"),
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
    st.info("Aguardando dados...")