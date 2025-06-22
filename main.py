from fastapi import FastAPI, Request
from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os
# NEWS
import httpx
from datetime import datetime, timedelta
import openai
from twilio.rest import Client

load_dotenv()


openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

kite = KiteConnect(api_key=os.getenv("ZERODHA_API_KEY"))

# Twilio client for sending SMS
def send_whatsapp_message(message: str, to_number: str = None):
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_WHATSAPP_NUMBER")
    to_number = to_number or os.getenv("USER_WHATSAPP_NUMBER")

    client = Client(account_sid, auth_token)

    message = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number
    )

    return message.sid

# Generate AI recommendation based on stock data
async def generate_ai_recommendation(stock_name: str, news: list, financials: dict):
    news_summary = "\n".join([f"- {n['title']}" for n in news[:5]]) if news else "No news found."

    financial_text = "\n".join([f"{k}: {v}" for k, v in financials.items() if v])

    prompt = f"""
                You are a stock market analyst.

                Analyze the following company: {stock_name}

                News Headlines:
                {news_summary}

                Financial Data:
                {financial_text}

                Answer the following:
                1. Should the user Buy, Hold, or Sell this stock? (Answer only one word: Buy / Hold / Sell)
                2. Is the company's financial health good or bad?
                3. What is its future outlook?
                4. Is the company competitive in its sector?
                Give short, professional answers.
            """

    client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )

    return response.choices[0].message.content


# Fetch latest news articles about a stock
async def fetch_news(stock_symbol: str):
    url = f"https://api.newscatcherapi.com/v2/search?q={stock_symbol}&lang=en"
    headers = {"x-api-key": os.getenv("NEWS_API_KEY")}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        data = response.json()
        return data.get("articles", [])

async def fetch_news_by_topic(topic: str):
    from_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = f"https://newsapi.org/v2/everything?q={topic}&from={from_date}&sortBy=popularity"
    headers = {"x-api-key": os.getenv("NEWS_API_KEY")}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        print(f"Fetching news for topic: {topic} from {from_date}")
        if response.status_code != 200:
            print(f"Error fetching news: {response.status_code} - {response.text}")
            return []
        print(f"Response: {response.text}")
        data = response.json()
        return data.get("articles", [])

# Fetch basic financials (e.g., via Alpha Vantage)
async def fetch_financials(stock_symbol: str):
    url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={stock_symbol}&apikey={os.getenv('FIN_API_KEY')}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

@app.get("/login")
async def login():
    login_url = kite.login_url()
    return {"login_url": login_url}

@app.get("/generate_token")
async def generate_token(request: Request):
    request_token = request.query_params.get("request_token")
    if not request_token:
        return {"error": "Missing request_token"}

    data = kite.generate_session(request_token, api_secret=os.getenv("ZERODHA_API_SECRET"))
    os.environ["ZERODHA_ACCESS_TOKEN"] = data["access_token"]
    kite.set_access_token(data["access_token"])
    return {"message": "Access token generated", "access_token": data["access_token"]}

@app.get("/holdings")
async def get_holdings():
    kite.set_access_token(os.getenv("ZERODHA_ACCESS_TOKEN"))
    holdings = kite.holdings()
    return {"holdings": holdings}

@app.get("/watchlist")
async def get_watchlist():
    kite.set_access_token(os.getenv("ZERODHA_ACCESS_TOKEN"))
    instruments = kite.positions()
    return {"watchlist": instruments}

@app.get("/enrich-stock/{symbol}")
async def enrich_stock(symbol: str):
    news = await fetch_news_by_topic(symbol)
    financials = await fetch_financials(symbol)
    recommendation = await generate_ai_recommendation(symbol, news, financials)
    return {
        "symbol": symbol,
        "ai_recommendation": recommendation,
        "news": news,  # top 5 articles
        "financials": financials
    }

@app.get("/notify-stock/{symbol}")
async def notify_stock(symbol: str):
    news = await fetch_news_by_topic(symbol)
    financials = await fetch_financials(symbol)
    recommendation = await generate_ai_recommendation(symbol, news, financials)

    news_summary = "\n".join([f"📰 {n['title']}" for n in news[:3]]) if news else "No news"

    message = f"""📊 Stock Advisor Update

            📌 *{symbol}*:

            🧠 *AI Suggestion:* 
            {recommendation}

            {news_summary}

            🔁 More updates soon.
            """

    sid = send_whatsapp_message(message)
    return {"message": "Sent to WhatsApp", "sid": "sid"}
