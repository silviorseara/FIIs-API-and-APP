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

# --- CSS PROFISSIONAL (CARDS ALINHADOS) ---
st.markdown("""
<style>
    /* Container dos Cards */
    .kpi-container {
        display: flex;
        justify-content: space-between;
        gap: 15px;
        flex-wrap: wrap;
        margin-bottom: 20px;
    }
    
    /* O Card em si (Altura fixa para alinhar) */
    .kpi-card {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        border: 1px solid #f0f0f0;
        flex: 1; /* Cresce igualmente */
        min-width: 200px;
        height: 160px; /* ALTURA FIXA PARA ALINHAMENTO PERFEITO */
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        transition: transform 0.2s;
    }
    
    .kpi-card:hover { transform: translateY(-5px); border-color: #d1e7dd; }

    /* Tipografia do Card */
    .kpi-label { font-size: 0.9rem; color: #6c757d; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
    .kpi-value { font-size: 1.8rem; color: #2c3e50; font-weight: 800; margin: 0; }
    .kpi-delta { font-size: 0.85rem; font-weight: 600; margin-top: 8px; padding: 4px 10px; border-radius: 20px; }
    
    /* Cores de Delta */
    .positive { color: #155724; background-color: #d4edda; }
    .negative { color: #721c24; background-color: #f8d7da; }
    .neutral  { color: #383d41; background-color: #e2e3e5; }

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
    except: pass

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
    
    # Cálculos
    df["Valor Atual"] = df.apply(lambda x: x["Qtd"] * x["Preço Atual"] if x["Tipo"] in ["FII", "Ação"] else x["Preço Atual"], axis=1)
    df["Total Investido"] = df.apply(lambda x: x["Qtd"] * x["Preço Médio"] if x["Tipo"] in ["FII", "Ação"] and x["Preço Médio"] > 0 else x["Valor Atual"], axis=1)
    df["Lucro R$"] = df["Valor Atual"] - df["Total Investido"]
    
    # RENDA MENSAL (Apenas FIIs)
    # Cálculo: (Valor Atual * DY Anual) / 12
    df["Renda Mensal"] = df.apply(lambda x: (x["Valor Atual"] * x["DY (12m)"] / 12) if x["Tipo"] == "FII" else 0.0, axis=1)

    # Limpeza Final (Flags)
    cols_float = ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)", "Renda Mensal", "P/VP", "Var %"]
    # P/VP
    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    # Var %
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    
    for col in cols_float:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # % Carteira
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0.0

    return df

# --- APP ---
st.title("💎 Carteira Pro")

df = carregar_tudo()

if not df.empty:
    
    # --- CÁLCULOS DOS CARDS ---
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    
    # 1. Valorização (Lucro/Prejuizo de Capital)
    valorizacao_rs = patrimonio - investido
    valorizacao_pct = (valorizacao_rs / investido) if investido > 0 else 0
    
    # 2. Renda Mensal (Apenas FIIs)
    renda_mensal = df["Renda Mensal"].sum()
    
    # 3. FIIs vs Total
    val_fiis = df[df["Tipo"]=="FII"]["Valor Atual"].sum()

    # --- HTML DOS CARDS (GRID FLEXBOX) ---
    # Define cores e sinais
    cor_val = "positive" if valorizacao_rs >= 0 else "negative"
    sinal_val = "+" if valorizacao_rs >= 0 else ""
    
    html_cards = f"""
    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-label">Patrimônio Global</div>
            <div class="kpi-value">R$ {patrimonio:,.2f}</div>
            <div class="kpi-delta neutral">Total Acumulado</div>
        </div>
        
        <div class="kpi-card">
            <div class="kpi-label">Valorização (Capital)</div>
            <div class="kpi-value">R$ {valorizacao_rs:,.2f}</div>
            <div class="kpi-delta {cor_val}">{sinal_val}{valorizacao_pct:.2%}</div>
        </div>

        <div class="kpi-card">
            <div class="kpi-label">Renda Mensal Est.</div>
            <div class="kpi-value">R$ {renda_mensal:,.2f}</div>
            <div class="kpi-delta positive">Fluxo Passivo</div>
        </div>

        <div class="kpi-card">
            <div class="kpi-label">Total em FIIs</div>
            <div class="kpi-value">R$ {val_fiis:,.2f}</div>
            <div class="kpi-delta neutral">{val_fiis/patrimonio:.1%} da Carteira</div>
        </div>
    </div>
    """
    st.markdown(html_cards, unsafe_allow_html=True)

    # --- NAVEGAÇÃO ---
    tab_dash, tab_opp, tab_det = st.tabs(["📊 Dashboard", "🎯 Radar & Oportunidades", "📋 Inventário"])

    with tab_dash:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Distribuição por Classe")
            fig = px.sunburst(df, path=['Tipo', 'Ativo'], values='Valor Atual', color='Tipo',
                              color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("Maiores Posições")
            top = df.sort_values("Valor Atual", ascending=False).head(10)
            fig2 = px.bar(top, x="Valor Atual", y="Ativo", color="Tipo", orientation='h', text_auto='.2s',
                          color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig2, use_container_width=True)

    with tab_opp:
        st.subheader("Quadrante Mágico (FIIs)")
        
        df_fii = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["Valor Atual"] > 0)].copy()
        
        if not df_fii.empty:
            mean_dy = df_fii["DY (12m)"].mean()
            # Gráfico Bolhas
            fig = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo")
            
            # Zonas
            fig.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(0, 255, 0, 0.1)", line=dict(width=0), layer="below")
            fig.add_annotation(x=0.5, y=df_fii["DY (12m)"].max(), text="OPORTUNIDADES", showarrow=False, font=dict(color="green", weight="bold"))
            
            fig.add_shape(type="rect", x0=1.0, y0=0, x1=2.0, y1=df_fii["DY (12m)"].max()*1.1,
                               fillcolor="rgba(255, 0, 0, 0.1)", line=dict(width=0), layer="below")
            
            fig.add_vline(x=1.0, line_dash="dot")
            fig.update_layout(height=500, xaxis_title="P/VP", yaxis_title="Dividend Yield")
            st.plotly_chart(fig, use_container_width=True)
        
        st.divider()

        # HEATMAP
        st.subheader("🔥 Top Oportunidades (P/VP < 1.0)")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        
        if not df_radar.empty:
            df_radar = df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]]
            
            st.dataframe(
                df_radar.style
                .format({
                    "Preço Atual": "R$ {:.2f}", "Valor Atual": "R$ {:.2f}",
                    "P/VP": "{:.2f}", "DY (12m)": "{:.2%}", "% Carteira": "{:.2%}"
                })
                .background_gradient(subset=["P/VP"], cmap="RdYlGn_r")
                .background_gradient(subset=["DY (12m)"], cmap="Greens"),
                use_container_width=True
            )
        else:
            st.info("Nenhum fundo descontado.")

    with tab_det:
        st.subheader("Inventário Completo")
        tipos = st.multiselect("Filtrar:", df["Tipo"].unique(), default=df["Tipo"].unique())
        df_view = df[df["Tipo"].isin(tipos)]

        st.dataframe(
            df_view,
            column_order=("Link", "Ativo", "Tipo", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"),
            column_config={
                "Link": st.column_config.LinkColumn("", display_text="🌐", width="small"),
                "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Qtd": st.column_config.NumberColumn(format="%.0f"),
                "Var %": st.column_config.NumberColumn("Valoriz.", format="%.2%"),
                "DY (12m)": st.column_config.NumberColumn(format="%.2%"),
                "% Carteira": st.column_config.ProgressColumn("Peso", format="%.2%", min_value=0, max_value=1),
                "Renda Mensal": st.column_config.NumberColumn("Renda Est.", format="R$ %.2f"),
            },
            hide_index=True,
            use_container_width=True,
            height=600
        )

else:
    st.info("Carregando... Verifique seus links.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Ferramentas")
    if st.button("🧠 Prompt IA"): st.session_state['gerar_ia'] = True
    if st.button("🔄 Atualizar"): st.cache_data.clear(); st.rerun()
    if st.session_state.get('gerar_ia'):
        st.divider()
        try:
            df_ia = df[df["Tipo"]!="Outros"][["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)"]]
            st.code(f"Analise:\n{df_ia.to_string(index=False)}", language="text")
        except: pass