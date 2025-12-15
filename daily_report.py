import pandas as pd
import smtplib
import requests
import json
import os
import sys
import time
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURAÇÕES ---
try:
    SHEET_URL_FIIS = os.environ.get("SHEET_URL_FIIS")
    SHEET_URL_MANUAL = os.environ.get("SHEET_URL_MANUAL")
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError as e:
    print(f"Erro Crítico: Variável {e} não configurada.")
    sys.exit(1)

# MUDANÇA: Usar 1.5-flash para fugir do bloqueio de RPD do lite
MODELO_IA = "gemini-1.5-flash"

# --- FUNÇÕES ---
def to_f(x):
    try: return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_price_yahoo(ticker):
    """Busca preço atualizado no Yahoo Finance"""
    try:
        # Adiciona .SA se não tiver
        ticker_sa = f"{ticker}.SA" if not ticker.endswith(".SA") else ticker
        # Baixa apenas o último dia
        dados = yf.Ticker(ticker_sa).history(period="1d")
        if not dados.empty:
            return float(dados['Close'].iloc[-1])
    except: pass
    return 0.0

def consultar_ia(df, patrimonio, investido):
    print("🤖 Consultando IA...")
    
    # Resumo focado em FIIs para a IA analisar
    df_fii = df[df["Tipo"] == "FII"].sort_values("Valor Atual", ascending=False).head(15)
    csv_data = df_fii[["Ativo", "Preço Atual", "P/VP", "DY (12m)"]].to_csv(index=False)
    
    prompt = f"""
    Aja como um consultor financeiro. Escreva um e-mail matinal curto.
    
    DADOS DA CARTEIRA (Resumo FIIs):
    {csv_data}
    
    TOTAIS GERAIS (FIIs + Ações + Outros):
    Patrimônio: R$ {patrimonio:.2f}
    Investido: R$ {investido:.2f}
    Resultado: R$ {patrimonio - investido:.2f}
    
    Gere um texto em HTML (sem tags html/body) contendo:
    1. <p><b>Diagnóstico:</b> Breve comentário sobre os totais.</p>
    2. <p><b>Destaque:</b> 1 oportunidade de FII (P/VP baixo).</p>
    3. <p><b>Veredito:</b> Frase motivacional.</p>
    """
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    # Retry Simples
    for i in range(3):
        try:
            if i > 0: time.sleep(5)
            resp = requests.post(url, headers=headers, data=json.dumps(data))
            if resp.status_code == 200:
                return resp.json()['candidates'][0]['content']['parts'][0]['text']
            elif resp.status_code == 429:
                print("Cota excedida. Tentando novamente...")
        except: pass
        
    return "<p><i>IA indisponível no momento. Dados financeiros atualizados acima.</i></p>"

# --- MAIN ---
def gerar_relatorio():
    print("Iniciando processamento...")
    dados = []
    
    # --- 1. PROCESSAR FIIs (Automático) ---
    if SHEET_URL_FIIS:
        try:
            df = pd.read_csv(SHEET_URL_FIIS, header=None)
            COL_T, COL_Q, COL_P_PLAN, COL_PM, COL_VP, COL_DY = 0, 5, 8, 9, 11, 17
            
            for index, row in df.iterrows():
                try:
                    raw = str(row[COL_T]).strip().upper()
                    if len(raw) < 4: continue
                    
                    qtd = to_f(row[COL_Q])
                    if qtd > 0:
                        # Yahoo Finance para FIIs também (garante preço atualizado)
                        pa = get_price_yahoo(raw)
                        if pa == 0: pa = to_f(row[COL_P_PLAN]) # Fallback planilha
                        
                        dados.append({
                            "Ativo": raw,
                            "Tipo": "FII",
                            "Valor Atual": pa * qtd,
                            "Total Investido": to_f(row[COL_PM]) * qtd,
                            "Preço Atual": pa,
                            "P/VP": (pa / to_f(row[COL_VP])) if to_f(row[COL_VP]) > 0 else 0,
                            "DY (12m)": to_f(row[COL_DY])/100 if to_f(row[COL_DY]) > 2 else to_f(row[COL_DY])
                        })
                except: continue
        except Exception as e: print(f"Erro FIIs: {e}")

    # --- 2. PROCESSAR MANUAL (Ações/Fundos) - CORREÇÃO VALE3 ---
    if SHEET_URL_MANUAL:
        try:
            df_m = pd.read_csv(SHEET_URL_MANUAL)
            # Lê colunas: Ativo(A), Tipo(B), Qtd(C), Valor(D)
            if len(df_m.columns) >= 4:
                df_m = df_m.iloc[:, :4]
                df_m.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
                
                for index, row in df_m.iterrows():
                    try:
                        at = str(row["Ativo"]).strip().upper()
                        if at in ["ATIVO", "", "TOTAL", "NAN"]: continue
                        
                        tipo_raw = str(row["Tipo"]).strip().upper()
                        qtd = to_f(row["Qtd"])
                        val_input = to_f(row["Valor"]) # Coluna D (Preço Médio ou Total)
                        
                        pa = val_input
                        investido_item = val_input
                        valor_atual_item = val_input
                        
                        # --- LÓGICA DE AÇÕES (VALE3) ---
                        if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                            # 1. Busca preço atualizado
                            web = get_price_yahoo(at)
                            pa = web if web > 0 else val_input
                            
                            # 2. Cálculo Correto:
                            # Investido = Qtd * Preço Médio (que está na coluna D)
                            investido_item = qtd * val_input 
                            # Valor Atual = Qtd * Preço Yahoo
                            valor_atual_item = qtd * pa
                            
                        # --- LÓGICA DE FUNDOS (Outros) ---
                        else:
                            # Se Qtd=1, Coluna D é o valor total investido/atual
                            # Se for Renda Fixa sem cotação diária, assume Valor Atual = Investido
                            valor_atual_item = val_input
                            investido_item = val_input
                            pa = val_input

                        dados.append({
                            "Ativo": at,
                            "Tipo": "Outros",
                            "Valor Atual": valor_atual_item,
                            "Total Investido": investido_item,
                            "Preço Atual": pa,
                            "P/VP": 0.0,
                            "DY (12m)": 0.0
                        })
                    except: continue
        except Exception as e: print(f"Erro Manual: {e}")

    # --- CONSOLIDAÇÃO ---
    df = pd.DataFrame(dados)
    if df.empty: return

    # Remove duplicatas
    df = df.drop_duplicates(subset=["Ativo", "Tipo"], keep="first")

    # Totais Finais
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    
    # Debug no log do GitHub
    print(f"Patrimônio Final: {real_br(patrimonio)}")
    
    # IA
    txt_ia = consultar_ia(df, patrimonio, investido)
    
    # E-mail
    enviar_email(patrimonio, investido, lucro, df, txt_ia)

def enviar_email(patr, inv, luc, df, txt):
    data = datetime.now().strftime("%d/%m/%Y")
    cor = "green" if luc >= 0 else "red"
    
    # Oportunidades (Apenas FIIs)
    df_fii = df[df["Tipo"] == "FII"].copy()
    opp_html = ""
    if not df_fii.empty:
        df_fii["%"] = df_fii["Valor Atual"] / patr
        media_peso = df_fii["%"].mean()
        tops = df_fii[(df_fii["P/VP"]>=0.8) & (df_fii["P/VP"]<=0.9) & (df_fii["DY (12m)"]>0.10)].head(4)
        if not tops.empty:
            opp_html = "<ul>"
            for _, r in tops.iterrows():
                opp_html += f"<li><b>{r['Ativo']}</b>: P/VP {r['P/VP']:.2f} | DY {r['DY (12m)']:.1%}</li>"
            opp_html += "</ul>"
        else: opp_html = "<p>Sem oportunidades claras hoje.</p>"

    txt = txt.replace("```html", "").replace("```", "")

    html = f"""
    <html><body style="font-family:Arial; color:#333;">
    <div style="background:#0f766e; padding:20px; text-align:center; color:white; border-radius:8px 8px 0 0;">
        <h2>💎 Morning Call: {real_br(patr)}</h2>
        <p>{data}</p>
    </div>
    <div style="padding:20px; border:1px solid #ddd;">
        <table style="width:100%; margin-bottom:20px;">
            <tr><td>Patrimônio Total:</td><td align="right"><b>{real_br(patr)}</b></td></tr>
            <tr><td>Total Investido:</td><td align="right">{real_br(inv)}</td></tr>
            <tr><td>Resultado:</td><td align="right" style="color:{cor}"><b>{real_br(luc)}</b></td></tr>
        </table>
        <div style="background:#f0fdfa; padding:15px; border-left:4px solid #0f766e;">
            {txt}
        </div>
        <h3>🎯 Radar de Oportunidades</h3>
        {opp_html}
        <br><center><a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:10px 20px; text-decoration:none; border-radius:5px">Abrir Painel Completo</a></center>
    </div>
    </body></html>
    """
    
    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{os.environ['EMAIL_USER']}>"
    msg['To'] = os.environ['EMAIL_DESTINO']
    msg['Subject'] = f"📈 Relatório: {real_br(patr)}"
    msg.attach(MIMEText(html, 'html'))
    
    try:
        s = smtplib.SMTP('smtp.gmail.com', 587); s.starttls()
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS'])
        s.send_message(msg); s.quit()
        print("✅ E-mail enviado!")
    except Exception as e: print(f"❌ Erro SMTP: {e}")

if __name__ == "__main__":
    gerar_relatorio()