import pandas as pd
import smtplib
import requests
import json
import os
import sys
import time
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from bs4 import BeautifulSoup

# --- CONFIGURAÇÕES ---
# Pega variáveis de ambiente (GitHub Actions)
try:
    SHEET_URL_FIIS = os.environ.get("SHEET_URL_FIIS")
    SHEET_URL_MANUAL = os.environ.get("SHEET_URL_MANUAL") # Opcional
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError as e:
    print(f"Erro de Configuração: {e}")
    sys.exit(1)

MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES DE AJUDA ---
def to_f(x):
    try:
        val = str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(val) if val else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- SCRAPER (Igual ao App para garantir mesmo preço) ---
def get_price_web(ticker, tipo="fii"):
    try:
        # Tenta Investidor10
        url_base = "fiis" if tipo == "fii" else "acoes"
        url = f"https://investidor10.com.br/{url_base}/{ticker.lower()}/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

# --- LÓGICA DE DADOS ---
def carregar_dados():
    print("📥 Baixando e processando dados...")
    dados = []
    
    # Índices (A=0, F=5, I=8, J=9, L=11, R=17)
    COL_TICKER, COL_QTD, COL_PM, COL_PRECO, COL_VP, COL_DY = 0, 5, 9, 8, 11, 17

    # 1. FIIs
    if SHEET_URL_FIIS:
        try:
            df_fiis = pd.read_csv(SHEET_URL_FIIS, header=None)
            for index, row in df_fiis.iterrows():
                try:
                    raw = str(row[COL_TICKER]).strip().upper()
                    if not re.match(r'^[A-Z]{4}11[B]?$', raw): continue
                    
                    qtd = to_f(row[COL_QTD])
                    if qtd > 0:
                        # Preço: Tenta Web, senão Planilha
                        web_price = get_price_web(raw, "fii")
                        pa = web_price if web_price > 0 else to_f(row[COL_PRECO])
                        
                        dy_calc = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                        
                        dados.append({
                            "Ativo": raw,
                            "Tipo": "FII",
                            "Qtd": qtd,
                            "Preço Atual": pa,
                            "Preço Médio": to_f(row[COL_PM]),
                            "VP": to_f(row[COL_VP]),
                            "DY (12m)": dy_calc
                        })
                except: continue
        except Exception as e: print(f"Erro FIIs: {e}")

    # 2. Manual
    if SHEET_URL_MANUAL:
        try:
            df_man = pd.read_csv(SHEET_URL_MANUAL)
            # Ajuste conforme seu CSV manual (assumindo colunas padrão)
            if len(df_man.columns) >= 4:
                df_man = df_man.iloc[:, :4]
                df_man.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
                for index, row in df_man.iterrows():
                    try:
                        ativo = str(row["Ativo"]).strip().upper()
                        if ativo in ["ATIVO", "TOTAL", "", "NAN"]: continue
                        
                        tipo_raw = str(row["Tipo"]).strip().upper()
                        qtd = to_f(row["Qtd"])
                        val_input = to_f(row["Valor"])
                        
                        pa = val_input
                        tipo = "Outros"
                        
                        if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                            tipo = "Ação"
                            web_price = get_price_web(ativo, "acoes")
                            pa = web_price if web_price > 0 else val_input
                        else:
                            qtd = 1 # Fundos manuais/Renda fixa costumam ser qtd 1
                        
                        dados.append({
                            "Ativo": ativo,
                            "Tipo": tipo,
                            "Qtd": qtd,
                            "Preço Atual": pa,
                            "Preço Médio": 0.0, # Geralmente manual não tem PM detalhado aqui
                            "VP": 0.0,
                            "DY (12m)": 0.0
                        })
                    except: continue
        except Exception as e: print(f"Erro Manual: {e}")

    # --- LIMPEZA CRÍTICA (IGUAL AO APP) ---
    df = pd.DataFrame(dados)
    if df.empty: return df
    
    # Remove duplicatas (Isso resolve o problema do valor maior)
    df = df.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")
    
    # Cálculos Finais
    df["Valor Atual"] = df["Qtd"] * df["Preço Atual"]
    
    # Lógica de Investido (Se PM existe usa ele, senão usa Valor Atual)
    df["Total Investido"] = df.apply(lambda x: x["Qtd"] * x["Preço Médio"] if x["Preço Médio"] > 0 else x["Valor Atual"], axis=1)
    
    # P/VP
    df["P/VP"] = df.apply(lambda x: (x["Preço Atual"] / x["VP"]) if x["VP"] > 0 else 0.0, axis=1)
    
    return df

# --- CONSULTA IA (COM RETRY AGRESSIVO) ---
def consultar_ia(df, patrimonio, investido):
    print("🤖 Consultando IA...")
    
    df_resumo = df[["Ativo", "Preço Atual", "P/VP", "DY (12m)"]].copy()
    csv_data = df_resumo.to_csv(index=False)
    
    prompt = f"""
    Você é um consultor financeiro. Escreva um 'Morning Call' curto para o investidor.
    
    DADOS CARTEIRA:
    {csv_data}
    Patrimônio: R$ {patrimonio:.2f} | Investido: R$ {investido:.2f}
    
    Responda em HTML (sem tags html/body) com 3 bullets:
    1. <b>Diagnóstico:</b> Visão geral.
    2. <b>Destaque:</b> Melhor oportunidade (P/VP e DY).
    3. <b>Veredito:</b> Orientação rápida.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    # Tenta 5 vezes com espera crescente
    for i in range(5):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(data))
            if resp.status_code == 200:
                return resp.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                print(f"Erro IA {resp.status_code}. Tentando novamente...")
                time.sleep(5 + (i * 5)) # 5s, 10s, 15s...
        except: time.sleep(5)
        
    return "<i>IA indisponível no momento.</i>"

# --- ENVIO DE E-MAIL ---
def enviar_email(df):
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    
    # IA
    texto_ia = consultar_ia(df, patrimonio, investido)
    
    # Oportunidades
    df["% Carteira"] = df["Valor Atual"] / patrimonio
    media_peso = df["% Carteira"].mean()
    df_opp = df[
        (df["Tipo"] == "FII") & 
        (df["P/VP"] >= 0.80) & (df["P/VP"] <= 0.90) & 
        (df["DY (12m)"] > 0.10) & (df["% Carteira"] < media_peso)
    ].sort_values("P/VP").head(4)

    # HTML
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    cor_res = "green" if lucro >= 0 else "red"
    texto_ia = texto_ia.replace("```html", "").replace("```", "")
    
    html = f"""
    <html>
    <body style="font-family: Arial, color: #333;">
        <div style="background:#0f766e; padding:20px; text-align:center; border-radius:8px 8px 0 0; color:white;">
            <h2>💎 Morning Call: {real_br(patrimonio)}</h2>
            <p>{data_hoje}</p>
        </div>
        <div style="padding:20px; border:1px solid #ddd;">
            <table style="width:100%; margin-bottom:20px;">
                <tr><td>Patrimônio:</td><td style="text-align:right;"><b>{real_br(patrimonio)}</b></td></tr>
                <tr><td>Investido:</td><td style="text-align:right;">{real_br(investido)}</td></tr>
                <tr><td>Resultado:</td><td style="text-align:right; color:{cor_res};"><b>{real_br(lucro)}</b></td></tr>
            </table>
            <div style="background:#f0fdfa; padding:15px; border-left:4px solid #0f766e;">
                {texto_ia}
            </div>
            <h3>🎯 Oportunidades</h3>
    """
    
    if not df_opp.empty:
        html += "<ul>"
        for _, row in df_opp.iterrows():
            html += f"<li><b>{row['Ativo']}</b>: P/VP {row['P/VP']:.2f} | DY {row['DY (12m)']:.1%}</li>"
        html += "</ul>"
    else: html += "<p>Sem oportunidades claras hoje.</p>"
        
    html += """
            <br><center><a href="SEU_LINK_STREAMLIT" style="background:#0f766e; color:white; padding:10px; text-decoration:none; border-radius:5px;">Abrir Painel</a></center>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{EMAIL_USER}>"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📈 Relatório: {real_br(patrimonio)}"
    msg.attach(MIMEText(html, 'html'))

    try:
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls(); s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg); s.quit()
        print("✅ E-mail enviado!")
    except Exception as e: print(f"❌ Erro SMTP: {e}")

if __name__ == "__main__":
    df = carregar_dados()
    if not df.empty:
        enviar_email(df)
    else:
        print("Erro: DataFrame vazio.")