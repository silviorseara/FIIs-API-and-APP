import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re
import requests
from bs4 import BeautifulSoup

# ==========================================
# ⚙️ CONFIGURAÇÃO DE SEGURANÇA E COLUNAS
# ==========================================
try:
    URL_FIIS = st.secrets["SHEET_URL_FIIS"]
    URL_MANUAL = st.secrets["SHEET_URL_MANUAL"]
except:
    st.error("Erro Crítico: Configure 'SHEET_URL_FIIS' e 'SHEET_URL_MANUAL' no arquivo .streamlit/secrets.toml")
    st.stop()

# Colunas (Sua configuração)
COL_TICKER = 0; COL_QTD = 5; COL_PRECO = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17

st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💎")

# --- DESIGN MODERNO (CSS) ---
st.markdown("""
<style>
    /* Cards para Métricas */
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    /* Ajuste de fontes */
    [data-testid="stMetricValue"] { font-size: 1.6rem !important; font-weight: 700; color: #1f77b4; }
    [data-testid="stMetricLabel"] { font-size: 0.9rem !important; color: #666; }
    /* Títulos mais limpos */
    h1, h2, h3 { font-family: 'Segoe UI', sans-serif; font-weight: 600; }
    /* Abas */
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px 4px 0 0; gap: 1px; padding-top: 10px; padding-bottom: 10px; }
    .stTabs [aria-selected="true"] { background-color: #f0f2f6; border-bottom: 2px solid #1f77b4; color: #1f77b4; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES AUXILIARES ---
@st.cache_data(ttl=300)
def get_stock_price(ticker):
    try:
        url = f"https://investidor10.com.br/acoes/{ticker.lower()}/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

def to_f(x): 
    try:
        if pd.isna(x) or str(x).strip() == "": return 0.0
        return float(str(x).replace("R$","").replace("%","").replace(".","").replace(",","."))
    except: return 0.0

# --- CARREGAMENTO E NORMALIZAÇÃO ---
@st.cache_data(ttl=60)
def carregar_tudo():
    dados = []

    # 1. FIIs
    try:
        df_fiis = pd.read_csv(URL_FIIS, header=None)
        for index, row in df_fiis.iterrows():
            try:
                raw = str(row[COL_TICKER]).strip().upper()
                if not re.match(r'^[A-Z]{4}11[B]?$', raw): continue
                
                qtd = to_f(row[COL_QTD])
                if qtd > 0:
                    dy_raw = to_f(row[COL_DY])
                    # NORMALIZAÇÃO DE PERCENTUAL: Se vier 8.5 vira 0.085
                    dy_calc = dy_raw / 100 if dy_raw > 0.5 else dy_raw
                    
                    dados.append({
                        "Ativo": raw, "Tipo": "FII", "Qtd": qtd,
                        "Preço Médio": to_f(row[COL_PM]),
                        "Preço Atual": to_f(row[COL_PRECO]),
                        "VP": to_f(row[COL_VP]),
                        "DY (12m)": dy_calc,
                        "Link": f"https://investidor10.com.br/fiis/{raw.lower()}/"
                    })
            except: continue
    except Exception as e: st.error(f"Erro FIIs: {e}")

    # 2. Manual
    try:
        df_man = pd.read_csv(URL_MANUAL)
        if len(df_man.columns) >= 4:
            df_man = df_man.iloc[:, :4]
            df_man.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
            for index, row in df_man.iterrows():
                try:
                    ativo = str(row["Ativo"]).strip().upper()
                    if ativo in ["ATIVO", "TOTAL", "", "NAN"]: continue
                    tipo_raw = str(row["Tipo"]).strip().upper()
                    qtd = to_f(row["Qtd"]); val_input = to_f(row["Valor"])
                    
                    tipo = "Outros"; pm = 0.0; pa = val_input; link = None
                    if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                        tipo = "Ação"; pm = val_input
                        plive = get_stock_price(ativo)
                        pa = plive if plive > 0 else val_input
                        link = f"https://investidor10.com.br/acoes/{ativo.lower()}/"
                    else:
                        qtd = 1 # Para Outros, qtd é 1 e valor é total

                    dados.append({
                        "Ativo": ativo, "Tipo": tipo, "Qtd": qtd,
                        "Preço Médio": pm, "Preço Atual": pa,
                        "VP": 0.0, "DY (12m)": 0.0, "Link": link
                    })
                except: continue
    except: pass

    df = pd.DataFrame(dados)
    if df.empty: return df
    
    df = df.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")
    
    # Cálculos
    df["Valor Atual"] = df.apply(lambda x: x["Qtd"] * x["Preço Atual"] if x["Tipo"] in ["FII", "Ação"] else x["Preço Atual"], axis=1)
    df["Total Investido"] = df.apply(lambda x: x["Qtd"] * x["Preço Médio"] if x["Tipo"] in ["FII", "Ação"] and x["Preço Médio"] > 0 else x["Valor Atual"], axis=1)
    df["Lucro R$"] = df["Valor Atual"] - df["Total Investido"]
    
    # P/VP (Proteção contra zero)
    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    
    # Var % (Normalização)
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    
    # % Carteira
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0

    return df

# --- APP ---
st.title("💎 Patrimônio Global")

df = carregar_tudo()

if not df.empty:
    # --- HEADER MÉTRICAS ---
    patrimonio = df["Valor Atual"].sum()
    lucro = df["Lucro R$"].sum()
    rent_geral = lucro / df["Total Investido"].sum() if df["Total Investido"].sum() > 0 else 0
    
    # FIIs apenas para média de DY
    df_fiis = df[df["Tipo"]=="FII"]
    dy_medio = df_fiis["DY (12m)"].mean() if not df_fiis.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio Total", f"R$ {patrimonio:,.2f}")
    c2.metric("Resultado Global", f"R$ {lucro:,.2f}", delta=f"{rent_geral:.2%}")
    c3.metric("FIIs (Renda Variável)", f"R$ {df_fiis['Valor Atual'].sum():,.2f}")
    c4.metric("DY Médio (FIIs)", f"{dy_medio:.2%}", help="Média simples dos DYs da carteira de FIIs")

    st.divider()

    # --- NAVEGAÇÃO ---
    tab_dash, tab_opp, tab_det = st.tabs(["📊 Dashboard Visual", "🎯 Radar de Oportunidades", "📋 Detalhes & Tabela"])

    # -----------------------------------------------
    # ABA 1: DASHBOARD VISUAL
    # -----------------------------------------------
    with tab_dash:
        col_charts1, col_charts2 = st.columns([1, 1])
        
        with col_charts1:
            st.subheader("Distribuição do Patrimônio")
            fig_pie = px.sunburst(df, path=['Tipo', 'Ativo'], values='Valor Atual', 
                                  color='Tipo', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=400)
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_charts2:
            st.subheader("Maiores Posições")
            top5 = df.sort_values("Valor Atual", ascending=False).head(8)
            fig_bar = px.bar(top5, x="Valor Atual", y="Ativo", color="Tipo", 
                             orientation='h', text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, margin=dict(t=0, l=0, r=0, b=0), height=400)
            st.plotly_chart(fig_bar, use_container_width=True)

    # -----------------------------------------------
    # ABA 2: RADAR DE OPORTUNIDADES (VISUAL MELHORADO)
    # -----------------------------------------------
    with tab_opp:
        st.subheader("💠 Quadrante Mágico de FIIs")
        
        # Filtra apenas FIIs com dados válidos
        df_scatter = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["P/VP"] < 2.0)].copy()
        
        if not df_scatter.empty:
            mean_dy = df_scatter["DY (12m)"].mean()
            
            # Criação do Gráfico com ZONAS COLORIDAS
            fig = px.scatter(df_scatter, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo",
                             text="Ativo", hover_data=["Preço Atual"], template="plotly_white")
            
            # Adicionar Zonas (Retângulos)
            # 1. ZONA VERDE (Oportunidades): P/VP < 1.0 e DY > Média
            fig.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_scatter["DY (12m)"].max()*1.1,
                          fillcolor="rgba(0, 200, 83, 0.1)", line=dict(width=0), layer="below")
            fig.add_annotation(x=0.5, y=df_scatter["DY (12m)"].max(), text="🚀 OPORTUNIDADES", showarrow=False, font=dict(color="green", size=14, weight="bold"))

            # 2. ZONA AMARELA (Descontados mas rendem pouco): P/VP < 1.0 e DY < Média
            fig.add_shape(type="rect", x0=0, y0=0, x1=1.0, y1=mean_dy,
                          fillcolor="rgba(255, 193, 7, 0.1)", line=dict(width=0), layer="below")
            
            # 3. ZONA VERMELHA (Caros): P/VP > 1.0
            fig.add_shape(type="rect", x0=1.0, y0=0, x1=2.0, y1=df_scatter["DY (12m)"].max()*1.1,
                          fillcolor="rgba(255, 82, 82, 0.1)", line=dict(width=0), layer="below")
            fig.add_annotation(x=1.3, y=mean_dy, text="⚠️ CAROS / ÁGIO", showarrow=False, font=dict(color="red", size=12))

            # Linhas de referência
            fig.add_vline(x=1.0, line_dash="dash", line_color="gray", annotation_text="Valor Justo")
            fig.add_hline(y=mean_dy, line_dash="dash", line_color="gray", annotation_text="Média DY")

            fig.update_traces(textposition='top center')
            fig.update_layout(xaxis_title="P/VP (Quanto menor, mais barato)", yaxis_title="Dividend Yield (Quanto maior, melhor)", showlegend=False, height=500)
            
            st.plotly_chart(fig, use_container_width=True)
            st.caption("💡 **Dica:** Os melhores fundos estão na área **Verde** (Baratos e Pagam Bem). Evite a área **Vermelha**.")

        st.divider()

        # TABELA VISUAL (HEATMAP)
        st.subheader("🔥 Radar de Preço (P/VP < 1.0)")
        
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        
        if not df_radar.empty:
            # Seleciona colunas e formata para % legível no Pandas
            df_radar = df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]]
            
            # Aplica gradiente de cores (Visual rico que você pediu)
            st.dataframe(
                df_radar.style
                .format({
                    "Preço Atual": "R$ {:.2f}",
                    "Valor Atual": "R$ {:.2f}",
                    "P/VP": "{:.2f}",
                    "DY (12m)": "{:.2%}",      # Formatação corrigida aqui
                    "% Carteira": "{:.2%}"     # Formatação corrigida aqui
                })
                .background_gradient(subset=["P/VP"], cmap="RdYlGn_r") # Verde para P/VP baixo
                .background_gradient(subset=["DY (12m)"], cmap="Greens"), # Verde para DY alto
                use_container_width=True,
                height=400
            )
        else:
            st.success("Sua carteira não possui FIIs descontados (P/VP < 1) no momento.")

    # -----------------------------------------------
    # ABA 3: DETALHES GERAIS
    # -----------------------------------------------
    with tab_det:
        st.subheader("📋 Inventário Completo")
        
        # Filtros
        tipos = st.multiselect("Filtrar Tipo:", df["Tipo"].unique(), default=df["Tipo"].unique())
        df_filt = df[df["Tipo"].isin(tipos)]

        # Tabela com Column Config (Barras de progresso e Links)
        st.dataframe(
            df_filt,
            column_order=("Link", "Ativo", "Tipo", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira"),
            column_config={
                "Link": st.column_config.LinkColumn("", display_text="🌐", width="small"),
                "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Qtd": st.column_config.NumberColumn(format="%.0f"),
                "Var %": st.column_config.NumberColumn("Rentab.", format="%.2%"), # Corrigido
                "DY (12m)": st.column_config.NumberColumn("DY (12m)", format="%.2%"), # Corrigido
                "% Carteira": st.column_config.ProgressColumn(
                    "% Carteira", 
                    format="%.2%", 
                    min_value=0, 
                    max_value=1
                ),
            },
            hide_index=True,
            use_container_width=True,
            height=600
        )

else:
    st.info("Carregando dados... Se demorar, verifique se a planilha está acessível.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Ferramentas")
    if st.button("🧠 Gerar Prompt IA"):
        st.session_state['gerar_ia'] = True
    if st.button("🔄 Atualizar"):
        st.cache_data.clear(); st.rerun()
        
    if st.session_state.get('gerar_ia'):
        st.divider()
        st.write("Copie para a IA:")
        try:
            # Prepara dados para o prompt
            df_ia = df[df["Tipo"]!="Outros"][["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)"]]
            txt = df_ia.to_string(index=False)
            st.code(f"Analise esta carteira de FIIs/Ações:\n{txt}\n1. Oportunidades?\n2. Riscos?", language="text")
        except: pass