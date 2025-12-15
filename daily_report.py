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
    print(f"Erro: Variável {e} não configurada.")
    sys.exit(1)

# Modelo padrão 
MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES ---
def to_f(x):
    """Converte string financeira (R$ 1.000,00) para float (1000.00)"""
    try:
        if pd.isna(x): return 0.0
        # Remove R$, %, espaços e pontos de milhar
        clean = str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "")
        # Troca vírgula decimal por ponto
        clean = clean.replace(",", ".")
        return float(clean)
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_price_yahoo(ticker):
    """Pega preço atualizado (Yahoo não bloqueia robôs)"""
    try:
        ticker_sa = f"{ticker}.SA" if not ticker.endswith(".SA") else ticker
        # Tenta baixar histórico de 1 dia
        data = yf.Ticker(ticker_sa).history(period="1d")
        if not data.empty:
            return float(data['Close'].iloc[-1])
    except: pass
    return 0.0

def consultar_ia(df_resumo, patrimonio, investido):
    print("🤖 Consultando IA...")
    try:
        # Prepara dados para o prompt
        csv_text = df_resumo.to_csv(index=False)
        
        prompt = f"""
        Você é um consultor financeiro. Escreva um resumo matinal curto (HTML).
        
        DADOS DA CARTEIRA:
        {csv_text}
        
        TOTAIS:
        Patrimônio: R$ {patrimonio:.2f} | Investido: R$ {investido:.2f}
        
        Responda APENAS com um HTML (sem tags html/body/head) formatado assim:
        <p><b>Diagnóstico:</b> [Sua análise curta]</p>
        <p><b>Destaque:</b> [Melhor FII barato]</p>
        <p><b>Veredito:</b> [Frase final]</p>
        """
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        # Tenta 1 vez com timeout curto
        resp = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
        
        if resp.status_code == 200:
            return resp.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"IA Falhou: {resp.status_code}")
            return "<p><i>IA indisponível no momento (Limite de cota atingido).</i></p>"
            
    except Exception as e:
        print(f"Erro IA: {e}")
        return "<p><i>IA indisponível.</i></p>"

# --- MAIN ---
def gerar_relatorio():
    print("🚀 Iniciando...")
    dados = []
    
    # 1. PROCESSAR FIIs (Planilha Automática)
    if SHEET_URL_FIIS:
        try:
            df = pd.read_csv(SHEET_URL_FIIS, header=None)
            # Índices fixos
            COL_T, COL_Q, COL_P_PLAN, COL_PM, COL_VP, COL_DY = 0, 5, 8, 9, 11, 17
            
            for index, row in df.iterrows():
                try:
                    raw = str(row[COL_T]).strip().upper()
                    if len(raw) < 4: continue
                    
                    qtd = to_f(row[COL_Q])
                    if qtd > 0:
                        # Prioridade: Yahoo Finance (Preço Real)
                        pa = get_price_yahoo(raw)
                        # Fallback: Planilha (Preço do Google Finance)
                        if pa == 0: pa = to_f(row[COL_P_PLAN])
                        
                        dy_calc = to_f(row[COL_DY])
                        if dy_calc > 2.0: dy_calc /= 100 # Corrige % se vier 10.0 em vez de 0.10
                        
                        dados.append({
                            "Ativo": raw,
                            "Tipo": "FII",
                            "Qtd": qtd,
                            "Preço Atual": pa,
                            "Valor Atual": pa * qtd,
                            "Total Investido": to_f(row[COL_PM]) * qtd,
                            "P/VP": (pa / to_f(row[COL_VP])) if to_f(row[COL_VP]) > 0 else 0,
                            "DY": dy_calc
                        })
                except: continue
        except Exception as e: print(f"Erro FIIs: {e}")

    # 2. PROCESSAR MANUAL (Ações e Fundos)
    if SHEET_URL_MANUAL:
        try:
            df_m = pd.read_csv(SHEET_URL_MANUAL)
            # Verifica se tem cabeçalho ou é direto
            # Assumindo colunas: Ativo, Tipo, Qtd, Valor
            if len(df_m.columns) >= 4:
                df_m = df_m.iloc[:, :4]
                df_m.columns = ["Ativo", "Tipo", "Qtd", "Valor"]
                
                for index, row in df_m.iterrows():
                    try:
                        at = str(row["Ativo"]).strip().upper()
                        # Pula linhas inúteis
                        if at in ["ATIVO", "", "TOTAL", "NAN"]: continue
                        
                        tipo_raw = str(row["Tipo"]).strip().upper()
                        qtd = to_f(row["Qtd"])
                        val_input = to_f(row["Valor"]) # Valor da Célula
                        
                        # Lógica Dupla:
                        # CASO A: É Ação? (VALE3)
                        if "AÇÃO" in tipo_raw or "ACAO" in tipo_raw:
                            # Tenta pegar preço atual
                            web = get_price_yahoo(at)
                            pa = web if web > 0 else val_input
                            
                            val_total = pa * qtd
                            investido_total = val_input * qtd # PM * QTD
                            
                        # CASO B: É Fundo/Renda Fixa? (Outros)
                        else:
                            # Aqui o 'Valor' geralmente já é o Total Atualizado
                            # E Qtd costuma ser 1
                            if qtd <= 0: qtd = 1
                            pa = val_input
                            val_total = val_input * qtd # R$ 26k * 1
                            investido_total = val_input * qtd # Assume sem lucro p/ simplificar se não tiver PM
                        
                        print(f"Manual processado: {at} | Valor: {val_total}")
                        
                        dados.append({
                            "Ativo": at,
                            "Tipo": "Outros",
                            "Qtd": qtd,
                            "Preço Atual": pa,
                            "Valor Atual": val_total,
                            "Total Investido": investido_total,
                            "P/VP": 0.0,
                            "DY": 0.0
                        })
                    except: continue
        except Exception as e: print(f"Erro Manual: {e}")

    # --- CONSOLIDAÇÃO ---
    df = pd.DataFrame(dados)
    if df.empty:
        print("❌ Sem dados.")
        return

    # Remove duplicatas (Prioriza FIIs se houver conflito)
    df = df.drop_duplicates(subset=["Ativo"], keep="first")

    # Totais Finais
    patrimonio = df["Valor Atual"].sum()
    investido = df["Total Investido"].sum()
    lucro = patrimonio - investido
    
    # Preparar IA (Apenas FIIs Top 10 para não lotar o prompt)
    df_fii = df[df["Tipo"] == "FII"].sort_values("Valor Atual", ascending=False).head(10)
    ia_html = consultar_ia(df_fii[["Ativo", "Preço Atual", "P/VP", "DY"]], patrimonio, investido)
    
    # Enviar
    enviar_email(patrimonio, investido, lucro, df, ia_html)

def enviar_email(patr, inv, luc, df, ia_html):
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    cor_res = "green" if luc >= 0 else "red"
    
    # Top Oportunidades (Apenas FIIs)
    df_fii = df[df["Tipo"] == "FII"].copy()
    opp_html = ""
    if not df_fii.empty:
        # P/VP entre 0.8 e 0.95 (Descontados mas não "quebrados")
        # DY > 9%
        tops = df_fii[(df_fii["P/VP"] >= 0.80) & (df_fii["P/VP"] <= 0.95) & (df_fii["DY"] > 0.09)].head(4)
        if not tops.empty:
            opp_html = "<ul>"
            for _, r in tops.iterrows():
                opp_html += f"<li><b>{r['Ativo']}</b>: P/VP {r['P/VP']:.2f} | DY {r['DY']:.1%}</li>"
            opp_html += "</ul>"
        else:
            opp_html = "<p>Sem oportunidades claras hoje.</p>"

    # Limpa markdown da IA
    ia_html = ia_html.replace("```html", "").replace("```", "")

    html_body = f"""
    <html>
    <body style="font-family: Arial, color: #333;">
        <div style="background-color: #0f766e; padding: 15px; text-align: center; border-radius: 8px 8px 0 0;">
            <h2 style="color: white; margin: 0;">💎 Morning Call</h2>
            <p style="color: #e0f2f1; margin: 5px 0 0 0;">{data_hoje}</p>
        </div>
        
        <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
            <table style="width: 100%; margin-bottom: 20px;">
                <tr><td>Patrimônio Total:</td><td style="text-align: right;"><b>{real_br(patr)}</b></td></tr>
                <tr><td>Total Investido:</td><td style="text-align: right;">{real_br(inv)}</td></tr>
                <tr><td>Resultado:</td><td style="text-align: right; color: {cor_res};"><b>{real_br(luc)}</b></td></tr>
            </table>
            
            <div style="background-color: #f0fdfa; padding: 15px; border-radius: 8px; border-left: 4px solid #0f766e;">
                <h3 style="margin-top: 0; color: #0f766e;">🤖 Análise do Dia</h3>
                {ia_html}
            </div>
            
            <h3 style="margin-top: 25px; color: #333;">🎯 Radar de Oportunidades</h3>
            {opp_html}
            
            <br>
            <center>
                <a href="https://fiis-api-and-app.onrender.com" 
                   style="background-color: #0f766e; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                   Abrir Painel Completo
                </a>
            </center>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{os.environ['EMAIL_USER']}>"
    msg['To'] = os.environ['EMAIL_DESTINO']
    msg['Subject'] = f"📊 Relatório: {real_br(patr)}"
    msg.attach(MIMEText(html_body, 'html'))

    try:
        s = smtplib.SMTP('smtp.gmail.com', 587)
        s.starttls()
        s.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASS'])
        s.send_message(msg)
        s.quit()
        print("✅ E-mail enviado com sucesso!")
    except Exception as e:
        print(f"❌ Erro de envio: {e}")

if __name__ == "__main__":
    gerar_relatorio()