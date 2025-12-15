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
    SHEET_URL_FIIS = os.environ.get("SHEET_URL_FIIS")
    SHEET_URL_MANUAL = os.environ.get("SHEET_URL_MANUAL") # Agora é obrigatório para bater o valor
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError as e:
    print(f"Erro: Variável {e} não encontrada. Verifique os Segredos do GitHub.")
    sys.exit(1)

MODELO_IA = "gemini-1.5-flash" # Modelo mais leve e rápido para automação

# --- FUNÇÕES ---
def to_f(x):
    try: return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_price_web(ticker, tipo="fii"):
    """Scraper robusto para FIIs e Ações"""
    try:
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

def consultar_ia_com_retry(df, patrimonio, investido, tentativas=5):
    print("🤖 Consultando IA...")
    
    # Resumo focado em FIIs para análise
    df_resumo = df[df["Tipo"] == "FII"][["Ativo", "Preço Atual", "P/VP", "DY (12m)"]].copy()
    csv_data = df_resumo.to_csv(index=False)
    
    prompt = f"""
    Atue como consultor financeiro. Escreva um 'Morning Call' curto.
    
    DADOS CARTEIRA:
    {csv_data}
    Patrimônio Total (FIIs + Ações): R$ {patrimonio:.2f} | Investido: R$ {investido:.2f}
    
    Tarefa: Gere um texto HTML simples (sem tags html/body, apenas p, b, ul, li) com:
    1. <b>Diagnóstico:</b> Visão geral rápida.
    2. <b>Destaque:</b> 1 oportunidade de FII hoje.
    3. <b>Veredito:</b> Frase motivacional curta.
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for i in range(tentativas):
        try:
            # Espera progressiva (10s, 20s, 30s...) para vencer o erro 429
            if i > 0: time.sleep(10 * i)
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                print(f"Erro IA {response.status_code}. Tentando novamente...")
        except Exception as e:
            print(f"Exceção IA: {e}")
            time.sleep(5)
    
    return "<i>IA indisponível no momento. Tente novamente mais tarde.</i>"

# --- MAIN ---
def gerar_relatorio():
    print("Iniciando processamento...")
    dados = []
    
    # --- 1. PLANILHA DE FIIs ---
    if SHEET_URL_FIIS:
        try:
            df_fiis = pd.read_csv(SHEET_URL_FIIS, header=None)
            COL_TICKER, COL_QTD, COL_PRECO, COL_PM, COL_VP, COL_DY = 0, 5, 8, 9, 11, 17
            
            for index, row in df_fiis.iterrows():
                try:
                    raw = str(row[COL_TICKER]).strip().upper()
                    if not re.match(r'^[A-Z]{4}11[B]?$', raw): continue
                    
                    qtd = to_f(row[COL_QTD])
                    if qtd > 0:
                        web = get_price_web(raw, "fii")
                        pa = web if web > 0 else to_f(row[COL_PRECO])
                        
                        dy_calc = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                        vp = to_f(row[COL_VP])
                        pvp = pa/vp if vp > 0 else 0.0
                        
                        dados.append({
                            "Ativo": raw, "Tipo": "FII", "Qtd": qtd,
                            "Valor Atual": pa * qtd, "Total Investido": to_f(row[COL_PM]) * qtd,
                            "Preço Atual": pa, "P/VP": pvp, "DY (12m)": dy_calc
                        })
                except: continue
        except Exception as e: print(f"Erro FIIs: {e}")

    # --- 2. PLANILHA MANUAL (AÇÕES/FUNDOS) ---
    if SHEET_URL_MANUAL:
        try:
            df_man = pd.read_csv(SHEET_URL_MANUAL)
            # Ajuste conforme seu CSV. Assumindo: Ativo, Tipo, Qtd, Valor
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
                        
                        # Se for Ação, tenta atualizar preço
                        if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                            tipo = "Ação"
                            web = get_price_web(ativo, "acoes")
                            pa = web if web > 0 else val_input
                            val_total = pa * qtd
                            # Assume PM = Valor Input se não tiver histórico
                            investido = val_total 
                        else:
                            # Fundos/Renda Fixa: Valor Input é o total
                            qtd = 1
                            val_total = val_input
                            investido = val_input
                        
                        dados.append({
                            "Ativo": ativo, "Tipo": tipo, "Qtd": qtd,
                            "Valor Atual": val_total, "Total Investido": investido,
                            "Preço Atual": pa, "P/VP": 0.0, "DY (12m)": 0.0
                        })
                    except: continue
        except Exception as e: print(f"Erro Manual: {e}")

    # --- CONSOLIDAÇÃO ---
    df_calc = pd.DataFrame(dados)
    if df_calc.empty: return

    # Totais Globais
    patrimonio = df_calc["Valor Atual"].sum()
    investido = df_calc["Total Investido"].sum()
    lucro = patrimonio - investido
    
    # IA
    texto_ia = consultar_ia_com_retry(df_calc, patrimonio, investido)
    
    # Oportunidades (Apenas FIIs)
    df_fiis_only = df_calc[df_calc["Tipo"] == "FII"].copy()
    if not df_fiis_only.empty:
        df_fiis_only["% Carteira"] = df_fiis_only["Valor Atual"] / patrimonio
        media_peso = df_fiis_only["% Carteira"].mean()
        df_opp = df_fiis_only[
            (df_fiis_only["P/VP"] >= 0.80) & (df_fiis_only["P/VP"] <= 0.90) & 
            (df_fiis_only["DY (12m)"] > 0.10) & (df_fiis_only["% Carteira"] < media_peso)
        ].head(4)
    else:
        df_opp = pd.DataFrame()

    enviar_email(patrimonio, investido, lucro, df_opp, texto_ia)

def enviar_email(patrimonio, investido, lucro, df_opp, texto_ia):
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
                <tr><td>Patrimônio Total:</td><td style="text-align:right;"><b>{real_br(patrimonio)}</b></td></tr>
                <tr><td>Total Investido:</td><td style="text-align:right;">{real_br(investido)}</td></tr>
                <tr><td>Resultado:</td><td style="text-align:right; color:{cor_res};"><b>{real_br(lucro)}</b></td></tr>
            </table>
            <div style="background:#f0fdfa; padding:15px; border-left:4px solid #0f766e;">
                {texto_ia}
            </div>
            <h3>🎯 Oportunidades (FIIs)</h3>
    """
    
    if not df_opp.empty:
        html += "<ul>"
        for _, row in df_opp.iterrows():
            html += f"<li><b>{row['Ativo']}</b>: P/VP {row['P/VP']:.2f} | DY {row['DY (12m)']:.1%}</li>"
        html += "</ul>"
    else: html += "<p>Sem oportunidades claras hoje.</p>"
        
    html += f"""
            <br><center><a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:10px; text-decoration:none; border-radius:5px;">Abrir Painel</a></center>
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
    gerar_relatorio()