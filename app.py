import streamlit as st
import pandas as pd
import plotly.express as px
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

# Configurações de Colunas
COL_TICKER = 0   # Coluna A
COL_QTD = 5      # Coluna F
COL_PRECO = 8    # Coluna I
COL_PM = 9       # Coluna J
COL_VP = 11      # Coluna L
COL_DY = 17      # Coluna R

st.set_page_config(page_title="Carteira Consolidada", layout="wide", page_icon="💎")

st.markdown("""
<style>
    .metric-card { background-color: #f9f9f9; border-radius: 8px; padding: 15px; border: 1px solid #eee; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; color: #0068c9; }
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
            if val:
                return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

def to_f(x): 
    try:
        if pd.isna(x) or str(x).strip() == "": return 0.0
        return float(str(x).replace("R$","").replace("%","").replace(".","").replace(",","."))
    except: return 0.0

# --- CARREGAMENTO DE DADOS ---
@st.cache_data(ttl=60)
def carregar_tudo():
    dados_consolidados = []

    # 1. PLANILHA DE FIIs
    try:
        df_fiis = pd.read_csv(URL_FIIS, header=None)
        for index, row in df_fiis.iterrows():
            try:
                raw = str(row[COL_TICKER]).strip().upper()
                if not re.match(r'^[A-Z]{4}11[B]?$', raw): continue
                
                qtd = to_f(row[COL_QTD])
                if qtd > 0:
                    preco_atual = to_f(row[COL_PRECO])
                    dy_raw = to_f(row[COL_DY])
                    dy_calc = dy_raw/100 if dy_raw > 2 else dy_raw 
                    
                    dados_consolidados.append({
                        "Ativo": raw,
                        "Tipo": "FII",
                        "Qtd": qtd,
                        "Preço Médio": to_f(row[COL_PM]),
                        "Preço Atual": preco_atual,
                        "Valor Atual": qtd * preco_atual,
                        "VP": to_f(row[COL_VP]),
                        "DY (12m)": dy_calc,
                        "Link": f"https://investidor10.com.br/fiis/{raw.lower()}/"
                    })
            except: continue
    except Exception as e:
        st.error(f"Erro FIIs: {e}")

    # 2. PLANILHA MANUAL
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
                    qtd = to_f(row["Qtd"])
                    valor_input = to_f(row["Valor"])
                    
                    preco_atual = valor_input
                    pm = 0.0
                    tipo_final = "Outros"
                    link = None

                    if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                        tipo_final = "Ação"
                        pm = valor_input 
                        preco_live = get_stock_price(ativo)
                        preco_atual = preco_live if preco_live > 0 else valor_input
                        valor_total = qtd * preco_atual
                        link = f"https://investidor10.com.br/acoes/{ativo.lower()}/"
                    else:
                        valor_total = valor_input
                        qtd = 1

                    if valor_total > 0:
                        dados_consolidados.append({
                            "Ativo": ativo,
                            "Tipo": tipo_final,
                            "Qtd": qtd,
                            "Preço Médio": pm,
                            "Preço Atual": preco_atual,
                            "Valor Atual": valor_total,
                            "VP": 0, "DY (12m)": 0, "Link": link
                        })
                except: continue
    except Exception as e:
        st.warning(f"Aba Manual vazia/erro: {e}")

    df_final = pd.DataFrame(dados_consolidados)
    if df_final.empty: return df_final
    
    # Limpeza e Deduplicação
    df_final = df_final.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")
    
    # ---------------------------------------------------------
    # CORREÇÃO PRINCIPAL: Cálculos de Colunas Faltantes (P/VP)
    # ---------------------------------------------------------
    
    # 1. Total Investido
    df_final["Total Investido"] = df_final.apply(
        lambda x: (x["Qtd"] * x["Preço Médio"]) if x["Tipo"] in ["FII", "Ação"] and x["Preço Médio"] > 0 else x["Valor Atual"], 
        axis=1
    )
    
    # 2. P/VP (Essencial para o gráfico funcionar)
    df_final["P/VP"] = df_final.apply(
        lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, 
        axis=1
    )

    # 3. Lucro e Rentabilidade
    df_final["Lucro R$"] = df_final["Valor Atual"] - df_final["Total Investido"]
    df_final["Var %"] = df_final.apply(
        lambda x: (x["Valor Atual"] / x["Total Investido"] - 1) if x["Total Investido"] > 0 else 0.0, 
        axis=1
    )
    
    # 4. Percentual na Carteira
    patrimonio_total = df_final["Valor Atual"].sum()
    df_final["% Carteira"] = df_final["Valor Atual"] / patrimonio_total if patrimonio_total > 0 else 0

    return df_final

# --- APP PRINCIPAL ---
st.title("💰 Painel de Patrimônio Global")

df = carregar_tudo()

if not df.empty:
    
    # --- IA ---
    if st.session_state.get('gerar_ia'):
        with st.expander("🧠 Prompt IA:", expanded=True):
            try:
                df_ia = df[df["Tipo"] != "Outros"][["Ativo", "Tipo", "Qtd", "Preço Atual", "Valor Atual"]].copy()
                df_ia["Valor Atual"] = df_ia["Valor Atual"].apply(lambda x: f"R$ {x:.2f}")
                try: 
                    import tabulate
                    resumo = df_ia.to_markdown(index=False)
                except: 
                    resumo = df_ia.to_string(index=False)
                prompt = f"Analise carteira RV:\nTotal: R$ {df[df['Tipo']!='Outros']['Valor Atual'].sum():,.2f}\n{resumo}\n1. Balanceamento.\n2. Riscos.\n3. Sugestões."
                st.code(prompt, language="text")
            except: pass

    # --- KPIs ---
    patrimonio = df["Valor Atual"].sum()
    lucro_total = df["Lucro R$"].sum()
    rent_total = (lucro_total / df["Total Investido"].sum()) if df["Total Investido"].sum() > 0 else 0
    
    grp = df.groupby("Tipo")["Valor Atual"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio Total", f"R$ {patrimonio:,.2f}")
    c2.metric("Lucro Global", f"R$ {lucro_total:,.2f}", delta=f"{rent_total:.2%}")
    c3.metric("FIIs", f"R$ {grp.get('FII', 0):,.2f}", delta=f"{grp.get('FII', 0)/patrimonio:.1%}")
    c4.metric("Ações/Outros", f"R$ {grp.get('Ação', 0) + grp.get('Outros', 0):,.2f}", delta=f"{(grp.get('Ação', 0)+grp.get('Outros', 0))/patrimonio:.1%}")

    st.divider()

    # --- ABAS ---
    tab1, tab2, tab3 = st.tabs(["📊 Distribuição", "💠 Análise FIIs", "📋 Detalhes"])

    with tab1:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.subheader("Por Classe")
            fig1 = px.pie(df, values="Valor Atual", names="Tipo", hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig1, use_container_width=True)
        with col_g2:
            st.subheader("Por Ativo (Treemap)")
            fig2 = px.treemap(df, path=['Tipo', 'Ativo'], values='Valor Atual')
            st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        st.subheader("Quadrante Mágico: Barato vs Rentável (Apenas FIIs)")
        st.info("Topo Esq: Oportunidades (DY Alto/PVP Baixo) | Topo Dir: Caros | Baixo Esq: Descontados sem rendimento")
        
        # Filtra e garante que temos dados para plotar
        df_fii = df[df["Tipo"] == "FII"].copy()
        
        if not df_fii.empty and "P/VP" in df_fii.columns:
            # Proteção extra para garantir que Valor Atual > 0 para o tamanho da bolha
            df_fii = df_fii[df_fii["Valor Atual"] > 0]
            
            fig_scat = px.scatter(df_fii, x="P/VP", y="DY (12m)", size="Valor Atual", color="Ativo",
                             hover_name="Ativo", text="Ativo")
            fig_scat.add_hline(y=df_fii["DY (12m)"].mean(), line_dash="dot", annotation_text="Média DY")
            fig_scat.add_vline(x=1, line_dash="dot", annotation_text="Preço Justo")
            st.plotly_chart(fig_scat, use_container_width=True)
        else:
            st.warning("Sem dados suficientes de FIIs para gerar o gráfico.")
        
        st.divider()
        st.subheader("🔎 Radar: Oportunidades (P/VP < 1.0)")
        df_baratos = df[(df["P/VP"] < 1.0) & (df["P/VP"] > 0) & (df["Tipo"] == "FII")].copy()
        
        if not df_baratos.empty:
            st.dataframe(
                df_baratos,
                column_order=("Link", "Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual", "% Carteira"),
                column_config={
                    "Link": st.column_config.LinkColumn("Info", display_text="🌐"),
                    "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "P/VP": st.column_config.NumberColumn(format="%.2f"),
                    "DY (12m)": st.column_config.NumberColumn(format="%.2%"),
                    "% Carteira": st.column_config.ProgressColumn(format="%.2%", min_value=0, max_value=1),
                },
                hide_index=True,
                use_container_width=True
            )

    with tab3:
        st.subheader("Carteira Detalhada")
        df_rv = df[df["Tipo"].isin(["FII", "Ação"])].copy()

        st.dataframe(
            df_rv,
            column_order=("Link", "Ativo", "Tipo", "Preço Atual", "Qtd", "Valor Atual", "Var %", "DY (12m)"),
            column_config={
                "Link": st.column_config.LinkColumn("Site", display_text="🌐"),
                "Preço Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                "Qtd": st.column_config.NumberColumn(format="%.0f"),
                "Var %": st.column_config.NumberColumn("Rentabilidade", format="%.2%"),
                "DY (12m)": st.column_config.NumberColumn("DY (12m)", format="%.2%"),
            },
            hide_index=True,
            use_container_width=True
        )
        
        df_outros = df[df["Tipo"] == "Outros"]
        if not df_outros.empty:
            st.markdown("### Outros")
            st.dataframe(
                df_outros[["Ativo", "Valor Atual", "% Carteira"]],
                column_config={
                    "Valor Atual": st.column_config.NumberColumn(format="R$ %.2f"),
                    "% Carteira": st.column_config.NumberColumn(format="%.2%")
                },
                hide_index=True,
                use_container_width=True
            )

else:
    st.info("Carregando dados... Verifique seus links secretos.")