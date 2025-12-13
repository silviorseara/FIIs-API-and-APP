from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import time
import requests
import re
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURAÇÕES ---
BASE_URL = "https://investidor10.com.br/fiis"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CACHE_MEMORIA = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api-investidor10")

# --- SESSÃO HTTP ---
def create_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(total=3, backoff_factor=1, status_forcelist=(403, 429, 500, 502))
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    return s

session = create_session()

# --- LIMPEZA DE DADOS ---
def limpar_valor(texto):
    """Converte 'R$ 163,34' ou '8,06%' para float"""
    if not texto: return None
    try:
        # Remove R$, %, espaços
        texto = texto.replace("R$", "").replace("%", "").strip()
        texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except:
        return None

# --- SCRAPER ATUALIZADO (VP + DY) ---
def scrape_dados(ticker: str):
    ticker = ticker.lower().strip()
    url = f"{BASE_URL}/{ticker}/"
    
    dados = {"vp": None, "dy": None}
    
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200 or resp.url == "https://investidor10.com.br/":
            return None
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. BUSCAR VP (Nas células brancas - div.cell)
        cards_cell = soup.select("div.cell")
        for card in cards_cell:
            desc = card.select_one("div.desc")
            if desc and ("PATRIMONIAL P/ COTA" in desc.get_text(strip=True).upper()):
                val = card.select_one("div.value span")
                if val: dados["vp"] = limpar_valor(val.get_text())

        # 2. BUSCAR DY (Nos cards coloridos do topo - div._card)
        # Baseado na sua imagem 4: div._card -> header "DY (12M)" -> body value
        cards_top = soup.select("div._card")
        for card in cards_top:
            header = card.select_one("div._card-header")
            if header and "DY" in header.get_text(strip=True).upper():
                body = card.select_one("div._card-body")
                if body:
                    # Às vezes o valor está num span direto ou dentro de outro elemento
                    dados["dy"] = limpar_valor(body.get_text())

        # 3. FALLBACK (Tabela - caso falhe nos cards)
        if dados["vp"] is None or dados["dy"] is None:
            tabela = soup.select_one("#table-indicators")
            if tabela:
                for tr in tabela.select("tr"):
                    cols = tr.select("td")
                    if len(cols) >= 2:
                        key = cols[0].get_text(strip=True).upper()
                        val = cols[1].get_text(strip=True)
                        
                        if "PATRIMONIAL P/ COTA" in key and dados["vp"] is None:
                            dados["vp"] = limpar_valor(val)
                        if "DIVIDEND YIELD" in key and dados["dy"] is None:
                            dados["dy"] = limpar_valor(val)

        # 4. ULTIMATO (Busca textual bruta - resolve casos como HGRU11/TRXF11)
                # Se ainda não achou VP, procura qualquer texto "VPA" ou "Patrimonial" e pega o próximo número
                if dados["vp"] is None:
                    # Pega todos os textos da página que parecem dinheiro
                    textos = soup.get_text(" ", strip=True)
                    # Removemos excesso de espaço
                    import re
                    # Regex procura: "Patrimonial p/ cota R$ 123,45" (com variações de espaço)
                    match = re.search(r'(?:Patrimonial\s*p/?\s*cota|VPA).*?R\$\s*([\d.,]+)', textos, re.IGNORECASE)
                    if match:
                        dados["vp"] = limpar_valor(match.group(1))

        return dados

    except Exception as e:
        logger.error(f"Erro scraper {ticker}: {e}")
        return None

# --- AGENDADOR ---
def atualizar_cache_job():
    lista = list(CACHE_MEMORIA.keys())
    if not lista: return
    logger.info(f"🔄 Atualizando {len(lista)} fundos...")
    for t in lista:
        d = scrape_dados(t)
        if d:
            CACHE_MEMORIA[t] = {"dados": d, "timestamp": time.time()}
        time.sleep(2)

# --- APP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler()
    scheduler.add_job(atualizar_cache_job, 'interval', hours=6)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def home():
    return {"status": "online", "fundos": len(CACHE_MEMORIA)}

@app.get("/dados/{ticker}")
def get_dados(ticker: str):
    ticker = ticker.upper().strip()
    
    # Cache Check
    if ticker in CACHE_MEMORIA:
        return {"ticker": ticker, **CACHE_MEMORIA[ticker]["dados"], "source": "cache"}
    
    # Live Check
    d = scrape_dados(ticker)
    if d:
        CACHE_MEMORIA[ticker] = {"dados": d, "timestamp": time.time()}
        return {"ticker": ticker, **d, "source": "live"}
    
    raise HTTPException(404, detail="Nao encontrado")