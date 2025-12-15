import streamlit as st
import pandas as pd
import plotly.express as px
import re
import requests
import json
import numpy as np
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# ==========================================
# ⚙️ CONFIGURAÇÃO
# ==========================================
st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💎")

# Modelo IA
MODELO_IA = "gemini-2.5-flash-lite"

try:
    URL_FIIS = st.secrets["SHEET_URL_FIIS"]
    URL_MANUAL = st.secrets["SHEET_URL_MANUAL"]
    
    if "LINK_PLANILHA" in st.secrets:
        URL_EDIT = st.secrets["LINK_PLANILHA"]
    else:
        URL_EDIT = None

    if "GOOGLE_API_KEY" in st.secrets:
        API_KEY = st.secrets["GOOGLE_API_KEY"]
        HAS_AI = True
    else:
        HAS_AI = False
except:
    st.error("Erro: Configure URLs e GOOGLE_API_KEY no secrets.toml")
    st.stop()

# Colunas
COL_TICKER = 0; COL_QTD = 5; COL_PRECO = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17

# --- CSS ---
st.markdown("""
<style>
    /* Grid Principal */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 30px;
    }
    
    /* Card Padrão */
    .kpi-card {
        background-color: var(--background-secondary-color);
        border: 1px solid var(--text-color-20);
        border-radius: 16px;
        padding: 20px 10px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.04);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        height: 100%;
        transition: transform 0.2s;
    }
    .kpi-card:hover { transform: translateY(-2px); }

    /* Card de Oportunidade (Destaque) */
    .opp-card {
        background: linear-gradient(135deg, rgba(6, 95, 70, 0.05) 0%, rgba(16, 185, 129, 0.1) 100%);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-radius: 12px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    
    .kpi-label { font-size: 0.75rem; opacity: 0.7; margin-bottom: 5px; text-transform: uppercase; font-weight: 600; letter-spacing: 0.5px;}
    .kpi-value { font-size: 1.5rem; font-weight: 800; color: #1f77b4; margin-bottom: 5px; }
    
    .opp-ticker { font-size: 1.4rem; font-weight: 900; color: #065f46; margin-bottom: 5px; }
    .opp-stats { font-size: 0.85rem; color: #374151; font-weight: 500; display: flex; justify-content: space-around; width: 100%; margin-top: 5px; }
    .opp-badge { background-color: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: bold; margin-bottom: 8px;}

    .stButton button { width: 100%; border-radius: 8px; font-weight: bold; }
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
        return float(str(x).replace("R$","").replace("%","").replace(" ", "").replace(".","").replace(",", "."))
    except: return 0.0

@st.cache_data(ttl=3600)
def obter_historico(tickers, periodo="6mo"):
    if not tickers: return pd.DataFrame()
    tickers_sa = [f"{t}.SA" if not t.endswith(".SA") else t for t in tickers]
    try:
        dados = yf.download(tickers_sa, period=periodo, progress=False)['Close']
        if isinstance(dados, pd.Series):
            dados = dados.to_frame(); dados.columns = tickers_sa
        dados.columns = [c.replace(".SA", "") for c in dados.columns]
        dados.dropna(axis=1, how='all', inplace=True)
        return dados
    except: return pd.DataFrame()

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
                    dy_calc = dy_raw / 100 if dy_raw > 2.0 else dy_raw
                    dados.append({
                        "Ativo": raw, "Tipo": "FII", "Qtd": qtd,
                        "Preço Médio": to_f(row[COL_PM]), "Preço Atual": to_f(row[COL_PRECO]),
                        "VP": to_f(row[COL_VP]), "DY (12m)": dy_calc,
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
                    else: qtd = 1
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
    df["Renda Mensal"] = df.apply(lambda x: (x["Valor Atual"] * x["DY (12m)"] / 12) if x["Tipo"] == "FII" else 0.0, axis=1)
    
    # Limpeza
    df.replace([np.inf, -np.inf], 0.0, inplace=True)
    cols_num = ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)", "Renda Mensal", "Lucro R$"]
    for col in cols_num:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0.0
    
    return df

# --- FUNÇÃO IA ---
def analisar_carteira(df):
    try:
        df_resumo = df[df["Tipo"]!="Outros"][["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)", "Var %"]].copy()
        csv_data = df_resumo.to_csv(index=False)
        prompt = f"""
        Você é um consultor financeiro sênior (foco: FIIs e Ações Brasil).
        Analise a carteira abaixo com rigor técnico e brevidade.
        DADOS:
        {csv_data}
        Patrimônio Total: R$ {df['Valor Atual'].sum():.2f}
        Total Investido: R$ {df['Total Investido'].sum():.2f}
        
        ENTREGÁVEL (Use Markdown e Emojis):
        1. 📊 **Diagnóstico:** Diversificação, Risco e Rentabilidade.
        2. 💎 **Oportunidades:** FIIs com P/VP < 1.0, DY > 10% e vacância controlada.
        3. ⚠️ **Pontos de Atenção:** Ativos com P/VP > 1.10 ou fundamentos ruins.
        4. 🎯 **Ação:** Onde alocar o próximo aporte?
        """
    except Exception as e: return False, "Erro dados", ""

    if not HAS_AI: return False, "Sem Chave API", prompt
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            return True, response.json()['candidates'][0]['content']['parts'][0]['text'], prompt
        else: return False, "Erro API", prompt
    except Exception as e: return False, str(e), prompt

# --- HELPER DE PRIVACIDADE ---
def fmt(valor, prefix="R$ ", is_pct=False):
    if st.session_state.get('privacy_mode'): return "••••••"
    if is_pct: return f"{valor:.2%}" if isinstance(valor, (int, float)) else valor
    return f"{prefix}{valor:,.2f}" if isinstance(valor, (int, float)) else valor

# --- LAYOUT PRINCIPAL ---
c_top1, c_top2 = st.columns([6, 1])
with c_top1: st.markdown("## 💠 Carteira Pro")
with c_top2: 
    if st.button("↻ Atualizar"): st.cache_data.clear(); st.rerun()

df = carregar_tudo()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Ferramentas")
    if URL_EDIT: st.link_button("🔗 Planilha Fonte", URL_EDIT)
    else: st.caption("Sem link.")
    st.divider()
    if 'privacy_mode' not in st.session_state: st.session_state['privacy_mode'] = False
    p_label = "🔒 Privacidade Ativa" if st.session_state['privacy_mode'] else "🔓 Privacidade Inativa"
    st.session_state['privacy_mode'] = st.toggle(p_label, value=st.session_state['privacy_mode'])
    st.divider()
    if not df.empty:
        if st.button("✨ Analisar com IA", type="primary", use_container_width=True):
            with st.spinner(f"Consultando {MODELO_IA}..."):
                sucesso, resultado, prompt_usado = analisar_carteira(df)
                st.session_state['ia_rodou'] = True
                st.session_state['ia_sucesso'] = sucesso
                st.session_state['ia_resultado'] = resultado
                st.session_state['ia_prompt'] = prompt_usado

if not df.empty:
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    val_rs = patrimonio - investido
    val_pct = val_rs / investido if investido > 0 else 0
    renda = df["Renda Mensal"].sum()
    fiis_total = df[df["Tipo"]=="FII"]["Valor Atual"].sum()
    cls_val = "pos" if val_rs >= 0 else "neg"
    sinal = "+" if val_rs >= 0 else ""

    # --- 5 CARDS PRINCIPAIS ---
    st.markdown(f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Patrimônio</div>
            <div class="kpi-value">{fmt(patrimonio)}</div>
            <div class="kpi-delta neu">Total</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Investido</div>
            <div class="kpi-value">{fmt(investido)}</div>
            <div class="kpi-delta neu">Custo</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Valorização</div>
            <div class="kpi-value">{fmt(val_rs)}</div>
            <div class="kpi-delta {cls_val}">{sinal}{fmt(val_pct, "", True)}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Renda Mensal</div>
            <div class="kpi-value">{fmt(renda)}</div>
            <div class="kpi-delta pos">Dividendos</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">FIIs</div>
            <div class="kpi-value">{fmt(fiis_total)}</div>
            <div class="kpi-delta neu">{fmt(fiis_total/patrimonio if patrimonio>0 else 0, "", True)} Carteira</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- DESTAQUE: OPORTUNIDADES (NOVO BLOCO) ---
    # Critérios: FII, 0.8 <= P/VP <= 0.9, DY > 10%, Peso < Média
    media_peso = df["% Carteira"].mean()
    
    df_opp = df[
        (df["Tipo"] == "FII") & 
        (df["P/VP"] >= 0.80) & 
        (df["P/VP"] <= 0.90) & 
        (df["DY (12m)"] > 0.10) & 
        (df["% Carteira"] < media_peso)
    ].sort_values("P/VP", ascending=True).head(4) # Top 4

    if not df_opp.empty and not st.session_state.get('privacy_mode'):
        st.subheader("🎯 Oportunidades de Aporte")
        cols = st.columns(len(df_opp))
        for idx, row in enumerate(df_opp.itertuples()):
            with cols[idx]:
                st.markdown(f"""
                <div class="opp-card">
                    <div class="opp-badge">💎 Oportunidade</div>
                    <div class="opp-ticker">{row.Ativo}</div>
                    <div class="opp-stats">
                        <span>P/VP: <b>{row._7:.2f}</b></span>
                        <span>DY: <b>{row._8:.1%}</b></span>
                    </div>
                    <div style="font-size: 0.8rem; margin-top: 5px; color: #666;">
                        Preço: R$ {row._5:.2f}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        st.write("") # Espaço
        st.divider()

    # --- RESULTADO DA IA ---
    if st.session_state.get('ia_rodou'):
        c_head, c_close = st.columns([9, 1])
        with c_head: st.markdown("### ✨ Insights da IA")
        with c_close:
            if st.button("✕", help="Fechar"):
                st.session_state['ia_rodou'] = False
                st.rerun()
        
        if st.session_state['ia_sucesso']: st.info(st.session_state['ia_resultado'])
        else:
            st.warning("IA Indisponível. Copie o prompt:")
            c1, c2 = st.columns([3, 1])
            with c1: st.text_area("Prompt:", value=st.session_state['ia_prompt'], height=150)
            with c2: 
                st.write(""); st.write("")
                st.link_button("🚀 Abrir Gemini", "https://gemini.google.com/app", use_container_width=True)
        st.divider()

    # --- ABAS ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão", "🎯 Matriz & Radar", "📋 Inventário", "📈 Histórico"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.sunburst(df, path=['Tipo', 'Ativo'], values='Valor Atual', color='Tipo', color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            top = df.sort_values("Valor Atual", ascending=False).head(10)
            fig2 = px.bar(top, x="Valor Atual", y="Ativo", color="Tipo", orientation='h', text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        st.subheader("Matriz de Valor (FIIs)")
        df_fii = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["Valor Atual"] > 0)].copy()
        if not df_fii.empty:
            mean_dy = df_fii["DY (12m)"].mean()
            fig = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo", hover_data=["Preço Atual"], template="plotly_white")
            fig.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1, fillcolor="rgba(0, 200, 83, 0.1)", line=dict(width=0), layer="below")
            fig.add_vline(x=1.0, line_dash="dot", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)
        st.divider()
        st.subheader("🔥 Top Melhores Métricas")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        if not df_radar.empty:
            st.dataframe(
                df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]].style.format({
                    "Preço Atual": "R$ {:.2f}", "Valor Atual": "R$ {:.2f}", "P/VP": "{:.2f}",
                    "DY (12m)": "{:.2%}", "% Carteira": "{:.2%}"
                }).background_gradient(subset=["P/VP"], cmap="RdYlGn_r"),
                use_container_width=True
            )

    with tab3:
        st.subheader("Inventário Completo")
        tipos = st.multiselect("Filtrar:", df["Tipo"].unique(), default=df["Tipo"].unique())
        df_view = df[df["Tipo"].isin(tipos)].copy()
        cols_show = ["Link", "Ativo", "Tipo", "Preço Médio", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"]
        df_view = df_view[[c for c in cols_show if c in df_view.columns]]

        st.dataframe(
            df_view.style.format({
                "Preço Médio": "R$ {:.2f}", "Preço Atual": "R$ {:.2f}", "Valor Atual": "R$ {:.2f}", "Renda Mensal": "R$ {:.2f}",
                "Qtd": "{:.0f}", "Var %": "{:.2%}", "DY (12m)": "{:.2%}", "% Carteira": "{:.2%}"
            }).background_gradient(subset=["Var %"], cmap="RdYlGn", vmin=-0.5, vmax=0.5).background_gradient(subset=["DY (12m)"], cmap="Greens"),
            column_order=cols_show,
            column_config={
                "Link": st.column_config.LinkColumn("", display_text="🔗", width="small"),
                "% Carteira": st.column_config.ProgressColumn("Peso", format="%.2%", min_value=0, max_value=1),
            },
            hide_index=True, use_container_width=True, height=600
        )

    with tab4:
        st.subheader("📈 Tendência")
        ativos_bolsa = df[df["Tipo"].isin(["FII", "Ação"])]["Ativo"].tolist()
        if ativos_bolsa:
            c1, c2 = st.columns([3, 1])
            with c1:
                top_5 = df.sort_values("Valor Atual", ascending=False).head(5)["Ativo"].tolist()
                sel = st.multiselect("Ativos:", ativos_bolsa, default=top_5)
            with c2: per = st.selectbox("Prazo:", ["1mo", "6mo", "1y", "5y"], index=1)
            
            if sel:
                with st.spinner("Carregando..."):
                    hist = obter_historico(sel, per)
                if not hist.empty:
                    st.line_chart((hist / hist.iloc[0] - 1) * 100)
        else: st.info("Sem dados.")

else:
    st.info("Carregando... Verifique seus links.")