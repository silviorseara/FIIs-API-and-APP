import smtplib
import json
import os
import sys
import pandas as pd
import requests
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURAÇÕES ---
try:
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
    GOOGLE_CREDENTIALS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    SHEET_ID = os.environ["SHEET_ID"]
except KeyError as e:
    print(f"Erro Config: Variável {e} não encontrada.")
    sys.exit(1)

MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES ---
def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def consultar_ia(df, patrimonio, investido):
    print("🤖 Consultando IA...")
    try:
        # Prepara resumo para não estourar limite de texto
        # Pega Top 15 ativos por valor
        df_top = df.sort_values("Valor Atual", ascending=False).head(15)
        # Seleciona colunas úteis se existirem
        cols_uteis = [c for c in ["Ativo", "Tipo", "Preço Atual", "P/VP", "DY (12m)"] if c in df_top.columns]
        csv_data = df_top[cols_uteis].to_csv(index=False)
        
        prompt = f"""
        Você é um consultor financeiro pessoal (Family Office).
        Escreva um 'Morning Call' curto e direto.
        
        DADOS REAIS DA CARTEIRA (Top 15):
        {csv_data}
        
        TOTAIS:
        Patrimônio: R$ {patrimonio:.2f}
        Investido: R$ {investido:.2f}
        Resultado: R$ {patrimonio - investido:.2f}
        
        Gere um HTML (sem tags html/body) com:
        <p><b>Diagnóstico:</b> Breve análise da saúde da carteira.</p>
        <p><b>Destaque:</b> Uma oportunidade ou ponto de atenção.</p>
        <p><b>Veredito:</b> Uma frase motivacional de fechamento.</p>
        """
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        # Tenta enviar
        resp = requests.post(url, headers=headers, data=json.dumps(data), timeout=15)
        
        if resp.status_code == 200:
            return resp.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"Erro IA: {resp.status_code}")
            return "<p><i>IA indisponível no momento.</i></p>"
            
    except Exception as e:
        print(f"Exceção IA: {e}")
        return "<p><i>Análise de IA não gerada hoje.</i></p>"

def ler_cache_google():
    print("📡 Conectando ao Google Sheets...")
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS, scope)
        client = gspread.authorize(creds)
        
        sh = client.open_by_key(SHEET_ID)
        ws = sh.worksheet("Cache_Dados")
        
        # Lê Totais (Linha 2)
        header_vals = ws.get("A2:C2")
        if not header_vals: return False, None, 0, 0, "Cache vazio."
            
        totais = header_vals[0]
        data_att = totais[0]
        
        # Limpeza robusta de string para float
        def clean_float(val):
            return float(str(val).replace("R$", "").replace(".", "").replace(",", ".").strip())
            
        patrimonio = clean_float(totais[1])
        investido = clean_float(totais[2])
        
        # Lê Tabela (Linha 4 em diante)
        dados_tabela = ws.get_all_records(head=4)
        df = pd.DataFrame(dados_tabela)
        
        return True, df, patrimonio, investido, data_att
        
    except Exception as e:
        print(f"Erro leitura: {e}")
        return False, None, 0, 0, str(e)

def enviar_email(patr, inv, data_att, texto_ia):
    print("📧 Enviando e-mail...")
    lucro = patr - inv
    cor = "green" if lucro >= 0 else "red"
    
    # Limpa markdown da IA se houver
    texto_ia = texto_ia.replace("```html", "").replace("```", "")
    
    html = f"""
    <html><body style="font-family:Arial, color:#333;">
    <div style="background:#0f766e; padding:20px; text-align:center; color:white; border-radius:8px 8px 0 0;">
        <h2>💎 Morning Call</h2>
        <p style="margin:0; font-size:14px; opacity:0.9;">Dados de: {data_att}</p>
    </div>
    <div style="padding:20px; border:1px solid #ddd;">
        <table style="width:100%; margin-bottom:20px; font-size:16px;">
            <tr><td>Patrimônio:</td><td align="right"><b>{real_br(patr)}</b></td></tr>
            <tr><td>Investido:</td><td align="right">{real_br(inv)}</td></tr>
            <tr><td>Resultado:</td><td align="right" style="color:{cor}"><b>{real_br(lucro)}</b></td></tr>
        </table>
        
        <div style="background-color:#f0fdfa; padding:15px; border-left: 4px solid #0f766e; border-radius:4px; margin-top:20px;">
            <h3 style="margin-top:0; color:#0f766e; font-size:16px;">🤖 Análise do Assistente</h3>
            {texto_ia}
        </div>
        
        <br><center>
            <a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:12px 24px; text-decoration:none; border-radius:5px; font-weight:bold;">
                Acessar Painel
            </a>
        </center>
    </div>
    </body></html>
    """
    
    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{EMAIL_USER}>"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📊 Morning Call: {real_br(patr)}"
    msg.attach(MIMEText(html, 'html'))
    
    try:
        s = smtplib.SMTP('smtp.gmail.com', 587); s.starttls()
        s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg); s.quit()
        print("✅ E-mail enviado!")
    except Exception as e: print(f"❌ Erro envio: {e}")

if __name__ == "__main__":
    sucesso, df, p, i, d = ler_cache_google()
    if sucesso:
        # Gera o texto da IA usando os dados lidos
        texto = consultar_ia(df, p, i)
        # Envia tudo
        enviar_email(p, i, d, texto)
    else:
        print(f"Falha ao ler dados: {d}")