✅ README.md (full, GitHub‑ready)
markdown
# KrakenMeanReversionBot — Open‑Source Mean Reversion Trading Bot for Kraken

A fully‑autonomous, real‑time crypto mean reversion trading bot built for the Kraken exchange.  
It listens to live WebSocket ticker data, evaluates price deviations using Bollinger Bands, RSI, volatility, and Monte Carlo reversion confidence, and executes trades using a rules‑based strategy. Includes a full HUD, dynamic top‑30 asset universe, trailing stops, take‑profit logic, and detailed JSONL order logging.

---

## 📌 Overview

KrakenMeanReversionBot is a standalone, open‑source trading bot designed for clarity, transparency, and ease of use.  
It requires no external services — just Python, a config file, and (optionally) Kraken API keys.

The bot:

- Streams **live ticker data** from Kraken WebSockets  
- Computes **Bollinger Bands**, **RSI**, **volatility**, and **Monte Carlo reversion probability**  
- Selects trades from a **dynamic top‑30 crypto universe**  
- Manages open positions with **hard stop**, **take profit**, and **trailing stop**  
- Displays a clean **HUD** every 30 seconds  
- Logs all trades to a JSONL file  
- Supports **paper mode** (default) and **live mode**

---

## 🚀 Features

### ✔ Bollinger‑Band Mean Reversion  
Buys when price deviates below the mean and conditions confirm a likely reversion.

### ✔ RSI Filter  
Avoids longs when RSI is too high.

### ✔ Volatility Guardrails  
Only trades when volatility is within a safe range.

### ✔ Monte Carlo Reversion Confidence  
Simulates short‑term paths to estimate probability of mean reversion.

### ✔ Dynamic Universe  
Pulls the top 30 crypto assets by market cap & volume, then filters to Kraken USD pairs.

### ✔ Full HUD  
Shows PnL, open positions, and USDC balance (live mode).

### ✔ JSONL Order Logging  
Every trade is logged to:

kraken_meanrev_orders_log.jsonl

Code

---

## 📁 Project Structure

KrakenMeanReversionBot/
│
├── bot.py
├── config.example.json
├── requirements.txt
└── README.md

Code

---

## ⚙️ Installation

Clone the repo:

```bash
git clone https://github.com/YOUR_USERNAME/KrakenMeanReversionBot
cd KrakenMeanReversionBot
Install dependencies:

bash
pip install -r requirements.txt
🛠 Configuration
Copy the example config:

bash
cp config.example.json config.json
Tune:

Bollinger period

RSI threshold

Volatility limits

Monte Carlo settings

Stop loss / take profit

HUD interval

🔑 Live Trading Setup (Optional)
Set your Kraken API keys:

Windows (PowerShell):

powershell
setx KRAKEN_API_KEY "your_key_here"
setx KRAKEN_API_SECRET "your_secret_here"
macOS/Linux:

bash
export KRAKEN_API_KEY="your_key_here"
export KRAKEN_API_SECRET="your_secret_here"
Enable live mode:

bash
setx KRAKEN_MR_MODE "live"
Paper mode is default.

▶️ Running the Bot
bash
python bot.py
You’ll see:

version banner

universe selection

HUD updates

trade entries/exits

order logs

📄 Order Log Format
Example entry:

json
{
  "timestamp": "2026-04-10T17:32:10Z",
  "symbol": "ETH/USD",
  "side": "long",
  "volume": 0.0421,
  "mode": "paper",
  "reason": "LONG ETH/USD mean-reversion ...",
  "price": 3452.12,
  "status": "paper"
}
⚠️ Disclaimer
This bot is provided as‑is.
Crypto trading involves risk.
Use paper mode before enabling live trading.

💬 Support
Open an issue on GitHub for bugs, questions, or feature requests.

Code

---

# ✅ **requirements.txt**

```text
websockets==12.0
requests==2.31.0
(Your bot only needs these two — same as the momentum bot.)