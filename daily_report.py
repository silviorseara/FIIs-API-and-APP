import pandas as pd
import smtplib
import requests
import json
import os
import sys
import time
import yfinance as yf # A chave para preços corretos
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

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

MODELO_IA = "gemini-2.5-flash-lite"

# --- FUNÇÕES ---
def to_f(x):
    try: return float(str(x).replace("R$", "").replace("%", "").replace(" ", "").replace(".", "").replace(",", ".")) if pd.notna(x) else 0.0
    except: return 0.0

def real_br(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def atualizar_precos_yfinance(df_calc):
    """Atualiza os preços usando Yahoo Finance (Blindado contra bloqueios)"""
    print("🔄 Atualizando preços via Yahoo Finance...")
    
    # Prepara lista de tickers com sufixo .SA
    tickers_map = {t: f"{t}.SA" for t in df_calc["Ativo"].unique()}
    tickers_lista = list(tickers_map.values())
    
    try:
        # Baixa tudo de uma vez (Muito mais rápido e seguro)
        dados_yf = yf.download(tickers_lista, period="1d", progress=False)['Close']
        
        # Pega o último preço disponível (iloc[-1])
        if not dados_yf.empty:
            precos_atuais = dados_yf.iloc[-1]
            
            # Atualiza o DataFrame linha a linha
            for index, row in df_calc.iterrows():
                ticker_sa = tickers_map.get(row["Ativo"])
                if ticker_sa in precos_atuais:
                    novo_preco = precos_atuais[ticker_sa]
                    # Só atualiza se o preço for válido (>0)
                    if novo_preco > 0:
                        df_calc.at[index, "Preço Atual"] = float(novo_preco)
                        # Recalcula valor total e P/VP com o novo preço
                        df_calc.at[index, "Valor Atual"] = float(novo_preco) * row["Qtd"]
                        vp = row["VP_Original"]
                        df_calc.at[index, "P/VP"] = (novo_preco / vp) if vp > 0 else 0.0
            
            print("✅ Preços atualizados com sucesso!")
        else:
            print("⚠️ Yahoo Finance não retornou dados.")
            
    except Exception as e:
        print(f"⚠️ Erro ao atualizar preços: {e}")
        # Se der erro, mantém os preços da planilha (fallback)
    
    return df_calc

def consultar_ia_com_retry(df, patrimonio, investido, tentativas=5): # Aumentado para 5
    print("🤖 Consultando IA...")
    
    # Resumo leve
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
            # Espera progressiva: 10s, 20s, 30s, 40s...
            # Isso ajuda muito a evitar o erro 429
            tempo_espera = 10 * (i + 1)
            if i > 0:
                print(f"⏳ Aguardando {tempo_espera}s para tentar novamente...")
                time.sleep(tempo_espera)
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            elif response.status_code == 429:
                print(f"⚠️ Cota excedida (429). Tentativa {i+1}/{tentativas}")
            elif response.status_code == 503:
                print(f"⚠️ Serviço instável (503). Tentativa {i+1}/{tentativas}")
            else:
                print(f"⚠️ Erro IA {response.status_code}")
                
        except Exception as e:
            print(f"Exceção IA: {e}")
    
    return "<i>IA indisponível após várias tentativas. Tente novamente mais tarde.</i>"

# --- MAIN ---
def gerar_relatorio():
    print("Iniciando processamento...")
    try:
        df = pd.read_csv(SHEET_URL_FIIS, header=None)
        
        # Índices (A=0, F=5, I=8, J=9, L=11, R=17)
        COL_TICKER = 0; COL_QTD = 5; COL_PRECO_PLANILHA = 8; COL_PM = 9; COL_VP = 11; COL_DY = 17
        
        dados = []
        for index, row in df.iterrows():
            try:
                raw = str(row[COL_TICKER]).strip().upper()
                if len(raw) < 5: continue 
                
                qtd = to_f(row[COL_QTD])
                if qtd > 0:
                    pa_planilha = to_f(row[COL_PRECO_PLANILHA])
                    vp = to_f(row[COL_VP])
                    dy = to_f(row[COL_DY]) / 100 if to_f(row[COL_DY]) > 2.0 else to_f(row[COL_DY])
                    
                    dados.append({
                        "Ativo": raw,
                        "Qtd": qtd,
                        "Valor Atual": pa_planilha * qtd, # Será atualizado
                        "Total Investido": to_f(row[COL_PM]) * qtd,
                        "Preço Atual": pa_planilha,       # Será atualizado
                        "VP_Original": vp,                # Guardado para recalculo
                        "P/VP": 0.0,                      # Será recalculado
                        "DY (12m)": dy
                    })
            except: continue
            
        df_calc = pd.DataFrame(dados)
        if df_calc.empty: return

        # --- ATUALIZAÇÃO REAL DE PREÇOS ---
        df_calc = atualizar_precos_yfinance(df_calc)

        # Totais Finais
        patrimonio = df_calc["Valor Atual"].sum()
        investido = df_calc["Total Investido"].sum()
        lucro = patrimonio - investido
        
        # IA
        texto_ia = consultar_ia_com_retry(df_calc, patrimonio, investido)
        
        # Oportunidades
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
            <center><a href="#" style="background:#0f766e; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Abrir Painel</a></center>
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