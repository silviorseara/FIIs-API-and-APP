import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re
import requests
import json
import numpy as np
import yfinance as yf
import calendar
import unicodedata
from pandas.tseries.offsets import BDay, MonthEnd
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from youtubesearchpython import VideosSearch
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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
COL_DATA_COM = 20
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
    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
    .kpi-card { background-color: var(--background-secondary-color); border: 1px solid rgba(128, 128, 128, 0.1); border-radius: 16px; padding: 24px 16px; text-align: center; box-shadow: 0 4px 6px -2px rgba(0, 0, 0, 0.05); height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; }
    
    .opp-card, .alert-card {
        border: 1px solid rgba(0,0,0,0.1); border-radius: 16px; padding: 16px; text-align: center; height: 100%;
        display: flex; flex-direction: column; justify-content: space-between; margin-bottom: 10px;
    }
    .opp-card { background: linear-gradient(135deg, rgba(20, 184, 166, 0.05) 0%, rgba(16, 185, 129, 0.1) 100%); border-color: rgba(20, 184, 166, 0.3); }
    .alert-card { background: linear-gradient(135deg, rgba(255, 87, 34, 0.05) 0%, rgba(255, 152, 0, 0.1) 100%); border-color: rgba(255, 87, 34, 0.3); }

    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 8px; }
    .card-ticker { font-size: 1.4rem; font-weight: 800; color: #333; line-height: 1.1; }
    .card-sector { font-size: 0.75rem; color: #7f8c8d; font-weight: 600; text-transform: uppercase; } 
    .green-t { color: #0f766e; } .red-t { color: #c0392b; }
    
    .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.8rem; text-align: left; }
    .card-item { background: rgba(255,255,255,0.6); padding: 8px; border-radius: 8px; }
    .card-label { font-size: 0.65rem; color: #666; text-transform: uppercase; margin-bottom: 2px; }
    .card-val { font-weight: 700; color: #333; font-size: 0.9rem; }
    
    .opp-footer { margin-top: 12px; background-color: #ccfbf1; color: #0f766e; padding: 6px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }
    .alert-footer { margin-top: 12px; background-color: #ffccbc; color: #bf360c; padding: 6px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }
    
    .link-btn { display: block; width: 100%; text-decoration: none; background-color: #fff; border: 1px solid #ccc; color: #555; padding: 6px 0; border-radius: 8px; font-size: 0.8rem; font-weight: 600; transition: all 0.2s; cursor: pointer; text-align: center; }
    .link-btn:hover { background-color: #eee; }

    .kpi-label { font-size: 0.75rem; opacity: 0.7; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    .kpi-value { font-size: 1.7rem; font-weight: 700; color: var(--text-color); margin-bottom: 5px; }
    .kpi-delta { font-size: 0.75rem; font-weight: 600; padding: 4px 12px; border-radius: 20px; display: inline-block; }
    .pos { color: #065f46; background-color: #d1fae5; } .neg { color: #991b1b; background-color: #fee2e2; } .neu { color: #374151; background-color: #f3f4f6; }
    
    .stButton button { width: 100%; border-radius: 10px; font-weight: 600; height: 40px; }
    .stProgress > div > div > div > div { background-color: #0f766e; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---
def real_br(valor): return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if isinstance(valor, (int, float)) else valor
def pct_br(valor): return f"{valor:.2%}".replace(".", ",") if isinstance(valor, (int, float)) else valor
def to_f(x): 
    try: return float(str(x).replace("R$","").replace("%","").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
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

@st.cache_data(ttl=86400)
def get_selic_meta():
    # Fonte principal: BrasilAPI (taxas/v1)
    try:
        url_main = "https://brasilapi.com.br/api/taxas/v1"
        resp = requests.get(url_main, timeout=5, headers={"User-Agent": "CarteiraPro/1.0"})
        if resp.status_code == 200:
            dados = resp.json()
            if isinstance(dados, list):
                for item in dados:
                    nome = str(item.get("nome", "")).upper()
                    valor = item.get("valor")
                    if "SELIC" in nome and isinstance(valor, (int, float)):
                        return float(valor) / 100
    except Exception:
        pass

    # Fallback: API BCB oficial (pode exigir permissões especiais em algumas redes)
    try:
        url_bcb = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json"
        headers = {"User-Agent": "CarteiraPro/1.0", "Accept": "application/json"}
        resp = requests.get(url_bcb, timeout=5, headers=headers)
        if resp.status_code == 200:
            dados = resp.json()
            if dados:
                return float(dados[0]["valor"]) / 100
    except Exception:
        pass
    return 0.12

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
    tickers_sa = [f"{t}.SA" if not t.endswith(".SA") else t for t in tickers]
    bench_ticker = "^BVSP" if benchmark == "IBOV" else "IFIX.SA"
    tickers_sa.append(bench_ticker)
    try:
        dados = yf.download(tickers_sa, period=periodo, progress=False)['Close']
        if isinstance(dados, pd.Series): dados = dados.to_frame(); dados.columns = tickers_sa
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
                    try:
                        setor = str(row[COL_SETOR]).strip()
                        if setor == "" or setor.lower() == "nan": setor = "Indefinido"
                    except: setor = "Indefinido"
                    try: data_com = str(row[COL_DATA_COM]).strip()
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

MESES_PT = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

TIJOLO_KEYWORDS = [
    "TIJOLO", "LOGIST", "SHOP", "LAJE", "CORPORAT", "RESID", "HOSPITAL", "HOTEL", "EDUC", "AGRO", "IMOBILIARIO URB",
    "RENDA URB", "DESENV", "MULTIPROPRI", "HÍBRID", "HIBRID", "INDUSTR"
]

def normalizar_setor(setor):
    if not setor:
        return ""
    texto = unicodedata.normalize('NFD', str(setor))
    texto = ''.join(ch for ch in texto if unicodedata.category(ch) != 'Mn')
    return texto.upper().strip()

def setor_eh_tijolo(setor):
    norm = normalizar_setor(setor)
    if not norm:
        return False
    return any(chave in norm for chave in TIJOLO_KEYWORDS)

def resolver_data_com(valor, referencia=None):
    if referencia is None:
        referencia = datetime.now()
    if pd.isna(valor):
        return None
    texto = str(valor).strip()
    if not texto or texto == "-":
        return None
    texto_upper = texto.upper()

    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue

    if re.match(r"^\d{1,2}/\d{1,2}$", texto):
        try:
            dia, mes = map(int, texto.split("/"))
            ano = referencia.year
            dt = datetime(ano, mes, dia)
            if dt.date() < referencia.date():
                dt = datetime(ano + 1, mes, dia)
            return dt
        except ValueError:
            return None

    ano_ref, mes_ref = referencia.year, referencia.month
    base_mes = pd.Timestamp(ano_ref, mes_ref, 1)

    match = re.match(r"(\d{1,2})º DIA ÚTIL", texto_upper)
    if match:
        try:
            pos = int(match.group(1))
            if pos <= 0:
                return None
            dt = (base_mes + BDay(pos - 1)).to_pydatetime()
            return dt
        except Exception:
            return None

    if "ÚLTIMO DIA ÚTIL" in texto_upper:
        dt = (base_mes + MonthEnd(0)).to_pydatetime()
        while dt.weekday() >= 5:
            dt = dt - timedelta(days=1)
        return dt

    return None

def gerar_calendario_dividendos(mapa_dividendos, referencia):
    cal = calendar.Calendar(firstweekday=0)
    semanas = cal.monthdayscalendar(referencia.year, referencia.month)
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    dados_z = []
    dados_texto = []

    for semana in semanas:
        linha_valores = []
        linha_textos = []
        for dia in semana:
            if dia == 0:
                linha_valores.append(None)
                linha_textos.append("")
            else:
                data_atual = datetime(referencia.year, referencia.month, dia).date()
                total = mapa_dividendos.get(data_atual, 0.0)
                linha_valores.append(total if total > 0 else 0.0)
                linha_textos.append(f"{dia}\n{real_br(total)}" if total > 0 else str(dia))
        dados_z.append(linha_valores)
        dados_texto.append(linha_textos)

    fig = go.Figure(data=go.Heatmap(
        z=dados_z,
        x=dias_semana,
        y=[f"Semana {idx + 1}" for idx in range(len(dados_z))],
        text=dados_texto,
        hoverinfo="text",
        colorscale="YlGnBu",
        xgap=2,
        ygap=2,
        showscale=False,
        zmin=0
    ))

    titulo_mes = f"{MESES_PT[referencia.month]} / {referencia.year}" if 1 <= referencia.month <= 12 else referencia.strftime("%m/%Y")

    fig.update_layout(
        title=f"Calendário de Dividendos - {titulo_mes}",
        yaxis=dict(autorange="reversed", showgrid=False, zeroline=False),
        xaxis=dict(showgrid=False, zeroline=False),
        height=260,
        margin=dict(l=10, r=10, t=60, b=10)
    )
    return fig

# --- SALVAMENTO (COM CORREÇÃO DE ERRO JSON) ---
def salvar_snapshot_google(df, patrimonio, investido):
    try:
        # 1. Autenticação (AQUI ESTÁ A CORREÇÃO: strict=False)
        creds_json = json.loads(st.secrets["GOOGLE_CREDENTIALS"], strict=False)
        
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
        client = gspread.authorize(creds)
        
        # 2. Abre a Planilha (Tenta ID ou URL)
        if "SHEET_ID" in st.secrets:
            sheet_id = st.secrets["SHEET_ID"]
            sh = client.open_by_key(sheet_id)
        else:
            url = st.secrets["SHEET_URL_FIIS"]
            # Extrai ID da URL se necessário
            try: sheet_id = url.split("/d/")[1].split("/")[0]
            except: sheet_id = url
            sh = client.open_by_key(sheet_id)

        try: worksheet = sh.worksheet("Cache_Dados")
        except: worksheet = sh.add_worksheet(title="Cache_Dados", rows="100", cols="20")
        
        # 3. Salva
        worksheet.clear()
        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        worksheet.update('A1', [['Atualizado em', 'Patrimonio', 'Investido'], [agora, float(patrimonio), float(investido)]])
        
        df_export = df[['Ativo', 'Tipo', 'Preço Atual', 'Valor Atual', 'P/VP', 'DY (12m)', 'Setor']].copy()
        df_export = df_export.fillna(0)
        dados_lista = [df_export.columns.values.tolist()] + df_export.values.tolist()
        worksheet.update('A4', dados_lista)
        
        return True, f"✅ Dados sincronizados com sucesso às {agora}"
    except Exception as e: return False, f"❌ Erro Técnico: {str(e)}"

@st.dialog("🤖 Análise Inteligente", width="large")
def modal_analise(ativo, tipo_analise, **kwargs):
    st.empty()
    prompt = f"Analise {ativo}. {kwargs}"
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
    meta_renda = st.number_input("Meta Renda (R$)", value=10000, step=500)
    
    if 'ipca_cache' not in st.session_state: st.session_state['ipca_cache'] = get_ipca_acumulado_12m()
    if 'selic_cache' not in st.session_state: st.session_state['selic_cache'] = get_selic_meta()
    ipca_atual = st.session_state['ipca_cache']
    selic_atual = st.session_state['selic_cache']
    st.caption(f"IPCA (12m): **{ipca_atual:.2%}** (BCB)")
    st.caption(f"SELIC oficial: **{selic_atual:.2%}** (fonte automática)")

    params_defaults = {
        "selic_custom": selic_atual,
        "opp_pvp_min": 0.80,
        "opp_pvp_max": 0.90,
        "opp_dy_min": 0.12,
        "opp_aporte_min": 1000.0,
        "radar_tijolo_pct": 0.60,
        "radar_outros_pct": 0.80,
    }
    if 'user_params' not in st.session_state: st.session_state['user_params'] = params_defaults.copy()
    else:
        for chave, val in params_defaults.items():
            st.session_state['user_params'].setdefault(chave, val)
    params = st.session_state['user_params']

    st.divider()
    st.subheader("⚙️ Parâmetros")
    selic_input = st.number_input("SELIC utilizada (%)", value=float(params['selic_custom'] * 100), step=0.25, min_value=0.0, max_value=100.0)
    params['selic_custom'] = selic_input / 100 if selic_input else 0.0

    with st.expander("Filtros de oportunidades"):
        c_op1, c_op2 = st.columns(2)
        params['opp_pvp_min'] = c_op1.number_input("P/VP mínimo", value=float(params['opp_pvp_min']), min_value=0.0, max_value=2.0, step=0.05)
        params['opp_pvp_max'] = c_op2.number_input("P/VP máximo", value=float(params['opp_pvp_max']), min_value=0.0, max_value=2.0, step=0.05)
        if params['opp_pvp_max'] < params['opp_pvp_min']:
            params['opp_pvp_max'] = params['opp_pvp_min']
        c_op3, c_op4 = st.columns(2)
        dy_min_input = c_op3.number_input("DY mínimo (%)", value=float(params['opp_dy_min'] * 100), min_value=0.0, max_value=100.0, step=0.25)
        params['opp_dy_min'] = dy_min_input / 100 if dy_min_input else 0.0
        params['opp_aporte_min'] = c_op4.number_input("Aporte mínimo (R$)", value=float(params['opp_aporte_min']), min_value=0.0, step=100.0)

    with st.expander("Critérios do radar"):
        c_rd1, c_rd2 = st.columns(2)
        tijolo_pct_input = c_rd1.number_input("Tijolo: % da SELIC", value=float(params['radar_tijolo_pct'] * 100), min_value=0.0, max_value=100.0, step=5.0)
        outros_pct_input = c_rd2.number_input("Outros: % da SELIC", value=float(params['radar_outros_pct'] * 100), min_value=0.0, max_value=100.0, step=5.0)
        params['radar_tijolo_pct'] = tijolo_pct_input / 100 if tijolo_pct_input else 0.0
        params['radar_outros_pct'] = outros_pct_input / 100 if outros_pct_input else 0.0
    
    st.divider()
    if not df.empty and st.button("✨ IA Geral", type="primary", use_container_width=True): pass

if not df.empty:
    patr = df["Valor Atual"].sum()
    renda_nominal = df["Renda Mensal"].sum()
    investido = df["Total Investido"].sum()
    selic_utilizada = params['selic_custom'] if params.get('selic_custom', 0) > 0 else selic_atual
    
    # --- CÁLCULO DA REALIDADE (Ajuste de Inflação) ---
    # 1. Converter IPCA anual para mensal (Juros Compostos)
    ipca_mensal = ((1 + ipca_atual) ** (1/12)) - 1
    
    # 2. Quanto do dividendo deve ser REINVESTIDO obrigatoriamente para manter o poder de compra do principal
    custo_manutencao_patrimonio = patr * ipca_mensal
    
    # 3. Renda Real (O que sobra para gastar sem corroer o patrimônio)
    renda_real_disponivel = renda_nominal - custo_manutencao_patrimonio
    
    # 4. Yield Real Anualizado (Métrica percentual ajustada)
    # Fórmula de Fisher aproximada para o todo: ((1 + Yield_Nominal) / (1 + Inflação)) - 1
    yield_nominal_anual = (renda_nominal * 12) / patr if patr > 0 else 0
    yield_real_perc = ((1 + yield_nominal_anual) / (1 + ipca_atual)) - 1

    # --- MÉTRICAS DE CARTEIRA ---
    val_rs = patr - investido
    val_pct = val_rs / investido if investido > 0 else 0
    fiis_total = df[df["Tipo"]=="FII"]["Valor Atual"].sum()
    cls_val = "pos" if val_rs >= 0 else "neg"; sinal = "+" if val_rs >= 0 else ""

    # --- AUTO-SAVE (Mantedo sua lógica) ---
    if 'dados_salvos' not in st.session_state:
        with st.spinner("Sincronizando dados com o Robô..."):
            sucesso, msg = salvar_snapshot_google(df, patr, investido)
            if sucesso:
                st.session_state['dados_salvos'] = True
                st.toast("✅ Dados atualizados na nuvem!", icon="☁️")
            else: st.error(f"Falha Auto-Save: {msg}")

    # --- TERMÔMETRO (AGORA HONESTO) ---
    # O progresso agora é sobre a Renda Real, não a Nominal
    perc_lib = renda_real_disponivel / meta_renda if meta_renda > 0 else 0
    
    # Se a inflação for maior que o dividendo, a renda real é negativa (consumo de capital)
    perc_lib = max(0.0, perc_lib) 

    c_t1, c_t2 = st.columns([3, 1])
    
    with c_t1: 
        st.markdown(f"**🌡️ Liberdade Financeira REAL:** {perc_lib:.1%} da Meta (Livre de Inflação)")
        st.progress(min(perc_lib, 1.0))
        
    with c_t2: 
        cor = "green" if yield_real_perc > 0 else "red"
        # Mostra o Custo da Inflação em R$ para "doer" visualmente
        st.markdown(f"""
        <div style='text-align:center; background:#f0f2f6; padding:8px; border-radius:10px;'>
            <small style='color:#7f8c8d'>Reposição Inflacionária</small><br>
            <strong style='color:#c0392b'>- {fmt(custo_manutencao_patrimonio)}/mês</strong>
        </div>
        """, unsafe_allow_html=True)
    
    st.write("") # Espaçamento

# --- CÁLCULO DAS VARIÁVEIS ---
    custo_inflacao = renda_nominal - renda_real_disponivel
    perc_fiis = fiis_total/patr if patr > 0 else 0
    selic_delta = selic_utilizada - selic_atual
    if abs(selic_delta) < 1e-6:
        selic_delta_txt = "Oficial"
        selic_delta_cls = "neu"
    else:
        selic_delta_txt = f"{'+' if selic_delta > 0 else ''}{pct_br(selic_delta)} vs oficial"
        selic_delta_cls = "pos" if selic_delta > 0 else "neg"

    # --- MONTAGEM DO HTML (SEM ESPAÇOS NA ESQUERDA) ---
    # Nota: O texto abaixo deve ficar encostado na margem esquerda do editor
    html_kpi = f"""
<div class="kpi-grid">
<div class="kpi-card">
<div class="kpi-label">Patrimônio</div>
<div class="kpi-value">{fmt(patr)}</div>
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

<div class="kpi-card" style="border: 1px solid rgba(16, 185, 129, 0.3);">
<div class="kpi-label" style="color:#047857; font-weight:700;">Renda Nominal</div>
<div class="kpi-value" style="color:#065f46;">{fmt(renda_nominal)}</div>
<div class="kpi-delta pos">Recebido</div>
</div>

<div class="kpi-card" style="background-color: #fff1f2; border: 1px solid rgba(225, 29, 72, 0.3);">
<div class="kpi-label" style="color:#be123c; font-weight:700;">Renda Real</div>
<div class="kpi-value" style="color:#9f1239;">{fmt(renda_real_disponivel)}</div>
<div class="kpi-delta neg" title="Perda inflacionária mensal">- {fmt(custo_inflacao)} (IPCA)</div>
</div>

<div class="kpi-card">
<div class="kpi-label">FIIs</div>
<div class="kpi-value">{fmt(fiis_total)}</div>
<div class="kpi-delta neu">{fmt(perc_fiis, "", True)} Carteira</div>
</div>

<div class="kpi-card">
<div class="kpi-label">SELIC Utilizada</div>
<div class="kpi-value">{pct_br(selic_utilizada)}</div>
<div class="kpi-delta {selic_delta_cls}">{selic_delta_txt}</div>
</div>
</div>
"""

    # --- RENDERIZAÇÃO ---
    st.markdown(html_kpi, unsafe_allow_html=True)

    # OPORTUNIDADES
    media_peso = df["% Carteira"].mean(); media_dy = df["DY (12m)"].mean()
    df_opp = df[(df["Tipo"]=="FII") & (df["P/VP"]>=params['opp_pvp_min']) & (df["P/VP"]<=params['opp_pvp_max']) & (df["DY (12m)"]>=params['opp_dy_min']) & (df["% Carteira"]<media_peso)].copy()
    if not df_opp.empty:
        df_opp["AporteSugerido"] = np.maximum(0, (patr * media_peso) - df_opp["Valor Atual"])
        df_opp = df_opp[df_opp["AporteSugerido"] >= params['opp_aporte_min']]
        df_opp = df_opp.sort_values(by=["P/VP", "DY (12m)", "AporteSugerido"], ascending=[True, False, False]).head(4)
    
    if not df_opp.empty and not st.session_state.get('privacy_mode'):
        st.subheader("🎯 Oportunidades")
        cols = st.columns(len(df_opp))
        for idx, (_, row) in enumerate(df_opp.iterrows()):
            ativo = row["Ativo"]; preco = row["Preço Atual"]
            pvp = row["P/VP"]; dy = row["DY (12m)"]
            peso = row["% Carteira"]; valor_tem = row["Valor Atual"]
            falta = row["AporteSugerido"]; link = row["Link"]
            setor = row["Setor"] # <--- NOVA VARIÁVEL

            with cols[idx]:
                # AQUI ABAIXO: Adicionei uma div envolvendo Ticker e Setor
                st.markdown(f"""<div class="opp-card">
                    <div class="card-header">
                        <div>
                            <div class="card-ticker green-t">{ativo}</div>
                            <div class="card-sector">{setor}</div>
                        </div>
                        <div class="opp-price">{real_br(preco)}</div>
                    </div>
                    <div class="card-grid">
                        <div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp:.2f}</div></div>
                        <div class="card-item"><div class="card-label">DY 12M</div><div class="card-val">{pct_br(dy)}</div></div>
                        <div class="card-item"><div class="card-label">PESO</div><div class="card-val">{pct_br(peso)}</div></div>
                        <div class="card-item"><div class="card-label">TENHO</div><div class="card-val">{real_br(valor_tem)}</div></div>
                    </div>
                    <div class="opp-footer">Meta Média: {pct_br(media_peso)} <br>Aporte Sugerido: {real_br(falta)}</div>
                    <a href="{link}" target="_blank" class="link-btn">🌐 Ver Detalhes</a>
                </div>""", unsafe_allow_html=True)
                
                if st.button(f"✨ Analisar {ativo}", key=f"opp_{ativo}", use_container_width=True): 
                    modal_analise(ativo, "compra", preco=preco, pvp=pvp, dy=dy)
        st.divider()

    # ALERTAS
    df_alert = df[(df["Tipo"]=="FII") & ((df["P/VP"]>1.1) | (df["DY (12m)"]<(media_dy*0.85)) | ((df["P/VP"]<0.7) & (df["DY (12m)"]<0.08)))].copy()
    if not df_alert.empty:
        selic_limite = selic_utilizada if selic_utilizada > 0 else selic_atual

        def _classificar_risco(row):
            motivos = []
            if row["P/VP"] > 1.1: motivos.append("Caro")
            threshold_yield = media_dy * 0.85
            if selic_limite > 0:
                if setor_eh_tijolo(row.get("Setor", "")):
                    threshold_yield = max(threshold_yield, selic_limite * params['radar_tijolo_pct'])
                else:
                    threshold_yield = max(threshold_yield, selic_limite * params['radar_outros_pct'])
            if row["DY (12m)"] < threshold_yield: motivos.append("Baixo Yield")
            if row["P/VP"] < 0.7 and row["DY (12m)"] < 0.08: motivos.append("Armadilha")
            if "Baixo Yield" in motivos and "Armadilha" in motivos:
                risco_ordem = 0; risco_txt = "Baixo Yield + Armadilha"
            elif "Baixo Yield" in motivos:
                risco_ordem = 1; risco_txt = "Baixo Yield"
            else:
                risco_ordem = 2; risco_txt = " + ".join(motivos) if motivos else "Observação"
            return pd.Series({"MotivoTexto": " + ".join(motivos) if motivos else "Observação", "RiscoOrdem": risco_ordem, "EtiquetaRisco": risco_txt})

        df_alert[["MotivoTexto", "RiscoOrdem", "EtiquetaRisco"]] = df_alert.apply(_classificar_risco, axis=1)
        df_alert = df_alert.sort_values(by=["Valor Atual", "RiscoOrdem"], ascending=[False, True]).head(4)
    if not df_alert.empty and not st.session_state.get('privacy_mode'):
        st.subheader("⚠️ Radar de Atenção")
        cols = st.columns(len(df_alert))
        for idx, (_, row) in enumerate(df_alert.iterrows()):
            ativo = row["Ativo"]; preco = row["Preço Atual"]
            pm = row["Preço Médio"]; pvp = row["P/VP"]
            dy = row["DY (12m)"]; peso = row["% Carteira"]
            valor_tem = row["Valor Atual"]; link = row["Link"]
            setor = row["Setor"] # <--- NOVA VARIÁVEL
            motivo_txt = row["MotivoTexto"]

            with cols[idx]:
                # AQUI ABAIXO: Mesma alteração no Header
                st.markdown(f"""<div class="alert-card">
                    <div class="card-header">
                        <div>
                            <div class="card-ticker red-t">{ativo}</div>
                            <div class="card-sector">{setor}</div>
                        </div>
                        <div class="opp-price">{real_br(preco)}</div>
                    </div>
                    <div class="card-grid">
                        <div class="card-item"><div class="card-label">P/VP</div><div class="card-val">{pvp:.2f}</div></div>
                        <div class="card-item"><div class="card-label">DY</div><div class="card-val">{pct_br(dy)}</div></div>
                        <div class="card-item"><div class="card-label">MEU PM</div><div class="card-val">{real_br(pm)}</div></div>
                        <div class="card-item"><div class="card-label">PESO</div><div class="card-val">{pct_br(peso)}</div></div>
                        <div class="card-item" style="grid-column: span 2;"><div class="card-label">TENHO (R$)</div><div class="card-val">{real_br(valor_tem)}</div></div>
                    </div>
                    <div class="alert-footer" style="background:white; border:1px solid #ffccbc; color:#bf360c;">🚨 {motivo_txt}</div>
                    <a href="{link}" target="_blank" class="link-btn">🌐 Ver Detalhes</a>
                </div>""", unsafe_allow_html=True)
                
                if st.button(f"🔍 Diagnóstico", key=f"alert_{ativo}", use_container_width=True): 
                    modal_analise(ativo, "venda", preco=preco, pm=pm, pvp=pvp, dy=dy, motivo=motivo_txt)
        st.divider()

    # ABAS
    t1, t2, t3, t4, t5 = st.tabs(["📊 Visão Setorial", "🎯 Matriz & Radar", "📋 Inventário", "📅 Agenda", "📈 Histórico"])

    with t1: # GRÁFICO SETORIAL
        c1, c2 = st.columns(2)
        with c1:
            fig = px.sunburst(df, path=['Tipo', 'Setor', 'Ativo'], values='Valor Atual', color='Setor', title="Diversificação por Setor")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            top_s = df.groupby("Setor")["Valor Atual"].sum().sort_values(ascending=False).reset_index()
            fig2 = px.bar(top_s, x="Valor Atual", y="Setor", orientation='h', title="Exposição por Setor")
            st.plotly_chart(fig2, use_container_width=True)

    with t2: # MATRIZ + TABELA
        st.subheader("Matriz de Valor (FIIs)")
        df_fii = df[(df["Tipo"]=="FII") & (df["P/VP"]>0)].copy()
        if not df_fii.empty:
            fig = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo", template="plotly_white")
            fig.add_shape(type="rect", x0=0, y0=media_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1, fillcolor="rgba(0, 200, 83, 0.1)", line=dict(width=0), layer="below")
            fig.add_vline(x=1.0, line_dash="dot", line_color="gray"); st.plotly_chart(fig, use_container_width=True)
        st.divider(); st.subheader("🔥 Melhores Descontos")
        df_radar = df[(df["Tipo"]=="FII") & (df["P/VP"]<1.0) & (df["P/VP"]>0.1)].copy()
        if not df_radar.empty:
            cols_descontos = ["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]
            tabela_descontos = df_radar.sort_values("P/VP")[cols_descontos]
            st.dataframe(
                tabela_descontos
                .style
                .format({"Preço Atual": real_br, "Valor Atual": real_br, "P/VP": "{:.2f}", "DY (12m)": pct_br, "% Carteira": pct_br})
                .background_gradient(subset=["P/VP"], cmap="RdYlGn_r")
                .background_gradient(subset=["DY (12m)"], cmap="Greens")
                .background_gradient(subset=["% Carteira"], cmap="Blues"),
                use_container_width=True
            )

    with t3: # INVENTÁRIO
        cols_show = ["Link", "Ativo", "Setor", "Preço Médio", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"]
        df_inv = df[[c for c in cols_show if c in df.columns]].copy()
        if "Link" in df_inv.columns:
            df_inv["Ficha"] = df_inv["Link"]
            df_inv.drop(columns=["Link"], inplace=True)
        else:
            df_inv["Ficha"] = None
        ordem_cols = ["Ficha", "Ativo", "Setor", "Preço Médio", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)", "% Carteira", "Renda Mensal"]
        df_inv = df_inv[[c for c in ordem_cols if c in df_inv.columns]]
        st.dataframe(
            df_inv.style
            .format({"Preço Médio": real_br, "Preço Atual": real_br, "Valor Atual": real_br, "Renda Mensal": real_br, "Qtd": "{:.0f}", "Var %": pct_br, "DY (12m)": pct_br, "% Carteira": pct_br})
            .background_gradient(subset=["Var %"], cmap="RdYlGn", vmin=-0.5, vmax=0.5)
            .background_gradient(subset=["DY (12m)"], cmap="Greens"),
            column_config={
                "Ficha": st.column_config.LinkColumn(" ", display_text="🔗", help="Abrir detalhes do ativo"),
                "% Carteira": st.column_config.ProgressColumn("Peso")
            },
            height=600
        )

    with t4: # AGENDA
        st.subheader("📅 Status dos Dividendos (Data Com)")
        df_ag = df[(df["Tipo"]=="FII") & (df["Data Com"] != "-")][["Ativo", "Data Com", "Link", "Renda Mensal"]].copy()
        if df_ag.empty:
            st.info("Nenhuma data encontrada.")
        else:
            hoje = datetime.now()
            df_ag["Data Prevista"] = df_ag["Data Com"].apply(lambda x: resolver_data_com(x, hoje))
            df_ag.dropna(subset=["Data Prevista"], inplace=True)
            if df_ag.empty:
                st.info("Não foi possível estimar as datas de corte para os registros atuais.")
            else:
                df_ag["Data Prevista"] = pd.to_datetime(df_ag["Data Prevista"])
                df_ag["Dividendo Estimado"] = df_ag["Renda Mensal"].fillna(0.0)
                df_ag["Ficha"] = df_ag["Link"]
                df_ag["Status"] = np.where(df_ag["Data Prevista"].dt.date <= hoje.date(), "Já ocorreu", "Próxima")
                df_ag["Mês"] = df_ag["Data Prevista"].dt.to_period("M")

                meses_disponiveis = sorted(df_ag["Mês"].unique())
                mes_atual = pd.Period(hoje, freq="M")
                mes_default = mes_atual if mes_atual in meses_disponiveis else meses_disponiveis[0]
                mes_escolhido = st.selectbox(
                    "Mês de referência",
                    options=meses_disponiveis,
                    index=meses_disponiveis.index(mes_default) if mes_default in meses_disponiveis else 0,
                    format_func=lambda p: f"{MESES_PT[p.month]} / {p.year}"
                )

                ref_data = datetime(mes_escolhido.year, mes_escolhido.month, 1)
                df_ag_mes = df_ag[df_ag["Mês"] == mes_escolhido].copy().sort_values("Data Prevista")
                if df_ag_mes.empty:
                    st.info("Sem eventos para o mês selecionado.")
                else:
                    total_mes = df_ag_mes["Dividendo Estimado"].sum()
                    if mes_escolhido == mes_atual:
                        total_passado = df_ag_mes[df_ag_mes["Data Prevista"].dt.date <= hoje.date()]["Dividendo Estimado"].sum()
                    else:
                        total_passado = 0.0
                    total_pendente = total_mes - total_passado

                    c_met1, c_met2, c_met3 = st.columns(3)
                    c_met1.metric("Previsto no mês", real_br(total_mes))
                    c_met2.metric("Já passou", real_br(total_passado))
                    c_met3.metric("Ainda por vir", real_br(max(total_pendente, 0.0)))

                    st.markdown("### 🗓️ Calendário do mês")
                    mapa_dividendos = df_ag_mes.groupby(df_ag_mes["Data Prevista"].dt.date)["Dividendo Estimado"].sum().to_dict()
                    st.plotly_chart(gerar_calendario_dividendos(mapa_dividendos, ref_data), use_container_width=True)

                    st.markdown("### 📌 Agenda detalhada")
                    agenda_view = df_ag_mes[["Ativo", "Data Com", "Data Prevista", "Status", "Dividendo Estimado", "Ficha"]].copy()
                    agenda_view["Data Prevista"] = agenda_view["Data Prevista"].dt.date
                    st.dataframe(
                        agenda_view,
                        column_config={
                            "Data Prevista": st.column_config.DateColumn("Data Com"),
                            "Dividendo Estimado": st.column_config.NumberColumn("Dividendo Estimado", format="R$ %.2f"),
                            "Ficha": st.column_config.LinkColumn(" ", display_text="🔗", help="Abrir detalhes do ativo")
                        },
                        use_container_width=True
                    )

                    st.markdown("### 📅 Totais por data")
                    df_tot_data = df_ag_mes.groupby("Data Prevista")["Dividendo Estimado"].sum().reset_index()
                    df_tot_data["Data Prevista"] = df_tot_data["Data Prevista"].dt.date
                    st.dataframe(
                        df_tot_data,
                        column_config={
                            "Data Prevista": st.column_config.DateColumn("Data"),
                            "Dividendo Estimado": st.column_config.NumberColumn("Total", format="R$ %.2f")
                        },
                        use_container_width=True
                    )

                    st.markdown("### 💸 Totais por ativo")
                    df_tot_ativo = df_ag_mes.groupby("Ativo")["Dividendo Estimado"].sum().reset_index().sort_values("Dividendo Estimado", ascending=False)
                    st.dataframe(
                        df_tot_ativo,
                        column_config={
                            "Dividendo Estimado": st.column_config.NumberColumn("Total", format="R$ %.2f")
                        },
                        use_container_width=True
                    )

    with t5: # HISTÓRICO
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