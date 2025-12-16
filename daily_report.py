import smtplib
import json
import os
import sys
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# CONFIGURAÇÃO
try:
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    # Pega o JSON de credenciais dos Segredos e converte para dicionário
    GOOGLE_CREDENTIALS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    SHEET_URL = os.environ["SHEET_URL_FIIS"] # Usa a mesma URL da planilha principal
except KeyError as e:
    print(f"Erro Config: {e}")
    sys.exit(1)

def ler_cache_google():
    print("📡 Conectando ao Google Sheets...")
    try:
        scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets', "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(GOOGLE_CREDENTIALS, scope)
        client = gspread.authorize(creds)
        
        sh = client.open_by_url(SHEET_URL)
        ws = sh.worksheet("Cache_Dados")
        
        # Lê Totais (Linha 2)
        # A1=Header, A2=Dados. Colunas: A=Data, B=Patrimonio, C=Investido
        totais = ws.get("A2:C2")[0] 
        data_att = totais[0]
        patrimonio = float(totais[1])
        investido = float(totais[2])
        
        # Lê Tabela (A partir da linha 4)
        dados_tabela = ws.get_all_records(head=4)
        df = pd.DataFrame(dados_tabela)
        
        return True, df, patrimonio, investido, data_att
        
    except Exception as e:
        print(f"Erro leitura: {e}")
        return False, None, 0, 0, ""

def enviar_email(df, patr, inv, data_att):
    print("📧 Preparando e-mail...")
    lucro = patr - inv
    cor = "green" if lucro >= 0 else "red"
    
    # Gera HTML Simples
    html = f"""
    <html><body style="font-family:Arial, color:#333;">
    <div style="background:#0f766e; padding:20px; text-align:center; color:white; border-radius:8px 8px 0 0;">
        <h2>💎 Relatório Consolidado</h2>
        <p>Dados do Painel (Snapshot: {data_att})</p>
    </div>
    <div style="padding:20px; border:1px solid #ddd;">
        <table style="width:100%; margin-bottom:20px; font-size:16px;">
            <tr><td>Patrimônio:</td><td align="right"><b>R$ {patr:,.2f}</b></td></tr>
            <tr><td>Investido:</td><td align="right">R$ {inv:,.2f}</td></tr>
            <tr><td>Resultado:</td><td align="right" style="color:{cor}"><b>R$ {lucro:,.2f}</b></td></tr>
        </table>
        <p style="text-align:center; color:#666; font-size:12px;">
            *Valores exatos conforme visualizado no App Carteira Pro.
        </p>
        <br><center><a href="https://fiis-api-and-app.onrender.com" style="background:#0f766e; color:white; padding:10px 20px; text-decoration:none; border-radius:5px">Acessar App</a></center>
    </div>
    </body></html>
    """
    
    msg = MIMEMultipart()
    msg['From'] = f"Carteira Bot <{EMAIL_USER}>"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📈 Relatório Fiel: R$ {patr:,.2f}"
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
        enviar_email(df, p, i, d)
    else:
        print("Falha ao ler cache. O App já salvou os dados hoje?")