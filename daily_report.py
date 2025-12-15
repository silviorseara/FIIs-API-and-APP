import pandas as pd
import smtplib
import requests
import json
import os
import sys
import time
import re
import yfinance as yf # A salvação para preços
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from bs4 import BeautifulSoup

# --- CONFIGURAÇÕES ---
try:
    SHEET_URL_FIIS = os.environ.get("SHEET_URL_FIIS")
    SHEET_URL_MANUAL = os.environ.get("SHEET_URL_MANUAL")
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError as e:
    print(f"Erro: {e}")
    sys.exit(1)

MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES ---
def to_f(x):
    try: return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_price_robust(ticker, tipo="fii"):
    """
    Tenta 3 fontes em ordem:
    1. Investidor10 (Igual App)
    2. Yahoo Finance (Backup seguro)
    3. Zero (Falha)
    """
    # 1. Tenta Scraping (Visual)
    try:
        url_base = "fiis" if tipo == "fii" else "acoes"
        url = f"https://investidor10.com.br/{url_base}/{ticker.lower()}/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    
    # 2. Tenta Yahoo Finance (API Oficial)
    try:
        ticker_sa = f"{ticker}.SA"
        hist = yf.Ticker(ticker_sa).history(period="1d")
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
    except: pass
    
    return 0.0

def consultar_ia(df, patrimonio, investido):
    print("🤖 IA...")
    # Resume apenas o essencial para caber no prompt
    df_top = df[["Ativo", "Preço Atual", "P/VP", "DY (12m)"]].head(15) 
    csv_data = df_top.to_csv(index=False)
    
    prompt = f"""
    Aja como um consultor financeiro. Escreva um e-mail matinal curto.
    Dados: {csv_data}
    Patrimônio: R$ {patrimonio:.2f} | Investido: R$ {investido:.2f}
    
    Gere HTML (sem tags html/body) com:
    1. <b>Resumo:</b> Saúde da carteira.
    2. <b>Destaque:</b> 1 oportunidade (P/VP baixo).
    3. <b>Conselho:</b> Frase final.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
    for i in range(3):
        try:
            if i > 0: time.sleep(5 * i)
            resp = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}))
            if resp.status_code == 200: return resp.json()['candidates'][0]['content']['parts'][0]['text']
        except: pass
    return "<i>IA indisponível. Dados atualizados acima.</i>"

# --- MAIN ---
def gerar_relatorio():
    print("Iniciando...")
    dados = []
    
    # 1. FIIs
    if SHEET_URL_FIIS:
        try:
            df = pd.read_csv(SHEET_URL_FIIS, header=None)
            COL_T, COL_Q, COL_P_PLAN, COL_PM, COL_VP, COL_DY = 0, 5, 8, 9, 11, 17
            for i, r in df.iterrows():
                try:
                    raw = str(r[COL_T]).strip().upper()
                    if len(raw) < 5: continue
                    qtd = to_f(r[COL_Q])
                    if qtd > 0:
                        # Tenta Web/Yahoo. Se falhar, usa Planilha.
                        web = get_price_robust(raw, "fii")
                        pa = web if web > 0 else to_f(r[COL_P_PLAN])
                        
                        dados.append({
                            "Ativo": raw, "Tipo": "FII", "Qtd": qtd,
                            "Valor Atual": pa * qtd, 
                            "Total Investido": to_f(r[COL_PM]) * qtd,
                            "Preço Atual": pa, 
                            "P/VP": (pa / to_f(r[COL_VP])) if to_f(r[COL_VP]) > 0 else 0,
                            "DY (12m)": to_f(r[COL_DY])/100 if to_f(r[COL_DY]) > 2 else to_f(r[COL_DY])
                        })
                except: continue
        except: pass

    # 2. Manual
    if SHEET_URL_MANUAL:
        try:
            df_m = pd.read_csv(SHEET_URL_MANUAL)
            if len(df_m.columns) >= 4:
                df_m = df_m.iloc[:, :4]
                df_m.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
                for i, r in df_m.iterrows():
                    try:
                        at = str(r["Ativo"]).strip().upper()
                        if at in ["ATIVO", "", "TOTAL"]: continue
                        
                        qtd = to_f(r["Qtd"])
                        val_input = to_f(r["Valor"])
                        
                        pa = val_input
                        investido_item = val_input # Default: Investido = Valor Input
                        
                        # Se for Ação, busca preço real
                        if "AÇÃO" in str(r["Tipo"]).upper() or "ACAO" in str(r["Tipo"]).upper():
                            web = get_price_robust(at, "acoes")
                            pa = web if web > 0 else val_input
                            # CORREÇÃO CRÍTICA: Se Qtd > 1, 'Valor' costuma ser PM unitário
                            # Se Qtd = 1, 'Valor' é total investido
                            if qtd > 1: investido_item = val_input * qtd
                        
                        dados.append({
                            "Ativo": at, "Tipo": "Outros", "Qtd": qtd,
                            "Valor Atual": pa * qtd, 
                            "Total Investido": investido_item,
                            "Preço Atual": pa, "P/VP": 0, "DY (12m)": 0
                        })
                    except: continue
        except: pass

    # Consolida
    df = pd.DataFrame(dados)
    if df.empty: return
    df = df.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")

    patr = df["Valor Atual"].sum()
    inv = df["Total Investido"].sum()
    lucro = patr - inv
    
    # IA
    txt_ia = consultar_ia(df, patr, inv)
    
    # Email
    enviar(patr, inv, lucro, txt_ia)

def enviar(patr, inv, luc, txt):
    data = datetime.now().strftime("%d/%m/%Y")
    cor = "green" if luc >= 0 else "red"
    txt = txt.replace("```html", "").replace("```", "")
    
    html = f"""
    <html><body style="font-family:Arial; color:#333;">
    <div style="background:#0f766e; padding:15px; text-align:center; color:white; border-radius:8px 8px 0 0;">
        <h2>💎 Morning Call: {real_br(patr)}</h2>
        <p>{data}</p>
    </div>
    <div style="padding:20px; border:1px solid #ddd;">
        <table style="width:100%">
            <tr><td>Patrimônio:</td><td align="right"><b>{real_br(patr)}</b></td></tr>
            <tr><td>Investido:</td><td align="right">{real_br(inv)}</td></tr>
            <tr><td>Resultado:</td><td align="right" style="color:{cor}"><b>{real_br(luc)}</b></td></tr>
        </table>
        <br>
        <div style="background:#f0fdfa; padding:15px; border-left:4px solid #0f766e;">
            {txt}
        </div>
        <br><center><a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:10px; text-decoration:none; border-radius:5px">Abrir Painel</a></center>
    </div>
    </body></html>
    """
    
    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{EMAIL_USER}>"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📈 Relatório: {real_br(patr)}"
    msg.attach(MIMEText(html, 'html'))
    
    try:
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls(); s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg); s.quit()
        print("✅ Enviado!")
    except Exception as e: print(f"❌ Erro: {e}")

if __name__ == "__main__":
    gerar_relatorio()