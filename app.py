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
from youtubesearchpython import VideosSearch

# ==========================================
# ⚙️ CONFIGURAÇÃO
# ==========================================
st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💠")

MODELO_IA = "gemini-2.5-flash-lite"

# Mapeamento de Colunas (Excel -> Python Index)
COL_TICKER = 0
COL_QTD = 5
COL_PRECO = 8
COL_PM = 9
COL_VP = 11
COL_DY = 17
COL_DATA_COM = 19
COL_SETOR = 24

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

# --- CSS REFINADO ---
st.markdown("""
<style>
    /* Grid */
    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
    
    /* Cards KPI */
    .kpi-card { background-color: var(--background-secondary-color); border: 1px solid rgba(128, 128, 128, 0.1); border-radius: 16px; padding: 24px 16px; text-align: center; box-shadow: 0 4px 6px -2px rgba(0, 0, 0, 0.05); height: 100%; display: flex; flex-direction: column; justify-content: center; }
    
    /* CARD OPORTUNIDADE (Visual Limpo para integrar com botão) */
    .opp-card {
        background: linear-gradient(135deg, rgba(20, 184, 166, 0.05) 0%, rgba(16, 185, 129, 0.1) 100%);
        border: 1px solid rgba(20, 184, 166, 0.3);
        border-radius: 16px; /* Borda arredondada completa */
        padding: 16px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        height: 100%;
        display: flex; flex-direction: column; justify-content: space-between;
        margin-bottom: 10px; /* Espaço para o botão abaixo */
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
        margin-bottom: 10px;
    }

    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px; }
    .card-ticker { font-size: 1.4rem; font-weight: 800; color: #333; }
    .green-t { color: #0f766e; } .red-t { color: #c0392b; }
    
    .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.8rem; text-align: left; }
    .card-item { background: rgba(255,255,255,0.6); padding: 8px; border-radius: 8px; }
    .card-label { font-size: 0.65rem; color: #666; text-transform: uppercase; margin-bottom: 2px; }
    .card-val { font-weight: 700; color: #333; font-size: 0.9rem; }
    
    /* Footer Informativo (Tag visual apenas) */
    .opp-footer { margin-top: 12px; background-color: #ccfbf1; color: #0f766e; padding: 6px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }
    .alert-footer { margin-top: 12px; background-color: #ffccbc; color: #bf360c; padding: 6px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }

    .kpi-label { font-size: 0.75rem; opacity: 0.7; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    .kpi-value { font-size: 1.7rem; font-weight: 700; color: var(--text-color); margin-bottom: 5px; }
    .kpi-delta { font-size: 0.75rem; font-weight: 600; padding: 4px 12px; border-radius: 20px; display: inline-block; }
    .pos { color: #065f46; background-color: #d1fae5; } .neg { color: #991b1b; background-color: #fee2e2; } .neu { color: #374151; background-color: #f3f4f6; }
    
    /* Botões Full Width */
    .stButton button { width: 100%; border-radius: 10px; font-weight: 600; height: 40px; }
    
    /* Barra de Progresso */
    .stProgress > div > div > div > div { background-color: #0f766e; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---
def real_br(valor): return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(valor, (int, float)) else valor
def pct_br(valor): return f"{valor:.2%}".replace(".", ",") if isinstance(valor, (int, float)) else valor
def to_f(x): 
    try: return float(str(x).replace("R$","").replace("%","").replace(" ", "").replace(".","").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

@st.cache_data(ttl=86400)
def get_ipca_acumulado_12m():
    try:
        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados/ultimos/12?formato=json"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            dados = resp.json(); acumulado = 1.0
            for item in dados: acumulado *= (1 + float(item['valor'])/100)
            return acumulado - 1
    except: pass
    return 0.045

@st.cache_data(ttl=300)
def get_stock_price(ticker):
    try:
        url = f"https://investidor10.com.br/acoes/{ticker.lower()}/"; headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

@st.cache_data(ttl=3600)
def obter_historico(tickers, periodo="6mo", benchmark="^BVSP"):
    if not tickers: return pd.DataFrame()
    # Adiciona Benchmark
    tickers_sa = [f"{t}.SA" if not t.endswith(".SA") else t for t in tickers]
    
    # Define o ticker do benchmark
    bench_ticker = "^BVSP" if benchmark == "IBOV" else "IFIX.SA"
    tickers_sa.append(bench_ticker)
    
    try:
        dados = yf.download(tickers_sa, period=periodo, progress=False)['Close']
        if isinstance(dados, pd.Series): dados = dados.to_frame(); dados.columns = tickers_sa
        
        # Limpeza de nomes
        cols_new = []
        for c in dados.columns:
            if c == "^BVSP": cols_new.append("IBOVESPA")
            elif c == "IFIX.SA": cols_new.append("IFIX")
            else: cols_new.append(c.replace(".SA", ""))
        dados.columns = cols_new
        
        dados.dropna(axis=1, how='all', inplace=True)
        return dados
    except: return pd.DataFrame()

@st.cache_data(ttl=86400)
def buscar_video(ticker):
    try:
        videosSearch = VideosSearch(f'Análise FII {ticker} vale a pena', limit = 1)
        res = videosSearch.result()
        if res and 'result' in res and len(res['result']) > 0:
            v = res['result'][0]
            return { 'link': v['link'], 'title': v['title'], 'channel': v['channel']['name'], 'views': v.get('viewCount', {}).get('short', '') }
    except: pass
    return None

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
                    dy_calc = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                    
                    # Leitura SEGURA da coluna Setor
                    try:
                        setor = str(row[COL_SETOR]).strip()
                        if setor == "" or setor.lower() == "nan": setor = "Indefinido"
                    except: setor = "Indefinido"
                    
                    try:
                        data_com = str(row[COL_DATA_COM]).strip()
                    except: data_com = "-"
                    
                    dados.append({
                        "Ativo": raw, "Tipo": "FII", "Setor": setor, "Qtd": qtd,
                        "Preço Médio": to_f(row[COL_PM]), "Preço Atual": to_f(row[COL_PRECO]),
                        "VP": to_f(row[COL_VP]), "DY (12m)": dy_calc, "Data Com": data_com,
                        "Link": f"https://investidor10.com.br/fiis/{raw.lower()}/"
                    })
            except: continue
    except: pass

    # 2. Manual
    try:
        df_man = pd.read_csv(URL_MANUAL)
        if len(df_man.columns) >= 4:
            df_man = df_man.iloc[:, :4]; df_man.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
            for index, row in df_man.iterrows():
                try:
                    ativo = str(row["Ativo"]).strip().upper()
                    if ativo in ["ATIVO", "TOTAL", "", "NAN"]: continue
                    tipo_raw = str(row["Tipo"]).strip().upper()
                    qtd = to_f(row["Qtd"]); val_input = to_f(row["Valor"])
                    tipo = "Outros"; pm = 0.0; pa = val_input; link = None; setor="Ação/Outros"; dcom="-"
                    if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                        tipo = "Ação"; pm = val_input
                        plive = get_stock_price(ativo); pa = plive if plive > 0 else val_input
                        link = f"https://investidor10.com.br/acoes/{ativo.lower()}/"
                        setor = "Ações"
                    else: qtd = 1
                    dados.append({
                        "Ativo": ativo, "Tipo": tipo, "Setor": setor, "Qtd": qtd,
                        "Preço Médio": pm, "Preço Atual": pa, "VP": 0.0, "DY (12m)": 0.0, 
                        "Data Com": dcom, "Link": link
                    })
                except: continue
    except: pass

    df = pd.DataFrame(dados)
    if df.empty: return df
    df = df.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")
    
    df["Valor Atual"] = df.apply(lambda x: x["Qtd"] * x["Preço Atual"] if x["Tipo"] in ["FII", "Ação"] else x["Preço Atual"], axis=1)
    df["Total Investido"] = df.apply(lambda x: x["Qtd"] * x["Preço Médio"] if x["Tipo"] in ["FII", "Ação"] and x["Preço Médio"] > 0 else x["Valor Atual"], axis=1)
    df["Lucro R$"] = df["Valor Atual"] - df["Total Investido"]
    df["Renda Mensal"] = df.apply(lambda x: (x["Valor Atual"] * x["DY (12m)"] / 12) if x["Tipo"] == "FII" else 0.0, axis=1)
    
    df.replace([np.inf, -np.inf], 0.0, inplace=True)
    for col in ["Valor Atual", "Total Investido", "Preço Atual", "VP", "DY (12m)", "Renda Mensal", "Lucro R$", "Preço Médio"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    df["Var %"] = df.apply(lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, axis=1)
    df["% Carteira"] = df["Valor Atual"] / df["Valor Atual"].sum() if df["Valor Atual"].sum() > 0 else 0.0
    return df

@st.dialog("🤖 Análise Inteligente", width="large")
def modal_analise(ativo, tipo_analise, **kwargs):
    st.empty()
    if tipo_analise == "compra":
        prompt = f"Analise FII **{ativo}** para COMPRA.\nPreço R$ {kwargs['preco']:.2f} | P/VP {kwargs['pvp']:.2f} | DY {kwargs['dy']:.1%}.\n1.Perfil/Gestão\n2.Risco/Alavancagem\n3.Valuation\n4.Veredito(Compra/Aguarda)."
    else:
        prompt = f"Analise VENDA FII **{ativo}**.\nPM R$ {kwargs['pm']:.2f} | Preço R$ {kwargs['preco']:.2f} | P/VP {kwargs['pvp']:.2f} | DY {kwargs['dy']:.1%}.\nMotivo: {kwargs['motivo']}.\n1.Diagnóstico\n2.Dilema\n3.Veredito."

    if not HAS_AI: st.error("Sem API Key"); return
    with st.spinner(f"Analisando {ativo}..."):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={API_KEY}"
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            resp = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(data))
            if resp.status_code == 200:
                txt = resp.json()['candidates'][0]['content']['parts'][0]['text']
                st.markdown(txt)
                st.caption("Copiar análise:"); st.code(txt, language=None)
            else: st.error("Erro IA")
        except Exception as e: st.error(str(e))
    st.divider(); st.subheader("📺 Vídeo Relacionado")
    with st.spinner("Buscando..."):
        vid = buscar_video(ativo)
        if vid: st.video(vid['link']); st.caption(f"{vid['title']} | {vid['views']}")
        else: st.info("Sem vídeo."); st.link_button("YouTube", f"https://www.youtube.com/results?search_query=analise+{ativo}")

def fmt(valor, prefix="R$ ", is_pct=False):
    if st.session_state.get('privacy_mode'): return "••••••"
    return pct_br(valor) if is_pct else real_br(valor)

# --- APP ---
c1, c2 = st.columns([6, 1])
with c1: st.markdown("## 💠 Carteira Pro")
with c2: 
    if st.button("↻ Atualizar"): st.cache_data.clear(); st.rerun()

df = carregar_tudo()

with st.sidebar:
    st.header("Ferramentas")
    if URL_EDIT: st.link_button("🔗 Planilha", URL_EDIT)
    if 'privacy_mode' not in st.session_state: st.session_state['privacy_mode'] = False
    st.session_state['privacy_mode'] = st.toggle("🔒 Privacidade", value=st.session_state['privacy_mode'])
    
    st.divider()
    st.subheader("🎯 Metas (Termômetro)")
    meta_renda = st.number_input("Meta Renda (R$)", value=12500, step=500)
    
    if 'ipca_cache' not in st.session_state: st.session_state['ipca_cache'] = get_ipca_acumulado_12m()
    ipca_atual = st.session_state['ipca_cache']
    st.caption(f"IPCA (12m): **{ipca_atual:.2%}** (BCB)")
    
    st.divider()
    if not df.empty and st.button("✨ IA Geral", type="primary", use_container_width=True):
        pass # Placeholder

if not df.empty:
    patr = df["Valor Atual"].sum(); renda = df["Renda Mensal"].sum(); investido = df["Total Investido"].sum()
    val_rs = patr - investido; val_pct = val_rs / investido if investido > 0 else 0
    fiis_total = df[df["Tipo"]=="FII"]["Valor Atual"].sum()
    cls_val = "pos" if val_rs >= 0 else "neg"; sinal = "+" if val_rs >= 0 else ""

    # TERMÔMETRO
    perc_lib = renda / meta_renda if meta_renda > 0 else 0
    dy_real = ((renda*12)/patr if patr>0 else 0) - ipca_atual
    c_t1, c_t2 = st.columns([3, 1])
    with c_t1: st.markdown(f"**🌡️ Liberdade Financeira:** {perc_lib:.1%} da Meta"); st.progress(min(perc_lib, 1.0))
    with c_t2: 
        cor = "green" if dy_real > 0 else "red"
        st.markdown(f"<div style='text-align:center; background:#f0f2f6; padding:5px; border-radius:10px;'><small>Yield Real</small><br><strong style='color:{cor}'>{dy_real:.2%}</strong></div>", unsafe_allow_html=True)
    st.write("")

    # CARDS
    st.markdown(f"""<div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-label">Patrimônio</div><div class="kpi-value">{fmt(patr)}</div><div class="kpi-delta neu">Total</div></div>
        <div class="kpi-card"><div class="kpi-label">Investido</div><div class="kpi-value">{fmt(investido)}</div><div class="kpi-delta neu">Custo</div></div>
        <div class="kpi-card"><div class="kpi-label">Valorização</div><div class="kpi-value">{fmt(val_rs)}</div><div class="kpi-delta {cls_val}">{sinal}{fmt(val_pct, "", True)}</div></div>
        <div class="kpi-card"><div class="kpi-label">Renda Mensal</div><div class="kpi-value">{fmt(renda)}</div><div class="kpi-delta pos">Dividendos</div></div>
        <div class="kpi-card"><div class="kpi-label">FIIs</div><div class="kpi-value">{fmt(fiis_total)}</div><div class="kpi-delta neu">{fmt(fiis_total/patr if patr>0 else 0, "", True)} Carteira</div></div>
    </div>""", unsafe_allow_html=True)

    # --- OPORTUNIDADES ---
    media_peso = df["% Carteira"].mean(); media_dy = df["DY (12m)"].mean()
    df_opp = df[(df["Tipo"]=="FII") & (df["P/VP"]>=0.8) & (df["P/VP"]<=0.9) & (df["DY (12m)"]>0.10) & (df["% Carteira"]<media_peso)].sort_values("P/VP").head(4)
    
    if not df_opp.empty and not st.session_state.get('privacy_mode'):
        st.subheader("🎯 Oportunidades")
        cols = st.columns(len(df_opp))
        for idx, row in enumerate(df_opp.itertuples(index=False)):
            # Recalcula variáveis com segurança (usando iloc no dataframe filtrado)
            ativo = df_opp.iloc[idx]["Ativo"]
            preco = df_opp.iloc[idx]["Preço Atual"]
            pvp = df_opp.iloc[idx]["P/VP"]
            dy = df_opp.iloc[idx]["DY (12m)"]
            peso = df_opp.iloc[idx]["% Carteira"]
            valor_tem = df_opp.iloc[idx]["Valor Atual"]
            falta = (patr * media_peso) - valor_tem
            link = df_opp.iloc[idx]["Link"]

            with cols[idx]:
                st.markdown(f"""<div class="opp-card"><div class="card-header"><div class="card-ticker green-t">{ativo}</div><div class="opp-price">{real_br(preco)}</div></div>
                <div class="card-grid"><div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp:.2f}</div></div><div class="card-item"><div class="card-label">DY 12M</div><div class="card-val">{pct_br(dy)}</div></div>
                <div class="card-item"><div class="card-label">PESO</div><div class="card-val">{pct_br(peso)}</div></div><div class="card-item"><div class="card-label">TENHO</div><div class="card-val">{real_br(valor_tem)}</div></div></div>
                <div class="opp-footer">Meta Média: {pct_br(media_peso)} <br>Aporte Sugerido: {real_br(max(0, falta))}</div>
                <a href="{link}" target="_blank" class="link-btn">🌐 Ver Detalhes</a></div>""", unsafe_allow_html=True)
                
                # Botão IA Full Width
                if st.button(f"✨ Analisar {ativo}", key=f"opp_{ativo}", use_container_width=True): 
                    modal_analise(ativo, "compra", preco=preco, pvp=pvp, dy=dy)
        st.divider()

    # --- ALERTAS DE SAÍDA ---
    df_alert = df[(df["Tipo"]=="FII") & ((df["P/VP"]>1.1) | (df["DY (12m)"]<(media_dy*0.85)) | ((df["P/VP"]<0.7) & (df["DY (12m)"]<0.08)))].head(4)
    if not df_alert.empty and not st.session_state.get('privacy_mode'):
        st.subheader("⚠️ Radar de Atenção")
        cols = st.columns(len(df_alert))
        for idx, row in enumerate(df_alert.itertuples(index=False)):
            # Recalcula variáveis
            ativo = df_alert.iloc[idx]["Ativo"]
            preco = df_alert.iloc[idx]["Preço Atual"]
            pm = df_alert.iloc[idx]["Preço Médio"]
            pvp = df_alert.iloc[idx]["P/VP"]
            dy = df_alert.iloc[idx]["DY (12m)"]
            peso = df_alert.iloc[idx]["% Carteira"]
            valor_tem = df_alert.iloc[idx]["Valor Atual"]
            link = df_alert.iloc[idx]["Link"]
            
            # Motivo
            mots = []
            if pvp > 1.1: mots.append("Caro")
            if dy < (media_dy*0.85): mots.append("Baixo Yield")
            if pvp < 0.7 and dy < 0.08: mots.append("Armadilha?")
            motivo_txt = " + ".join(mots)

            with cols[idx]:
                st.markdown(f"""<div class="alert-card"><div class="card-header"><div class="card-ticker red-t">{ativo}</div><div class="opp-price">{real_br(preco)}</div></div>
                <div class="card-grid"><div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp:.2f}</div></div><div class="card-item"><div class="card-label">DY</div><div class="card-val">{pct_br(dy)}</div></div>
                <div class="card-item"><div class="card-label">MEU PM</div><div class="card-val">{real_br(pm)}</div></div><div class="card-item"><div class="card-label">PESO</div><div class="card-val">{pct_br(peso)}</div></div>
                <div class="card-item" style="grid-column: span 2;"><div class="card-label">TENHO (R$)</div><div class="card-val">{real_br(valor_tem)}</div></div></div>
                <div class="alert-footer" style="background:white; border:1px solid #ffccbc; color:#bf360c;">🚨 {motivo_txt}</div>
                <a href="{link}" target="_blank" class="link-btn">🌐 Ver Detalhes</a></div>""", unsafe_allow_html=True)
                
                # Botão IA Full Width
                if st.button(f"🔍 Diagnóstico", key=f"alert_{ativo}", use_container_width=True): 
                    modal_analise(ativo, "venda", preco=preco, pm=pm, pvp=pvp, dy=dy, motivo=motivo_txt)
        st.divider()

    # --- ABAS ---
    t1, t2, t3, t4, t5 = st.tabs(["📊 Visão Setorial", "🎯 Matriz & Radar", "📋 Inventário", "📅 Agenda", "📈 Histórico"])

    with t1: # GRÁFICO SETORIAL CORRIGIDO
        c1, c2 = st.columns(2)
        with c1:
            fig = px.sunburst(df, path=['Tipo', 'Setor', 'Ativo'], values='Valor Atual', color='Setor', title="Diversificação (Baseado na Planilha)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            top_s = df.groupby("Setor")["Valor Atual"].sum().sort_values(ascending=False).reset_index()
            fig2 = px.bar(top_s, x="Valor Atual", y="Setor", orientation='h', title="Exposição por Setor")
            st.plotly_chart(fig2, use_container_width=True)

    with t2: # MATRIZ + TABELA DESCONTOS (HEATMAP CORRIGIDO)
        st.subheader("Matriz de Valor (FIIs)")
        df_fii = df[(df["Tipo"]=="FII") & (df["P/VP"]>0)].copy()
        if not df_fii.empty:
            fig = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo", template="plotly_white")
            fig.add_shape(type="rect", x0=0, y0=media_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1, fillcolor="rgba(0, 200, 83, 0.1)", line=dict(width=0), layer="below")
            fig.add_vline(x=1.0, line_dash="dot", line_color="gray"); st.plotly_chart(fig, use_container_width=True)
        
        st.divider(); st.subheader("🔥 Melhores Descontos")
        df_radar = df[(df["Tipo"]=="FII") & (df["P/VP"]<1.0) & (df["P/VP"]>0.1)].copy()
        if not df_radar.empty:
            st.dataframe(df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]].style.format({"Preço Atual": real_br, "Valor Atual": real_br, "P/VP": "{:.2f}", "DY (12m)": pct_br, "% Carteira": pct_br}).background_gradient(subset=["P/VP"], cmap="RdYlGn_r").background_gradient(subset=["DY (12m)"], cmap="Greens"), use_container_width=True)

    with t3: # INVENTÁRIO
        cols_show = ["Link", "Ativo", "Setor", "Preço Médio", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"]
        df_inv = df[[c for c in cols_show if c in df.columns]].copy()
        st.dataframe(df_inv.style.format({"Preço Médio": real_br, "Preço Atual": real_br, "Valor Atual": real_br, "Renda Mensal": real_br, "Qtd": "{:.0f}", "Var %": pct_br, "DY (12m)": pct_br, "% Carteira": pct_br}).background_gradient(subset=["Var %"], cmap="RdYlGn", vmin=-0.5, vmax=0.5).background_gradient(subset=["DY (12m)"], cmap="Greens"), column_config={"Link": st.column_config.LinkColumn("🔗"), "% Carteira": st.column_config.ProgressColumn("Peso")}, height=600)

    with t4: # AGENDA
        st.subheader("📅 Status dos Dividendos (Data Com)")
        # Filtra apenas quem tem Data Com preenchida
        df_ag = df[(df["Tipo"]=="FII") & (df["Data Com"] != "-")][["Ativo", "Data Com", "Link"]].copy()
        if not df_ag.empty:
            st.dataframe(df_ag, column_config={"Link": st.column_config.LinkColumn("🔗")}, use_container_width=True)
        else:
            st.info("Nenhuma data 'Data Com' encontrada na coluna 19 da planilha.")

    with t5: # HISTÓRICO COM SELETOR
        st.subheader("📈 Rentabilidade Relativa")
        ativos = df[df["Tipo"].isin(["FII", "Ação"])]["Ativo"].tolist()
        if ativos:
            c_sel, c_p, c_b = st.columns([2, 1, 1])
            with c_sel: sel = st.multiselect("Ativos:", ativos, default=ativos[:3])
            with c_p: per = st.selectbox("Prazo:", ["1mo", "6mo", "1y", "5y"], index=1)
            with c_b: bench = st.selectbox("Benchmark:", ["IBOV", "IFIX"], index=0)
            if sel:
                with st.spinner("..."):
                    hist = obter_historico(sel, per, bench)
                if not hist.empty: st.line_chart((hist/hist.iloc[0]-1)*100)
else: st.info("Carregando...")