import streamlit as st
import pandas as pd
import plotly.express as px
import re
import requests
from bs4 import BeautifulSoup

# ==========================================
# ⚙️ CONFIGURAÇÃO
# ==========================================
try:
    URL_FIIS = st.secrets["SHEET_URL_FIIS"]
    URL_MANUAL = st.secrets["SHEET_URL_MANUAL"]
except:
    st.error("Erro: Configure 'SHEET_URL_FIIS' e 'SHEET_URL_MANUAL' no arquivo secrets.toml")
    st.stop()

# Colunas (Mantendo sua configuração)
COL_TICKER = 0; COL_QTD = 5; COL_PRECO = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17

st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💎")

# --- REMOVI O CSS DE CARDS PARA FICAR NATIVO (SEM CONTRASTE RUIM) ---
# Apenas um ajuste fino para o tamanho das fontes
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; color: #1f77b4; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---
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

# --- CARREGAMENTO ---
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
                    # Normaliza DY (se vier 8.5 vira 0.085)
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
                        qtd = 1
                    
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
    
    # CÁLCULOS
    df["Valor Atual"] = df.apply(lambda x: x["Qtd"] * x["Preço Atual"] if x["Tipo"] in ["FII", "Ação"] else x["Preço Atual"], axis=1)
    df["Total Investido"] = df.apply(lambda x: x["Qtd"] * x["Preço Médio"] if x["Tipo"] in ["FII", "Ação"] and x["Preço Médio"] > 0 else x["Valor Atual"], axis=1)
    df["Lucro R$"] = df["Valor Atual"] - df["Total Investido"]
    
    # LIMPEZA DE DADOS (CRUCIAL PARA CORRIGIR OS PERCENTUAIS)
    # Converte tudo para número puro. Se der erro, vira 0.0
    cols_numericas = ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)"]
    for col in cols_numericas:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # Cálculo P/VP Seguro
    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    
    # Cálculo Rentabilidade Seguro
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    
    # Cálculo % Carteira Seguro
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0.0

    return df

# --- APP ---
st.title("💎 Patrimônio Global")

df = carregar_tudo()

if not df.empty:
    # --- MÉTRICAS ---
    patrimonio = df["Valor Atual"].sum()
    lucro = df["Lucro R$"].sum()
    rent_geral = lucro / df["Total Investido"].sum() if df["Total Investido"].sum() > 0 else 0
    
    df_fiis = df[df["Tipo"]=="FII"]
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio Total", f"R$ {patrimonio:,.2f}")
    c2.metric("Lucro Global", f"R$ {lucro:,.2f}", delta=f"{rent_geral:.2%}")
    c3.metric("FIIs", f"R$ {df_fiis['Valor Atual'].sum():,.2f}")
    
    # DY Médio Ponderado (Mais preciso que média simples)
    if not df_fiis.empty:
        dy_pond = (df_fiis["Valor Atual"] * df_fiis["DY (12m)"]).sum() / df_fiis["Valor Atual"].sum()
    else:
        dy_pond = 0
    c4.metric("DY Carteira (FIIs)", f"{dy_pond:.2%}")

    st.divider()

    tab_dash, tab_opp, tab_det = st.tabs(["📊 Dashboard", "🎯 Radar FIIs", "📋 Tabela Detalhada"])

    # 1. DASHBOARD
    with tab_dash:
        c_pie, c_bar = st.columns(2)
        with c_pie:
            st.subheader("Por Classe")
            fig = px.pie(df, values="Valor Atual", names="Tipo", hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)
        with c_bar:
            st.subheader("Maiores Posições")
            top = df.sort_values("Valor Atual", ascending=False).head(8)
            fig2 = px.bar(top, x="Valor Atual", y="Ativo", color="Tipo", orientation='h', text_auto='.2s')
            fig2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig2, use_container_width=True)

    # 2. RADAR OPORTUNIDADES
    with tab_opp:
        st.subheader("Quadrante Mágico (FIIs)")
        df_fii = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["Valor Atual"] > 0)].copy()
        
        if not df_fii.empty:
            mean_dy = df_fii["DY (12m)"].mean()
            fig_scat = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo")
            
            # Áreas coloridas
            # Verde: Barato e Paga bem
            fig_scat.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(0, 255, 0, 0.1)", line=dict(width=0), layer="below")
            fig_scat.add_annotation(x=0.5, y=df_fii["DY (12m)"].max(), text="OPORTUNIDADES", showarrow=False, font=dict(color="green"))
            
            # Vermelho: Caro
            fig_scat.add_shape(type="rect", x0=1.0, y0=0, x1=2.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(255, 0, 0, 0.1)", line=dict(width=0), layer="below")
            
            fig_scat.add_vline(x=1.0, line_dash="dot"); fig_scat.add_hline(y=mean_dy, line_dash="dot")
            st.plotly_chart(fig_scat, use_container_width=True)
        
        st.divider()
        st.subheader("🔥 Top Descontados (P/VP < 1.0)")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].sort_values("P/VP")
        
        if not df_radar.empty:
            st.dataframe(
                df_radar[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]],
                column_config={
                    "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "P/VP": st.column_config.NumberColumn(format="%.2f"),
                    "DY (12m)": st.column_config.NumberColumn(format="%.2%"),
                    "% Carteira": st.column_config.ProgressColumn(format="%.2%", min_value=0, max_value=1)
                },
                hide_index=True, use_container_width=True
            )
        else:
            st.info("Nenhum fundo descontado.")

    # 3. DETALHES (TABELA GERAL)
    with tab_det:
        st.subheader("Inventário")
        tipos = st.multiselect("Filtrar:", df["Tipo"].unique(), default=df["Tipo"].unique())
        df_view = df[df["Tipo"].isin(tipos)]

        st.dataframe(
            df_view,
            column_order=("Link", "Ativo", "Tipo", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira"),
            column_config={
                "Link": st.column_config.LinkColumn("", display_text="🌐", width="small"),
                "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Qtd": st.column_config.NumberColumn(format="%.0f"),
                "Var %": st.column_config.NumberColumn("Rentab.", format="%.2%"),
                "DY (12m)": st.column_config.NumberColumn("DY (12m)", format="%.2%"),
                "% Carteira": st.column_config.ProgressColumn("Peso", format="%.2%", min_value=0, max_value=1),
            },
            hide_index=True,
            use_container_width=True,
            height=600
        )

else:
    st.info("Carregando dados... Verifique a conexão com a Planilha.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Ferramentas")
    if st.button("🧠 Gerar Prompt IA"):
        st.session_state['gerar_ia'] = True
    if st.button("🔄 Atualizar"):
        st.cache_data.clear(); st.rerun()
        
    if st.session_state.get('gerar_ia'):
        st.divider()
        try:
            df_ia = df[df["Tipo"]!="Outros"][["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)"]]
            st.code(f"Analise:\n{df_ia.to_string(index=False)}", language="text")
        except: pass