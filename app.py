import streamlit as st
import pandas as pd
import plotly.express as px
import re

# ==========================================
# ⚙️ CONFIGURAÇÃO DAS COLUNAS (AJUSTE AQUI!)
# ==========================================
# Busca a URL dentro dos segredos do Streamlit
SHEET_URL = st.secrets["SHEET_URL"]

# Indique o número da coluna (A=0, B=1, C=2, D=3, E=4, ... I=8, ... R=17)
COL_TICKER = 0   # Coluna A (Onde estão os códigos)
COL_VP = 11       # Coluna B (Vem do Script)
COL_QTD = 5      # <--- AJUSTE ISTO! (Onde está a Quantidade? Ex: Coluna D = 3)
COL_PM = 9       # <--- AJUSTE ISTO! (Onde está o Preço Médio? Ex: Coluna E = 4)
COL_PRECO = 8    # Coluna I (Vem do GoogleFinance)
COL_DY = 17      # Coluna R (Vem do Script)
# ==========================================

st.set_page_config(page_title="Gestão de FIIs", layout="wide", page_icon="🏢")

# CSS para deixar elegante e esconder índices feios
st.markdown("""
<style>
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e6e6e6;
        border-radius: 8px;
        padding: 15px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    [data-testid="stMetricValue"] { font-size: 1.6rem; color: #2e3b4e; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem; color: #666; }
    div.stDataFrame { width: 100%; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def carregar_dados():
    try:
        # Lê o CSV sem cabeçalho fixo
        df = pd.read_csv(SHEET_URL, header=None)
        
        dados_limpos = []

        for index, row in df.iterrows():
            try:
                raw_ticker = str(row[COL_TICKER]).strip().upper()
                
                # Filtra apenas tickers válidos (4 letras + 11)
                if not re.match(r'^[A-Z]{4}11[B]?$', raw_ticker):
                    continue

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
                    "DY (12m)": get_float(row[COL_DY])
                }
                
                if item["Qtd"] > 0:
                    dados_limpos.append(item)

            except Exception:
                continue

        df_final = pd.DataFrame(dados_limpos)
        
        if df_final.empty: return df_final

        # --- CORREÇÃO AQUI: REMOVER DUPLICATAS ---
        # Como a quantidade é a mesma em todas as linhas, mantemos apenas a primeira.
        # Isso evita somar o patrimônio do mesmo fundo duas vezes.
        df_final = df_final.drop_duplicates(subset=["Ticker"], keep="first")

        # Cálculos (Agora feitos com a lista limpa e única)
        df_final["Total Investido"] = df_final["Qtd"] * df_final["Preço Médio"]
        df_final["Valor Atual"] = df_final["Qtd"] * df_final["Preço Atual"]
        df_final["Lucro R$"] = df_final["Valor Atual"] - df_final["Total Investido"]
        df_final["Var %"] = ((df_final["Valor Atual"] / df_final["Total Investido"]) - 1) * 100
        df_final["P/VP"] = df_final["Preço Atual"] / df_final["VP"]
        
        # Ajuste do DY
        df_final["DY (12m)"] = df_final["DY (12m)"].apply(lambda x: x/100 if x > 2 else x) 
        df_final["Renda Mensal Est."] = (df_final["Valor Atual"] * df_final["DY (12m)"]) / 12

        return df_final

    except Exception as e:
        st.error(f"Erro ao processar dados: {e}")
        return pd.DataFrame()

# --- SIDEBAR (DEBUG) ---
with st.sidebar:
    st.header("Configurações")
    if st.button("🔄 Atualizar Agora"):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    st.caption("Ferramentas de Análise")
    mostrar_tabela_raw = st.checkbox("Mostrar Tabela Completa")

# --- APP PRINCIPAL ---
st.title("🏢 Carteira Inteligente")

df = carregar_dados()

if not df.empty:
    # --- BIG NUMBERS (KPIs) ---
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    rentabilidade = (lucro / investido) * 100
    renda_est = df["Renda Mensal Est."].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio", f"R$ {patrimonio:,.2f}")
    c2.metric("Lucro / Prejuízo", f"R$ {lucro:,.2f}", delta=f"{rentabilidade:.2f}%")
    c3.metric("Custo de Aquisição", f"R$ {investido:,.2f}")
    c4.metric("Renda Mensal (Est.)", f"R$ {renda_est:,.2f}")

    st.divider()

    # --- GRÁFICOS ---
    g1, g2 = st.columns([1.5, 1])
    
    with g1:
        st.subheader("Diversificação (Por Valor)")
        fig = px.bar(df.sort_values("Valor Atual", ascending=True), 
                     x="Valor Atual", y="Ticker", orientation='h', text_auto='.2s')
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=350)
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        st.subheader("Top Renda (Estimada)")
        # Gráfico de rosca para ver quem paga mais
        fig2 = px.pie(df, values='Renda Mensal Est.', names='Ticker', hole=0.5)
        fig2.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=350, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    # --- TABELA DE OPORTUNIDADES (PVP < 1) ---
    st.subheader("🔎 Radar: Fundos Descontados (P/VP < 1.0)")
    
    # Prepara tabela bonita
    df_display = df.copy()
    colunas_visuais = ["Ticker", "Preço Atual", "VP", "P/VP", "DY (12m)", "Qtd", "Valor Atual", "Var %"]
    
    # Filtra e Ordena
    df_baratos = df_display[df_display["P/VP"] < 1.0].sort_values("P/VP")[colunas_visuais]
    
    # Formatação condicional
    st.dataframe(
        df_baratos.style.format({
            "Preço Atual": "R$ {:.2f}",
            "VP": "R$ {:.2f}",
            "P/VP": "{:.2f}",
            "Valor Atual": "R$ {:.2f}",
            "Var %": "{:.2f}%",
            "DY (12m)": "{:.2%}"
        }).background_gradient(subset=["P/VP"], cmap="Greens_r"), # Verde quanto menor o P/VP
        use_container_width=True,
        hide_index=True
    )

    # --- TABELA GERAL (Opcional) ---
    if mostrar_tabela_raw:
        st.subheader("Carteira Completa")
        st.dataframe(df_display.style.format({"Valor Atual": "R$ {:.2f}", "Total Investido": "R$ {:.2f}"}), use_container_width=True)

else:
    st.info("Nenhum dado carregado. Verifique:\n1. O Link CSV está correto?\n2. Os números das colunas (COL_QTD, COL_PM) estão configurados certos no código?")