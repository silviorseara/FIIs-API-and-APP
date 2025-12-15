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
try:
    SHEET_URL_FIIS = os.environ["SHEET_URL_FIIS"]
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError as e:
    print(f"Erro: Variável {e} não encontrada.")
    sys.exit(1)

# MESMO MODELO DO SEU APP
MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES IDÊNTICAS AO APP.PY ---
def to_f(x):
    try: return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_stock_price(ticker):
    """Mesma lógica de scraping do seu App"""
    try:
        url = f"https://investidor10.com.br/acoes/{ticker.lower()}/"
        # Header completo para evitar bloqueio
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

def get_fii_price(ticker):
    """Adaptado para FIIs"""
    try:
        url = f"https://investidor10.com.br/fiis/{ticker.lower()}/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            val = soup.select_one("div._card.cotacao div.value span")
            if val: return float(val.get_text().replace("R$", "").replace(".", "").replace(",", ".").strip())
    except: pass
    return 0.0

def consultar_ia_com_retry(df, patrimonio, investido, tentativas=5):
    print(f"🤖 Consultando {MODELO_IA}...")
    
    # Resumo leve para a IA
    df_resumo = df[["Ativo", "Preço Atual", "P/VP", "DY (12m)"]].copy()
    csv_data = df_resumo.to_csv(index=False)
    
    prompt = f"""
    Atue como consultor financeiro pessoal. Escreva um 'Morning Call' curto.
    
    DADOS ATUALIZADOS:
    {csv_data}
    Patrimônio Hoje: R$ {patrimonio:.2f} | Investido: R$ {investido:.2f}
    
    Tarefa: Gere um texto HTML (sem tags html/body) com:
    1. <b>Diagnóstico:</b> Resumo da saúde da carteira.
    2. <b>Destaque:</b> 1 ativo bom e barato para hoje.
    3. <b>Veredito:</b> Frase final de orientação.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for i in range(tentativas):
        try:
            # Pausa progressiva para evitar Erro 429
            time.sleep(5 + (i * 5)) 
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            elif response.status_code == 429:
                print(f"⏳ Cota IA excedida. Tentando novamente... ({i+1}/{tentativas})")
            else:
                print(f"Erro IA {response.status_code}")
        except Exception as e:
            print(f"Exceção IA: {e}")
    
    return "<i>IA indisponível no momento (Limite de cota ou instabilidade).</i>"

# --- MAIN ---
def gerar_relatorio():
    print("Iniciando processamento...")
    try:
        df = pd.read_csv(SHEET_URL_FIIS, header=None)
        
        # Índices da sua planilha
        COL_TICKER = 0; COL_QTD = 5; COL_PRECO_PLANILHA = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17
        
        dados = []
        for index, row in df.iterrows():
            try:
                raw = str(row[COL_TICKER]).strip().upper()
                if not re.match(r'^[A-Z]{4}11[B]?$', raw): continue
                
                qtd = to_f(row[COL_QTD])
                if qtd > 0:
                    # 1. Tenta pegar preço atualizado (Scraping Igual App)
                    preco_web = get_fii_price(raw)
                    
                    # Se falhar o scraper, usa o da planilha (fallback)
                    if preco_web > 0:
                        pa = preco_web
                    else:
                        pa = to_f(row[COL_PRECO_PLANILHA])
                    
                    dy_calc = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                    vp = to_f(row[COL_VP])
                    pvp = pa/vp if vp > 0 else 0.0
                    
                    dados.append({
                        "Ativo": raw,
                        "Qtd": qtd,
                        "Valor Atual": pa * qtd,
                        "Total Investido": to_f(row[COL_PM]) * qtd,
                        "Preço Atual": pa,
                        "P/VP": pvp,
                        "DY (12m)": dy_calc
                    })
            except: continue
            
        df_calc = pd.DataFrame(dados)
        if df_calc.empty: return

        # Totais Finais
        patrimonio = df_calc["Valor Atual"].sum()
        investido = df_calc["Total Investido"].sum()
        lucro = patrimonio - investido
        
        # IA (Com o modelo certo e retry)
        texto_ia = consultar_ia_com_retry(df_calc, patrimonio, investido)
        
        # Oportunidades (Mesma lógica do App)
        df_calc["% Carteira"] = df_calc["Valor Atual"] / patrimonio
        media_peso = df_calc["% Carteira"].mean()
        df_opp = df_calc[
            (df_calc["P/VP"] >= 0.80) & (df_calc["P/VP"] <= 0.90) & 
            (df_calc["DY (12m)"] > 0.10) & (df_calc["% Carteira"] < media_peso)
        ].head(4)

        enviar_email(patrimonio, investido, lucro, df_opp, texto_ia)

    except Exception as e:
        print(f"Erro Crítico: {e}")

def enviar_email(patrimonio, investido, lucro, df_opp, texto_ia):
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    cor_res = "green" if lucro >= 0 else "red"
    
    # Limpa markdown simples se vier da IA
    if texto_ia:
        texto_ia = texto_ia.replace("```html", "").replace("```", "")
    
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <div style="background-color: #0f766e; padding: 15px; text-align: center; border-radius: 8px 8px 0 0;">
            <h2 style="color: white; margin:0;">📊 Morning Call: {real_br(patrimonio)}</h2>
            <p style="color: #ccfbf1; margin:5px 0 0 0;">{data_hoje}</p>
        </div>
        
        <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
            <table style="width:100%; margin-bottom: 20px;">
                <tr><td><b>Patrimônio:</b></td><td style="text-align:right;">{real_br(patrimonio)}</td></tr>
                <tr><td><b>Investido:</b></td><td style="text-align:right;">{real_br(investido)}</td></tr>
                <tr><td><b>Resultado:</b></td><td style="text-align:right; color:{cor_res}; font-weight:bold;">{real_br(lucro)}</td></tr>
            </table>
            
            <div style="background-color: #f0fdfa; padding: 15px; border-radius: 8px; border-left: 4px solid #0f766e;">
                <h3 style="margin-top:0; color: #0f766e;">🤖 Análise do Dia</h3>
                {texto_ia}
            </div>
            
            <h3 style="color: #333; margin-top: 25px;">🎯 Oportunidades</h3>
    """
    
    if not df_opp.empty:
        html += "<ul>"
        for _, row in df_opp.iterrows():
            html += f"<li><b>{row['Ativo']}</b>: P/VP {row['P/VP']:.2f} | DY {row['DY (12m)']:.1%}</li>"
        html += "</ul>"
    else:
        html += "<p>Nenhuma oportunidade clara hoje.</p>"
        
    html += """
            <br>
            <center><a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Abrir Painel</a></center>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{EMAIL_USER}>"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📈 Relatório {data_hoje}: {real_br(patrimonio)}"
    msg.attach(MIMEText(html, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print("✅ Enviado!")
    except Exception as e:
        print(f"❌ Erro SMTP: {e}")

if __name__ == "__main__":
    gerar_relatorio()