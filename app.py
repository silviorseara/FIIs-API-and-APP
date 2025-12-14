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

# Colunas
COL_TICKER = 0; COL_QTD = 5; COL_PRECO = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17

st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💎")

# --- CSS PARA METRICAS MODERNAS ---
st.markdown("""
<style>
    /* Estilo dos Cards de Métricas */
    div[data-testid="stMetric"] {
        background-color: #ffffff; /* Fundo sempre branco */
        border: 1px solid #e6e6e6;
        padding: 15px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700;
        color: #0068c9;
    }
    [data-testid="stMetricLabel"] {
        font-weight: 500;
        color: #444;
    }
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
    """Converte qualquer bagunça para float puro"""
    try:
        if pd.isna(x) or str(x).strip() == "": return 0.0
        # Remove tudo que não for numero, ponto ou virgula
        clean = str(x).replace("R$", "").replace("%", "").replace(" ", "")
        # Troca virgula por ponto para o Python entender
        clean = clean.replace(".", "").replace(",", ".")
        return float(clean)
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
                    # Tratamento especial para DY
                    dy_raw = to_f(row[COL_DY])
                    # Se vier > 1 (ex: 12.5), divide por 100. Se vier < 1 (ex: 0.125), mantem.
                    dy_calc = dy_raw / 100 if dy_raw > 1.0 else dy_raw
                    
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
    
    # CÁLCULO P/VP
    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    
    # CÁLCULO VARIAÇÃO % (Rentabilidade)
    # Se Total Investido for 0, retorna 0.0 para não quebrar
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    
    # CÁLCULO % CARTEIRA
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0.0

    # --- LIMPEZA NUCLEAR (SANITIZAÇÃO) ---
    # Isso garante que o Streamlit não mostre a bandeira vermelha
    cols_float = ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)", "Preço Médio", "Qtd", "Var %", "P/VP", "% Carteira"]
    for col in cols_float:
        # Força conversão para numérico, erros viram NaN, NaN vira 0.0
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

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
    
    if not df_fiis.empty:
        dy_pond = (df_fiis["Valor Atual"] * df_fiis["DY (12m)"]).sum() / df_fiis["Valor Atual"].sum()
    else: dy_pond = 0
    c4.metric("DY Carteira (FIIs)", f"{dy_pond:.2%}")

    st.divider()

    tab_dash, tab_opp, tab_det = st.tabs(["📊 Dashboard", "🎯 Radar Colorido", "📋 Inventário Completo"])

    # 1. DASHBOARD
    with tab_dash:
        c_pie, c_bar = st.columns(2)
        with c_pie:
            st.subheader("Por Classe")
            fig = px.sunburst(df, path=['Tipo', 'Ativo'], values='Valor Atual', color='Tipo',
                              color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)
        with c_bar:
            st.subheader("Maiores Posições")
            top = df.sort_values("Valor Atual", ascending=False).head(10)
            fig2 = px.bar(top, x="Valor Atual", y="Ativo", color="Tipo", orientation='h', text_auto='.2s',
                          color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig2, use_container_width=True)

    # 2. RADAR OPORTUNIDADES
    with tab_opp:
        st.subheader("Quadrante Mágico (FIIs)")
        
        df_fii = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["Valor Atual"] > 0)].copy()
        
        if not df_fii.empty:
            mean_dy = df_fii["DY (12m)"].mean()
            fig_scat = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo")
            
            # Zonas Coloridas
            fig_scat.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(0, 255, 0, 0.1)", line=dict(width=0), layer="below")
            fig_scat.add_annotation(x=0.5, y=df_fii["DY (12m)"].max(), text="OPORTUNIDADES", showarrow=False, font=dict(color="green", weight="bold"))
            
            fig_scat.add_shape(type="rect", x0=1.0, y0=0, x1=2.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(255, 0, 0, 0.1)", line=dict(width=0), layer="below")
            fig_scat.add_annotation(x=1.5, y=mean_dy, text="CAROS", showarrow=False, font=dict(color="red"))
            
            fig_scat.add_vline(x=1.0, line_dash="dot")
            st.plotly_chart(fig_scat, use_container_width=True)
        
        st.divider()

        st.subheader("🔥 Mapa de Calor (P/VP < 1.0)")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        
        if not df_radar.empty:
            df_radar = df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]]
            
            st.dataframe(
                df_radar.style
                .format({
                    "Preço Atual": "R$ {:.2f}", "Valor Atual": "R$ {:.2f}",
                    "P/VP": "{:.2f}", 
                    "DY (12m)": "{:.2%}",      # Agora funciona! (0.10 vira 10.00%)
                    "% Carteira": "{:.2%}"     # Agora funciona!
                })
                .background_gradient(subset=["P/VP"], cmap="RdYlGn_r")
                .background_gradient(subset=["DY (12m)"], cmap="Greens"),
                use_container_width=True
            )
        else:
            st.info("Nenhum fundo barato encontrado.")

    # 3. INVENTÁRIO COMPLETO (Corrigido)
    with tab_det:
        st.subheader("Inventário Completo")
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
                # Formatadores Streamlit (x100 automático se o dado for float puro)
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