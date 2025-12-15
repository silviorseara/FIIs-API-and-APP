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
st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💠")

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
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin-bottom: 30px;
    }
    .kpi-card {
        background-color: var(--background-secondary-color);
        border: 1px solid rgba(128, 128, 128, 0.1); 
        border-radius: 16px;
        padding: 24px 16px;
        text-align: center;
        box-shadow: 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        height: 100%;
    }

    /* CARD OPORTUNIDADE */
    .opp-card {
        background: linear-gradient(135deg, rgba(20, 184, 166, 0.05) 0%, rgba(16, 185, 129, 0.1) 100%);
        border: 1px solid rgba(20, 184, 166, 0.3);
        border-radius: 16px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        height: 100%;
        display: flex; flex-direction: column; justify-content: space-between;
    }
    
    /* CARD ALERTA */
    .alert-card {
        background: linear-gradient(135deg, rgba(255, 87, 34, 0.05) 0%, rgba(255, 152, 0, 0.1) 100%);
        border: 1px solid rgba(255, 87, 34, 0.3);
        border-radius: 16px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        height: 100%;
        display: flex; flex-direction: column; justify-content: space-between;
    }

    .card-header {
        display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;
        border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px;
    }
    .card-ticker { font-size: 1.4rem; font-weight: 800; color: #333; }
    .green-t { color: #0f766e; }
    .red-t { color: #c0392b; }
    
    .card-grid {
        display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.8rem; text-align: left;
    }
    .card-item { background: rgba(255,255,255,0.6); padding: 8px; border-radius: 8px; }
    .card-label { font-size: 0.65rem; color: #666; text-transform: uppercase; margin-bottom: 2px; }
    .card-val { font-weight: 700; color: #333; font-size: 0.9rem; }
    
    .opp-footer {
        margin-top: 12px; background-color: #ccfbf1; color: #0f766e;
        padding: 8px; border-radius: 8px; font-size: 0.85rem; font-weight: 700; margin-bottom: 8px;
    }
    .alert-footer {
        margin-top: 12px; background-color: #ffccbc; color: #bf360c;
        padding: 8px; border-radius: 8px; font-size: 0.85rem; font-weight: 700; margin-bottom: 8px;
    }
    
    .kpi-label { font-size: 0.75rem; opacity: 0.7; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    .kpi-value { font-size: 1.7rem; font-weight: 700; color: var(--text-color); margin-bottom: 8px; }
    .kpi-delta { font-size: 0.75rem; font-weight: 600; padding: 4px 12px; border-radius: 20px; display: inline-block; }
    
    .pos { color: #065f46; background-color: #d1fae5; } 
    .neg { color: #991b1b; background-color: #fee2e2; } 
    .neu { color: #374151; background-color: #f3f4f6; } 
    
    .stButton button { width: 100%; border-radius: 10px; font-weight: 600; }
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

def real_br(valor):
    if not isinstance(valor, (int, float)): return valor
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def pct_br(valor):
    if not isinstance(valor, (int, float)): return valor
    return f"{valor:.2%}".replace(".", ",")

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
    
    df.replace([np.inf, -np.inf], 0.0, inplace=True)
    cols_num = ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)", "Renda Mensal", "Lucro R$", "Preço Médio"]
    for col in cols_num:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    patr = df["Valor Atual"].sum()
    df["% Carteira"] = df["Valor Atual"] / patr if patr > 0 else 0.0
    
    return df

# --- IA: ANÁLISE GERAL ---
def analisar_carteira(df):
    try:
        df_resumo = df[df["Tipo"]!="Outros"][["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)", "Var %"]].copy()
        csv_data = df_resumo.to_csv(index=False)
        prompt = f"""
        Você é um consultor financeiro sênior. Analise:
        {csv_data}
        Patrimônio: R$ {df['Valor Atual'].sum():.2f}. Investido: R$ {df['Total Investido'].sum():.2f}
        Gere Markdown curto:
        1. 📊 Diagnóstico Geral.
        2. 💎 Melhores Oportunidades.
        3. ⚠️ Riscos Imediatos.
        4. 🎯 Sugestão Prática.
        """
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
            return True, response.json()['candidates'][0]['content']['parts'][0]['text'], prompt
        else: return False, "Erro API", prompt
    except Exception as e: return False, str(e), prompt

# --- MODAL: ANÁLISE ESPECÍFICA (NOVO!) ---
@st.dialog("🤖 Análise Inteligente")
def modal_analise(ativo, tipo_analise, **kwargs):
    st.caption(f"Analisando {ativo} com {MODELO_IA}...")
    
    if tipo_analise == "compra":
        prompt = f"""
        Atue como analista. Raio-X do FII **{ativo}**.
        Preço R$ {kwargs['preco']:.2f} | P/VP {kwargs['pvp']:.2f} | DY {kwargs['dy']:.1%}.
        1. 🏢 Perfil e Gestão.
        2. 📉 Risco e Alavancagem.
        3. 💰 Valuation.
        4. ⚖️ Veredito: Compra ou Aguarda?
        """
    else: # venda
        prompt = f"""
        Analise a VENDA do FII **{ativo}**.
        Dados: PM R$ {kwargs['pm']:.2f} | Preço R$ {kwargs['preco']:.2f} | P/VP {kwargs['pvp']:.2f} | DY {kwargs['dy']:.1%}.
        Motivo Alerta: {kwargs['motivo']}.
        1. ⚠️ Diagnóstico (Por que está ruim?).
        2. 📉 Dilema (Vender ou esperar?).
        3. 🛑 Veredito (Manter ou Vender?).
        """

    if not HAS_AI:
        st.error("Sem chave de API configurada.")
        st.text_area("Prompt para copiar:", prompt)
        return

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            texto = response.json()['candidates'][0]['content']['parts'][0]['text']
            st.markdown(texto)
        else:
            st.error(f"Erro na IA ({response.status_code})")
            st.text_area("Prompt (Fallback):", prompt)
    except Exception as e:
        st.error(f"Erro de conexão: {e}")

# --- HELPER PRIVACIDADE ---
def fmt(valor, prefix="R$ ", is_pct=False):
    if st.session_state.get('privacy_mode'): return "••••••"
    if is_pct: return pct_br(valor)
    return real_br(valor)

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
        if st.button("✨ Analisar Carteira (IA)", type="primary", use_container_width=True):
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

    # --- DESTAQUE: OPORTUNIDADES ---
    media_peso = df["% Carteira"].mean()
    df_opp = df[
        (df["Tipo"] == "FII") & 
        (df["P/VP"] >= 0.80) & 
        (df["P/VP"] <= 0.90) & 
        (df["DY (12m)"] > 0.10) & 
        (df["% Carteira"] < media_peso)
    ].sort_values("P/VP", ascending=True)

    # Contador para saber se tem mais além dos 4 mostrados
    total_opp = len(df_opp)
    df_opp_view = df_opp.head(4)

    if not df_opp.empty and not st.session_state.get('privacy_mode'):
        st.subheader(f"🎯 Oportunidades ({total_opp} encontrados)")
        cols = st.columns(len(df_opp_view))
        
        for idx, row in enumerate(df_opp_view.itertuples(index=False)):
            # Cálculo seguro com getattr para evitar erro de índice
            ativo = getattr(row, "Ativo")
            preco = getattr(row, "_5") # Valor Atual (Indice 5 no itertuples padrão do pandas se não renomear, mas vamos usar logica melhor)
            # Melhor: Vamos usar os nomes das colunas direto do DF original filtrado
            
            # Recalculando variaveis para o loop (Método Seguro)
            val_atual = df_opp_view.iloc[idx]["Valor Atual"]
            peso_atual = df_opp_view.iloc[idx]["% Carteira"]
            meta_val = patrimonio * media_peso
            falta = meta_val - val_atual
            if falta < 0: falta = 0
            
            ativo_nome = df_opp_view.iloc[idx]["Ativo"]
            preco_un = df_opp_view.iloc[idx]["Preço Atual"]
            pvp_val = df_opp_view.iloc[idx]["P/VP"]
            dy_val = df_opp_view.iloc[idx]["DY (12m)"]
            
            with cols[idx]:
                st.markdown(f"""
                <div class="opp-card">
                    <div class="card-header">
                        <div class="card-ticker green-t">{ativo_nome}</div>
                        <div class="opp-price">{real_br(preco_un)}</div>
                    </div>
                    <div class="card-grid">
                        <div class="card-item"><div class="card-label">TENHO (R$)</div><div class="card-val">{real_br(val_atual)}</div></div>
                        <div class="card-item"><div class="card-label">PESO</div><div class="card-val">{pct_br(peso_atual)}</div></div>
                        <div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp_val:.2f}</div></div>
                        <div class="card-item"><div class="card-label">DY</div><div class="card-val">{pct_br(dy_val)}</div></div>
                    </div>
                    <div class="opp-footer">
                        Falta: {real_br(falta)}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # BOTÃO QUE ABRE O MODAL
                if st.button(f"✨ Analisar {ativo_nome}", key=f"btn_opp_{ativo_nome}", use_container_width=True):
                    modal_analise(ativo_nome, "compra", preco=preco_un, pvp=pvp_val, dy=dy_val)
        
        st.write("")
        st.divider()

    # --- ALERTAS DE SAÍDA ---
    media_dy = df["DY (12m)"].mean()
    df_alert = df[(df["Tipo"] == "FII") & (
        (df["P/VP"] > 1.10) | 
        (df["DY (12m)"] < (media_dy * 0.85)) | 
        ((df["P/VP"] < 0.70) & (df["DY (12m)"] < 0.08))
    )].head(4)

    if not df_alert.empty and not st.session_state.get('privacy_mode'):
        st.subheader("⚠️ Radar de Atenção (Venda?)")
        cols_al = st.columns(len(df_alert))
        
        for idx, row in enumerate(df_alert.itertuples(index=False)):
            # Dados do DF Alert
            ativo_nome = df_alert.iloc[idx]["Ativo"]
            preco_un = df_alert.iloc[idx]["Preço Atual"]
            pm_val = df_alert.iloc[idx]["Preço Médio"]
            pvp_val = df_alert.iloc[idx]["P/VP"]
            dy_val = df_alert.iloc[idx]["DY (12m)"]
            
            # Motivo
            mots = []
            if pvp_val > 1.10: mots.append("Caro")
            if dy_val < (media_dy * 0.85): mots.append("Baixo Yield")
            if pvp_val < 0.70 and dy_val < 0.08: mots.append("Armadilha?")
            motivo_txt = " + ".join(mots)

            with cols_al[idx]:
                st.markdown(f"""
                <div class="alert-card">
                    <div class="card-header">
                        <div class="card-ticker red-t">{ativo_nome}</div>
                        <div class="opp-price">{real_br(preco_un)}</div>
                    </div>
                    <div class="card-grid">
                        <div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp_val:.2f}</div></div>
                        <div class="card-item"><div class="card-label">DY</div><div class="card-val">{pct_br(dy_val)}</div></div>
                        <div class="card-item"><div class="card-label">MEU PM</div><div class="card-val">{real_br(pm_val)}</div></div>
                        <div class="card-item"><div class="card-label">ALERTA</div><div class="card-val" style="color:#d32f2f; font-size:0.7rem;">{motivo_txt}</div></div>
                    </div>
                    <div class="alert-footer">
                        Avaliar Saída?
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # BOTÃO QUE ABRE O MODAL
                if st.button(f"🔍 Analisar Venda", key=f"btn_alert_{ativo_nome}", use_container_width=True):
                    modal_analise(ativo_nome, "venda", preco=preco_un, pm=pm_val, pvp=pvp_val, dy=dy_val, motivo=motivo_txt)
        st.divider()

    # --- RESULTADO DA IA GERAL ---
    if st.session_state.get('ia_rodou'):
        c_head, c_close = st.columns([9, 1])
        with c_head: st.markdown("### ✨ Insights da Carteira")
        with c_close:
            if st.button("✕", help="Fechar"):
                st.session_state['ia_rodou'] = False
                st.rerun()
        if st.session_state['ia_sucesso']: st.info(st.session_state['ia_resultado'])
        else:
            st.warning("IA Indisponível. Copie o prompt:")
            st.text_area("Prompt:", value=st.session_state['ia_prompt'], height=150)
            st.link_button("🚀 Abrir Gemini", "https://gemini.google.com/app")
        st.divider()

    # --- ABAS ---
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão", "🎯 Matriz & Radar", "📋 Lista", "📈 Histórico"])

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
        st.subheader("🔥 Melhores Descontos")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        if not df_radar.empty:
            st.dataframe(
                df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]].style.format({
                    "Preço Atual": real_br, "Valor Atual": real_br, "P/VP": "{:.2f}",
                    "DY (12m)": pct_br, "% Carteira": pct_br
                }).background_gradient(subset=["P/VP"], cmap="RdYlGn_r"),
                use_container_width=True
            )

    with tab3:
        st.subheader("Lista Completa")
        tipos = st.multiselect("Filtrar:", df["Tipo"].unique(), default=df["Tipo"].unique())
        df_view = df[df["Tipo"].isin(tipos)].copy()
        cols_show = ["Link", "Ativo", "Tipo", "Preço Médio", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"]
        df_view = df_view[[c for c in cols_show if c in df_view.columns]]

        st.dataframe(
            df_view.style.format({
                "Preço Médio": real_br, "Preço Atual": real_br, "Valor Atual": real_br, "Renda Mensal": real_br,
                "Qtd": "{:.0f}", "Var %": pct_br, "DY (12m)": pct_br, "% Carteira": pct_br
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