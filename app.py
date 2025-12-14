import streamlit as st
import pandas as pd
import plotly.express as px
import re
import requests
import json
import numpy as np
from bs4 import BeautifulSoup

# ==========================================
# ⚙️ CONFIGURAÇÃO
# ==========================================
st.set_page_config(page_title="Carteira Pro", layout="wide", page_icon="💎")

# Modelo IA
MODELO_IA = "gemini-2.5-flash-lite"

try:
    URL_FIIS = st.secrets["SHEET_URL_FIIS"]
    URL_MANUAL = st.secrets["SHEET_URL_MANUAL"]
    
    # Link da Planilha para o botão
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
        border: 1px solid var(--text-color-20);
        border-radius: 12px;
        padding: 20px 10px;
        text-align: center;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        height: 100%;
    }
    .kpi-label { font-size: 0.8rem; opacity: 0.7; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
    .kpi-value { font-size: 1.5rem; font-weight: 800; color: #1f77b4; margin-bottom: 5px; }
    .kpi-delta { font-size: 0.75rem; font-weight: 600; padding: 2px 10px; border-radius: 10px; display: inline-block; }
    
    .pos { color: #155724; background-color: #d4edda; }
    .neg { color: #721c24; background-color: #f8d7da; }
    .neu { color: #383d41; background-color: #e2e3e5; }
    
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

# --- FUNÇÃO IA ROBUSTA (RETORNA SUCESSO, TEXTO, PROMPT) ---
def analisar_carteira(df):
    try:
        # Prepara dados resumidos
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
        2. 💎 **Oportunidades:** FIIs com P/VP < 1.0, DY > 10% e vacância controlada (se souber).
        3. ⚠️ **Pontos de Atenção:** Ativos com P/VP > 1.10 ou fundamentos ruins.
        4. 🎯 **Ação:** Onde alocar o próximo aporte?
        """
    except Exception as e:
        return False, "Erro ao gerar dados", ""

    if not HAS_AI: 
        return False, "Chave de API não configurada", prompt
    
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
            # Retorna: Sucesso=True, Resposta, Prompt (vazio pois não precisa)
            return True, texto_ia, prompt
        else:
            # Retorna: Sucesso=False, Erro, Prompt (para o fallback)
            return False, "Erro na API", prompt
            
    except Exception as e: 
        return False, str(e), prompt

# --- LAYOUT PRINCIPAL ---
col_tit, col_btn = st.columns([4, 1])
with col_tit: st.title("💎 Carteira Pro")
with col_btn: 
    if st.button("🔄 Atualizar Dados"): st.cache_data.clear(); st.rerun()

df = carregar_tudo()

# --- SIDEBAR (FERRAMENTAS) ---
with st.sidebar:
    st.header("Ferramentas")
    
    # 1. Botão Planilha
    if URL_EDIT:
        st.link_button("📂 Abrir Planilha Fonte", URL_EDIT)
    else:
        st.caption("Sem link de planilha configurado.")
    
    st.divider()
    
    # 2. Botão IA (Só roda se clicar)
    if not df.empty:
        if st.button("🤖 Analisar com IA", type="primary", use_container_width=True):
            with st.spinner(f"Consultando {MODELO_IA}..."):
                # Chama a função e guarda os 3 retornos
                sucesso, resultado, prompt_usado = analisar_carteira(df)
                
                # Salva no Session State
                st.session_state['ia_rodou'] = True
                st.session_state['ia_sucesso'] = sucesso
                st.session_state['ia_resultado'] = resultado
                st.session_state['ia_prompt'] = prompt_usado

if not df.empty:
    # --- DADOS ---
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    val_rs = patrimonio - investido
    val_pct = val_rs / investido if investido > 0 else 0
    renda = df["Renda Mensal"].sum()
    fiis_total = df[df["Tipo"]=="FII"]["Valor Atual"].sum()
    
    cls_val = "pos" if val_rs >= 0 else "neg"
    sinal = "+" if val_rs >= 0 else ""

    # --- 5 CARDS ---
    st.markdown(f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label">Patrimônio Global</div>
            <div class="kpi-value">R$ {patrimonio:,.2f}</div>
            <div class="kpi-delta neu">Acumulado</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Total Investido</div>
            <div class="kpi-value">R$ {investido:,.2f}</div>
            <div class="kpi-delta neu">Custo Total</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Valorização</div>
            <div class="kpi-value">R$ {val_rs:,.2f}</div>
            <div class="kpi-delta {cls_val}">{sinal}{val_pct:.2%}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Renda Mensal Est.</div>
            <div class="kpi-value">R$ {renda:,.2f}</div>
            <div class="kpi-delta pos">Dividendos</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Exposição FIIs</div>
            <div class="kpi-value">R$ {fiis_total:,.2f}</div>
            <div class="kpi-delta neu">{(fiis_total/patrimonio if patrimonio>0 else 0):.1%} da Carteira</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- RESULTADO DA IA (ABAIXO DOS CARDS) ---
    if st.session_state.get('ia_rodou'):
        st.markdown("### 🤖 Análise Inteligente")
        
        if st.session_state['ia_sucesso']:
            # SUCESSO: Mostra a resposta da IA
            st.info(st.session_state['ia_resultado'])
        else:
            # ERRO: Mostra o Fallback para Manual
            st.warning("⚠️ IA Indisponível no momento. Faça a análise manual:")
            
            c_man1, c_man2 = st.columns([3, 1])
            with c_man1:
                st.text_area("Copie este Prompt:", value=st.session_state['ia_prompt'], height=150)
            with c_man2:
                st.write("") # Espaçamento
                st.write("")
                # Link seguro para abrir o Gemini
                st.link_button("🚀 Abrir Gemini", "https://gemini.google.com/app", use_container_width=True)
                st.caption("1. Copie o texto.\n2. Abra o Gemini.\n3. Cole e envie.")
        
        st.divider()

    # --- ABAS DE CONTEÚDO ---
    tab1, tab2, tab3 = st.tabs(["📊 Visão Geral", "🎯 Radar & Oportunidades", "📋 Inventário"])

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
        st.subheader("Quadrante Mágico (FIIs)")
        df_fii = df[(df["Tipo"] == "FII") & (df["P/VP"] > 0) & (df["Valor Atual"] > 0)].copy()
        if not df_fii.empty:
            mean_dy = df_fii["DY (12m)"].mean()
            fig = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo", text="Ativo", hover_data=["Preço Atual"])
            fig.add_shape(type="rect", x0=0, y0=mean_dy, x1=1.0, y1=df_fii["DY (12m)"].max()*1.1, fillcolor="rgba(0,255,0,0.1)", line=dict(width=0), layer="below")
            fig.add_annotation(x=0.5, y=df_fii["DY (12m)"].max(), text="OPORTUNIDADES", showarrow=False, font=dict(color="green", weight="bold"))
            fig.add_shape(type="rect", x0=1.0, y0=0, x1=2.0, y1=df_fii["DY (12m)"].max()*1.1, fillcolor="rgba(255,0,0,0.1)", line=dict(width=0), layer="below")
            fig.add_vline(x=1.0, line_dash="dot")
            st.plotly_chart(fig, use_container_width=True)
        st.divider()
        st.subheader("🔥 Top Descontados")
        df_radar = df[(df["Tipo"] == "FII") & (df["P/VP"] < 1.0) & (df["P/VP"] > 0.1)].copy()
        if not df_radar.empty:
            df_radar = df_radar.sort_values("P/VP")[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"]]
            st.dataframe(
                df_radar.style.format({
                    "Preço Atual": "R$ {:.2f}", "Valor Atual": "R$ {:.2f}", "P/VP": "{:.2f}",
                    "DY (12m)": "{:.2%}", "% Carteira": "{:.2%}"
                }).background_gradient(subset=["P/VP"], cmap="RdYlGn_r").background_gradient(subset=["DY (12m)"], cmap="Greens"),
                use_container_width=True
            )

    with tab3:
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
                "Var %": st.column_config.NumberColumn("Rentab.", format="%.2%"),
                "DY (12m)": st.column_config.NumberColumn(format="%.2%"),
                "% Carteira": st.column_config.ProgressColumn("Peso", format="%.2%", min_value=0, max_value=1),
                "Renda Mensal": st.column_config.NumberColumn("Renda Est.", format="R$ %.2f"),
            },
            hide_index=True, use_container_width=True, height=600
        )
else:
    st.info("Carregando... Verifique seus links.")