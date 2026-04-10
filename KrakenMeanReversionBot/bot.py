#!/usr/bin/env python
# KrakenMeanReversionBot — standalone open-source edition

import os
import json
import time
import hmac
import hashlib
import base64
import asyncio
import websockets
import requests
from datetime import datetime, timezone
from typing import Optional, Deque, Dict, List, Any
from collections import deque
from pathlib import Path
import random
import math

BOT_NAME = "KrakenMeanReversionBot"
BOT_VERSION = "v1.0.0"

KRAKEN_WS_URL = "wss://ws.kraken.com/v2"
KRAKEN_REST_URL = "https://api.kraken.com"

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
ORDERS_LOG_FILE = Path(__file__).resolve().parent / "kraken_meanrev_orders_log.jsonl"

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

MODE = os.getenv("KRAKEN_MR_MODE", "paper").lower()

KRAKEN_API_KEY = ""
KRAKEN_API_SECRET = ""


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}][{BOT_NAME}] {msg}", flush=True)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"Config file not found at {CONFIG_PATH}. Using defaults from code.")
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"Failed to load config.json: {e}. Using defaults from code.")
        return {}


def load_kraken_keys() -> None:
    global KRAKEN_API_KEY, KRAKEN_API_SECRET
    KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
    KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")
    if KRAKEN_API_KEY and KRAKEN_API_SECRET:
        log("Kraken API keys loaded from environment variables.")
    else:
        log("Kraken API keys not set in environment. Live trading will be disabled.")


def fetch_top_universe(vs: str = "usd", n: int = 30) -> List[str]:
    def fetch(order: str) -> List[str]:
        url = f"{COINGECKO_BASE}/coins/markets"
        params = {
            "vs_currency": vs,
            "order": order,
            "per_page": n,
            "page": 1,
            "sparkline": "false",
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        symbols: List[str] = []
        for c in data:
            sym = c.get("symbol", "").upper()
            if sym in {"USDT", "USDC", "DAI", "TUSD", "FDUSD"}:
                continue
            symbols.append(sym)
        return symbols

    try:
        top_vol = set(fetch("volume_desc"))
        top_mc = set(fetch("market_cap_desc"))
        universe = sorted(top_vol & top_mc)
        return universe
    except Exception as e:
        log(f"[UNIVERSE] Failed to fetch dynamic universe: {e}")
        return ["BTC", "ETH", "SOL", "XRP"]


def kraken_symbol_from_base(base: str) -> Optional[str]:
    mapping = {
        "BTC": "BTC/USD",
        "XBT": "BTC/USD",
        "ETH": "ETH/USD",
        "SOL": "SOL/USD",
        "XRP": "XRP/USD",
        "ADA": "ADA/USD",
        "DOGE": "DOGE/USD",
        "AVAX": "AVAX/USD",
        "LINK": "LINK/USD",
        "MATIC": "MATIC/USD",
        "LTC": "LTC/USD",
        "DOT": "DOT/USD",
    }
    return mapping.get(base.upper())


class Position:
    def __init__(self, symbol: str, entry_price: float, size: float):
        self.symbol = symbol
        self.entry_price = entry_price
        self.size = size
        self.max_price = entry_price
        self.realized_pnl = 0.0


positions: Dict[str, Position] = {}
unrealized_pnl: float = 0.0
realized_pnl_total: float = 0.0


def update_pnl_snapshot(last_prices: Dict[str, float]) -> None:
    global unrealized_pnl
    unrealized_pnl = 0.0
    for sym, pos in positions.items():
        lp = last_prices.get(sym)
        if lp is None:
            continue
        pnl = (lp - pos.entry_price) * pos.size
        unrealized_pnl += pnl


def _kraken_sign(path: str, data: dict, secret: str) -> str:
    postdata = "&".join([f"{k}={v}" for k, v in data.items()])
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def kraken_private(path: str, data: dict) -> dict:
    if not KRAKEN_API_KEY or not KRAKEN_API_SECRET:
        log("KRAKEN_API_KEY/SECRET not set. Trading disabled.")
        return {"error": ["EAPI:NoKey"]}

    data["nonce"] = int(time.time() * 1000)
    headers = {
        "API-Key": KRAKEN_API_KEY,
        "API-Sign": _kraken_sign(path, data, KRAKEN_API_SECRET),
    }
    url = KRAKEN_REST_URL + path
    resp = requests.post(url, headers=headers, data=data, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_usdc_balance() -> float:
    if MODE != "live":
        return 0.0
    try:
        resp = kraken_private("/0/private/Balance", {})
        if resp.get("error"):
            log(f"[BALANCE] Error from Kraken: {resp['error']}")
            return 0.0
        result = resp.get("result", {})
        for key in ("USDC", "USDC.M", "ZUSD", "USD"):
            if key in result:
                try:
                    return float(result[key])
                except Exception:
                    continue
        return 0.0
    except Exception as e:
        log(f"[BALANCE] Failed to fetch balance: {e}")
        return 0.0


def log_order(event: Dict[str, Any]) -> None:
    with ORDERS_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def place_order(symbol: str, side: str, volume: float, reason: str, price: Optional[float]) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    event = {
        "timestamp": ts,
        "symbol": symbol,
        "side": side,
        "volume": volume,
        "mode": MODE,
        "reason": reason,
        "price": price,
    }

    if MODE != "live":
        log(f"[TRADE] PAPER {side.upper()} {symbol} vol={volume:.6f} reason={reason}")
        event["status"] = "paper"
        log_order(event)
        return

    try:
        data = {
            "ordertype": "market",
            "type": "buy" if side == "long" else "sell",
            "volume": volume,
            "pair": symbol.replace("/", ""),
        }
        resp = kraken_private("/0/private/AddOrder", data)
        event["status"] = "sent"
        event["response"] = resp
        log(f"[TRADE] LIVE {side.upper()} {symbol} vol={volume:.6f} resp={resp}")
    except Exception as e:
        event["status"] = "error"
        event["error"] = str(e)
        log(f"[TRADE] ERROR sending order: {e}")
    finally:
        log_order(event)


class SymbolState:
    def __init__(self, symbol: str, bb_period: int, rsi_period: int):
        self.symbol = symbol
        self.prices: Deque[tuple[float, float]] = deque()
        self.last_price: Optional[float] = None
        self.bb_period = bb_period
        self.rsi_period = rsi_period

    def add_price(self, ts: float, price: float) -> None:
        self.last_price = price
        self.prices.append((ts, price))
        # keep last max(bb_period, rsi_period) * 3 points
        max_len = max(self.bb_period, self.rsi_period) * 3
        while len(self.prices) > max_len:
            self.prices.popleft()

    def closes(self) -> List[float]:
        return [p for _, p in self.prices]

    def bollinger(self) -> Optional[tuple[float, float, float]]:
        closes = self.closes()
        if len(closes) < self.bb_period:
            return None
        window = closes[-self.bb_period:]
        mean = sum(window) / len(window)
        var = sum((x - mean) ** 2 for x in window) / len(window)
        std = math.sqrt(var)
        upper = mean + 2 * std
        lower = mean - 2 * std
        return lower, mean, upper

    def rsi(self) -> float:
        closes = self.closes()
        if len(closes) < self.rsi_period + 1:
            return 50.0
        window = closes[-(self.rsi_period + 1):]
        deltas = [window[i] - window[i - 1] for i in range(1, len(window))]
        gains = [max(d, 0) for d in deltas]
        losses = [-min(d, 0) for d in deltas]
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    def volatility_pct(self) -> float:
        closes = self.closes()
        if len(closes) < 3:
            return 0.0
        p0 = min(closes)
        p1 = max(closes)
        if p0 <= 0:
            return 0.0
        return abs(p1 - p0) / p0 * 100.0


def mc_reversion_confidence(st: SymbolState, num_paths: int, horizon_sec: int) -> float:
    # Simple Monte Carlo: probability of price reverting toward mean
    bb = st.bollinger()
    if bb is None or st.last_price is None:
        return 0.5
    lower, mean, upper = bb
    closes = st.closes()
    if len(closes) < 10:
        return 0.5

    rets: List[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
    if not rets:
        return 0.5

    current = st.last_price
    revert_count = 0
    for _ in range(num_paths):
        price = current
        t = 0
        while t < horizon_sec:
            r = random.choice(rets)
            price *= (1.0 + r)
            t += 1
        # consider "reverted" if closer to mean than current
        if abs(price - mean) < abs(current - mean):
            revert_count += 1
    return revert_count / num_paths


def mc_size_multiplier(conf: float, mc_min_conf: float) -> float:
    if conf < mc_min_conf:
        return 0.0
    if conf >= 0.75:
        return 1.5
    if conf >= 0.65:
        return 1.0
    return 0.5


def compute_meanrev_score(
    st: SymbolState,
    rsi_max_long: float,
    vol_min_pct: float,
    vol_max_pct: float,
    mc_conf: float,
    mc_min_conf: float,
) -> float:
    if st.last_price is None:
        return -999.0

    bb = st.bollinger()
    if bb is None:
        return -999.0
    lower, mean, upper = bb
    price = st.last_price

    # we want price below mean, ideally near/below lower band
    if price >= mean:
        return -999.0

    rsi = st.rsi()
    if rsi > rsi_max_long:
        return -999.0

    vol = st.volatility_pct()
    if vol < vol_min_pct or vol > vol_max_pct:
        return -999.0

    if mc_conf < mc_min_conf:
        return -999.0

    # distance below mean (normalized) + MC + RSI cushion
    dist = (mean - price) / mean * 100.0
    score = dist + (mc_conf - 0.5) * 100.0 + max(0.0, rsi_max_long - rsi)
    return score


def maybe_trade(
    symbol_states: Dict[str, SymbolState],
    last_prices: Dict[str, float],
    base_position_usd: float,
    max_open_positions: int,
    rsi_max_long: float,
    vol_min_pct: float,
    vol_max_pct: float,
    mc_min_conf: float,
    mc_paths: int,
    mc_horizon_sec: int,
) -> None:
    global positions

    if len(positions) >= max_open_positions:
        return

    best_sym = None
    best_score = -999.0
    best_mc_conf = 0.5

    for sym, st in symbol_states.items():
        mc_conf = mc_reversion_confidence(st, mc_paths, mc_horizon_sec)
        s = compute_meanrev_score(
            st,
            rsi_max_long,
            vol_min_pct,
            vol_max_pct,
            mc_conf,
            mc_min_conf,
        )
        if s > best_score:
            best_score = s
            best_sym = sym
            best_mc_conf = mc_conf

    if best_sym is None or best_score <= -999.0:
        return

    st = symbol_states[best_sym]
    price = st.last_price
    if price is None or price <= 0:
        return

    mc_mult = mc_size_multiplier(best_mc_conf, mc_min_conf)
    if mc_mult <= 0.0:
        return

    notional = base_position_usd * mc_mult
    volume = notional / price

    bb = st.bollinger()
    lower, mean, upper = bb if bb is not None else (0.0, 0.0, 0.0)

    reason = (
        f"LONG {best_sym} mean-reversion price={price:.2f} "
        f"bb_lower={lower:.2f} mean={mean:.2f} rsi={st.rsi():.1f} "
        f"vol={st.volatility_pct():.3f}% mc_conf={best_mc_conf:.3f} score={best_score:.3f}"
    )

    log(f"[ENTRY] LONG {best_sym} @ {price:.2f}, notional={notional:.2f}, reason={reason}")
    place_order(best_sym, "long", volume, reason, price)
    positions[best_sym] = Position(best_sym, price, volume)


def manage_positions(
    last_prices: Dict[str, float],
    hard_sl_pct: float,
    take_profit_pct: float,
    trail_start_pct: float,
    trail_step_pct: float,
) -> None:
    global realized_pnl_total, positions
    to_close: List[str] = []

    for sym, pos in positions.items():
        lp = last_prices.get(sym)
        if lp is None:
            continue

        if lp > pos.max_price:
            pos.max_price = lp

        pnl = (lp - pos.entry_price) * pos.size
        pnl_pct = (lp - pos.entry_price) / pos.entry_price * 100.0

        if pnl_pct <= -hard_sl_pct:
            log(f"[EXIT] HARD SL {sym} @ {lp:.2f}, pnl={pnl:.2f} ({pnl_pct:.3f}%)")
            place_order(sym, "flat", pos.size, f"hard_sl {pnl_pct:.3f}%", lp)
            realized_pnl_total += pnl
            to_close.append(sym)
            continue

        if pnl_pct >= take_profit_pct:
            log(f"[EXIT] TP {sym} @ {lp:.2f}, pnl={pnl:.2f} ({pnl_pct:.3f}%)")
            place_order(sym, "flat", pos.size, f"take_profit {pnl_pct:.3f}%", lp)
            realized_pnl_total += pnl
            to_close.append(sym)
            continue

        peak_pct = (pos.max_price - pos.entry_price) / pos.entry_price * 100.0
        if peak_pct >= trail_start_pct:
            trail_level = pos.max_price * (1.0 - trail_step_pct / 100.0)
            if lp <= trail_level:
                log(f"[EXIT] TRAIL {sym} @ {lp:.2f}, pnl={pnl:.2f} ({pnl_pct:.3f}%), peak={peak_pct:.3f}%")
                place_order(sym, "flat", pos.size, f"trailing_stop {pnl_pct:.3f}%", lp)
                realized_pnl_total += pnl
                to_close.append(sym)

    for sym in to_close:
        positions.pop(sym, None)


def hud_line(last_prices: Dict[str, float]) -> None:
    total_unreal = 0.0
    for sym, pos in positions.items():
        lp = last_prices.get(sym)
        if lp is None:
            continue
        total_unreal += (lp - pos.entry_price) * pos.size
    total_pnl = realized_pnl_total + total_unreal
    log(
        f"[HUD] MODE={MODE.upper()} | OpenPos={len(positions)} | "
        f"PnL={total_pnl:+.2f} (Real={realized_pnl_total:+.2f}, Unrl={total_unreal:+.2f})"
    )

    bal = fetch_usdc_balance()
    log(f"[HUD] Balance: USDC={bal:.2f}")


async def kraken_ws_loop(
    symbols: List[str],
    symbol_states: Dict[str, SymbolState],
    base_position_usd: float,
    max_open_positions: int,
    rsi_max_long: float,
    vol_min_pct: float,
    vol_max_pct: float,
    mc_min_conf: float,
    mc_paths: int,
    mc_horizon_sec: int,
    hard_sl_pct: float,
    take_profit_pct: float,
    trail_start_pct: float,
    trail_step_pct: float,
    hud_interval_sec: float,
) -> None:
    last_prices: Dict[str, float] = {}
    last_hud = time.time()

    subs = []
    for sym in symbols:
        pair = sym.replace("/", "")
        subs.append(pair)

    sub_msg = {
        "method": "subscribe",
        "params": {
            "channel": "ticker",
            "symbol": subs,
        },
    }

    while True:
        try:
            async with websockets.connect(KRAKEN_WS_URL) as ws:
                log(f"[WS] Connected to {KRAKEN_WS_URL}")
                await ws.send(json.dumps(sub_msg))
                log(f"[WS] Subscribed to ticker for {symbols}")

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue

                    if isinstance(msg, dict) and msg.get("channel") == "ticker":
                        data = msg.get("data", [])
                        for tick in data:
                            pair = tick.get("symbol")
                            if not pair:
                                continue
                            price_str = tick.get("last", {}).get("price")
                            if price_str is None:
                                continue
                            try:
                                price = float(price_str)
                            except Exception:
                                continue

                            sym = None
                            for s in symbols:
                                if s.replace("/", "") == pair:
                                    sym = s
                                    break
                            if sym is None:
                                continue

                            ts = time.time()
                            last_prices[sym] = price
                            st = symbol_states.get(sym)
                            if st:
                                st.add_price(ts, price)

                    now = time.time()
                    if now - last_hud >= hud_interval_sec:
                        hud_line(last_prices)
                        update_pnl_snapshot(last_prices)
                        maybe_trade(
                            symbol_states,
                            last_prices,
                            base_position_usd,
                            max_open_positions,
                            rsi_max_long,
                            vol_min_pct,
                            vol_max_pct,
                            mc_min_conf,
                            mc_paths,
                            mc_horizon_sec,
                        )
                        manage_positions(
                            last_prices,
                            hard_sl_pct,
                            take_profit_pct,
                            trail_start_pct,
                            trail_step_pct,
                        )
                        last_hud = now

        except Exception as e:
            log(f"[WS] Error in loop: {e}, reconnecting in 5s...")
            await asyncio.sleep(5.0)


async def main() -> None:
    cfg = load_config()
    load_kraken_keys()

    base_position_usd = float(cfg.get("base_position_usd", 25.0))
    bb_period = int(cfg.get("bb_period", 40))
    rsi_period = int(cfg.get("rsi_period", 14))
    rsi_max_long = float(cfg.get("rsi_max_long", 55.0))
    vol_min_pct = float(cfg.get("vol_min_pct", 0.05))
    vol_max_pct = float(cfg.get("vol_max_pct", 3.0))
    take_profit_pct = float(cfg.get("take_profit_pct", 1.2))
    hard_sl_pct = float(cfg.get("hard_sl_pct", 0.7))
    trail_start_pct = float(cfg.get("trail_start_pct", 1.0))
    trail_step_pct = float(cfg.get("trail_step_pct", 0.3))
    max_open_positions = int(cfg.get("max_open_positions", 2))
    mc_min_conf = float(cfg.get("mc_min_conf", 0.55))
    mc_paths = int(cfg.get("mc_paths", 800))
    mc_horizon_sec = int(cfg.get("mc_horizon_sec", 60))
    hud_interval_sec = float(cfg.get("hud_interval_sec", 30.0))

    universe_bases = fetch_top_universe("usd", 30)
    symbols: List[str] = []
    for base in universe_bases:
        ks = kraken_symbol_from_base(base)
        if ks:
            symbols.append(ks)

    if not symbols:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"]

    log(f"{BOT_NAME} {BOT_VERSION} starting in MODE={MODE.upper()}")
    log(f"[UNIVERSE] Symbols: {', '.join(symbols)}")

    symbol_states: Dict[str, SymbolState] = {}
    for sym in symbols:
        symbol_states[sym] = SymbolState(sym, bb_period, rsi_period)

    await kraken_ws_loop(
        symbols,
        symbol_states,
        base_position_usd,
        max_open_positions,
        rsi_max_long,
        vol_min_pct,
        vol_max_pct,
        mc_min_conf,
        mc_paths,
        mc_horizon_sec,
        hard_sl_pct,
        take_profit_pct,
        trail_start_pct,
        trail_step_pct,
        hud_interval_sec,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Shutting down.")
