import pandas as pd
import smtplib
import requests
import json
import os
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- CONFIGURAÇÕES VIA ENV (RENDER) ---
try:
    SHEET_URL_FIIS = os.environ["SHEET_URL_FIIS"]
    EMAIL_USER = os.environ["EMAIL_USER"]
    EMAIL_PASS = os.environ["EMAIL_PASS"]
    EMAIL_DESTINO = os.environ["EMAIL_DESTINO"]
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"] # Nova Variável Necessária!
except KeyError as e:
    print(f"Erro: Variável de ambiente não encontrada: {e}")
    sys.exit(1)

MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES AUXILIARES ---
def to_f(x):
    try:
        return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- CONSULTA IA (GEMINI) ---
def consultar_ia(df, patrimonio, investido):
    print("🤖 Consultando Inteligência Artificial...")
    try:
        # Prepara resumo leve para não estourar tokens
        df_resumo = df[["Ativo", "Preço Atual", "P/VP", "DY (12m)", "Valor Atual"]].copy()
        csv_data = df_resumo.to_csv(index=False)
        
        prompt = f"""
        Atue como um consultor financeiro pessoal (Family Office). 
        Escreva um resumo matinal curto e direto para o investidor sobre esta carteira de FIIs:
        
        DADOS DA CARTEIRA:
        {csv_data}
        Patrimônio Total: R$ {patrimonio:.2f}
        Total Investido: R$ {investido:.2f}
        
        Gere um texto curto em HTML (use tags <b>, <br>, <ul>, <li>) com a seguinte estrutura:
        1. <b>Diagnóstico Rápido:</b> Como está a saúde geral (P/VP médio, risco)?
        2. <b>Destaque do Dia:</b> Qual o melhor ativo para aportar hoje (barato e bom)?
        3. <b>Alerta:</b> Algum ativo preocupante?
        4. <b>Veredito:</b> Uma frase motivacional ou de cautela sobre o mercado hoje.
        
        Não use tabelas, apenas texto corrido e listas. Seja breve.
        """
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO_IA}:generateContent?key={GOOGLE_API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"<i>IA Indisponível no momento (Erro {response.status_code}).</i>"
    except Exception as e:
        return f"<i>Erro ao conectar com a IA: {str(e)}</i>"

# --- PROCESSAMENTO ---
def gerar_relatorio():
    print("📥 Baixando planilha...")
    try:
        df = pd.read_csv(SHEET_URL_FIIS, header=None)
        
        # Índices (Baseado no app.py)
        COL_TICKER = 0; COL_QTD = 5; COL_PRECO = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17
        
        dados = []
        for index, row in df.iterrows():
            try:
                raw = str(row[COL_TICKER]).strip().upper()
                if len(raw) < 5: continue 
                
                qtd = to_f(row[COL_QTD])
                if qtd > 0:
                    dy_calc = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                    pa = to_f(row[COL_PRECO])
                    vp = to_f(row[COL_VP])
                    
                    # Evita divisão por zero
                    pvp = pa/vp if vp > 0 else 0.0
                    
                    dados.append({
                        "Ativo": raw,
                        "Valor Atual": pa * qtd,
                        "Preço Atual": pa,
                        "Total Investido": to_f(row[COL_PM]) * qtd,
                        "P/VP": pvp,
                        "DY (12m)": dy_calc
                    })
            except: continue
            
        df_calc = pd.DataFrame(dados)
        
        if df_calc.empty:
            print("Nenhum dado processado.")
            return

        # Totais
        patrimonio = df_calc["Valor Atual"].sum()
        investido = df_calc["Total Investido"].sum()
        lucro = patrimonio - investido
        
        # --- CHAMA A IA ---
        analise_ia_html = consultar_ia(df_calc, patrimonio, investido)

        # --- ENVIO ---
        enviar_email(patrimonio, investido, lucro, analise_ia_html)

    except Exception as e:
        print(f"Erro crítico no script: {e}")

def enviar_email(patrimonio, investido, lucro, analise_html):
    print("📧 Enviando e-mail...")
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    cor_lucro = "green" if lucro >= 0 else "red"
    
    # Limpeza básica do Markdown para HTML caso a IA mande markdown
    analise_html = analise_html.replace("```html", "").replace("```", "")
    
    html_body = f"""
    <html>
    <body style="font-family: Helvetica, Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
            <div style="background-color: #0f766e; padding: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0;">💎 Carteira Pro: Morning Call</h2>
                <p style="color: #ccfbf1; margin: 5px 0 0 0;">{data_hoje}</p>
            </div>
            
            <div style="padding: 20px;">
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr style="background-color: #f8fafc;">
                        <td style="padding: 12px; border-bottom: 1px solid #eee;">Patrimônio</td>
                        <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right; font-weight: bold; font-size: 1.1em;">{real_br(patrimonio)}</td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #eee;">Resultado Acumulado</td>
                        <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right; font-weight: bold; color: {cor_lucro};">{real_br(lucro)}</td>
                    </tr>
                </table>
                
                <div style="background-color: #f0fdfa; border-left: 4px solid #0f766e; padding: 15px; margin-top: 20px; border-radius: 4px;">
                    <h3 style="margin-top: 0; color: #0f766e;">🤖 Análise Inteligente do Dia</h3>
                    {analise_html}
                </div>
                
                <div style="margin-top: 30px; text-align: center;">
                    <a href="SEU_LINK_DO_STREAMLIT_AQUI" style="background-color: #0f766e; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Acessar Painel Completo</a>
                </div>
            </div>
            
            <div style="background-color: #f8fafc; padding: 15px; text-align: center; font-size: 12px; color: #888;">
                <p>Este é um relatório automático gerado pelo seu assistente pessoal.</p>
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = "Carteira IA <" + EMAIL_USER + ">"
    msg['To'] = EMAIL_DESTINO
    msg['Subject'] = f"📊 Morning Call: {real_br(patrimonio)}"
    msg.attach(MIMEText(html_body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print("✅ Sucesso! E-mail enviado.")
    except Exception as e:
        print(f"❌ Erro SMTP: {e}")

if __name__ == "__main__":
    gerar_relatorio()