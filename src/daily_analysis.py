import os
import sys
from datetime import datetime, timezone, timedelta
from kalshi_client import KalshiClient

def get_analysis_window():
    """
    Returns the start (Now + 24h) and end (Now + 7d) timestamps.
    Excludes markets closing in <24h to avoid fast-moving/stale live odds.
    """
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = now + timedelta(days=7)
    
    return int(start_time.timestamp()), int(end_time.timestamp())

def format_market_for_prompt(market):
    """
    Formats a single market's data into a concise string for the LLM prompt.
    """
    ticker = market.get("ticker", "N/A")
    title = market.get("title", "N/A")
    subtitle = market.get("subtitle") or market.get("yes_sub_title", "")
    
    # Prices
    yes_price = market.get("yes_ask_dollars", "N/A")
    no_price = market.get("no_ask_dollars", "N/A")
    if yes_price != "N/A": 
        # Strip trailing zeros if possible for compactness, e.g. 0.2800 -> 0.28
        try:
            yes_price = f"{float(yes_price):.2f}"
            no_price = f"{float(no_price):.2f}"
        except:
            pass

    last_price = market.get("last_price_dollars", "0")
    try:
        last_price = f"{float(last_price):.2f}"
    except:
        pass

    volume = market.get("volume", 0)
    liquidity = market.get("liquidity", 0)
    
    # Skip empty pricing
    if yes_price == "N/A" and no_price == "N/A":
        return None
    
    # Calculate Spread (Vig)
    spread_str = ""
    try:
        y_float = float(yes_price)
        n_float = float(no_price)
        spread = y_float + n_float
        # Only show if meaningful (e.g., > 1.00)
        spread_str = f" | Spread:${spread:.2f}"
    except:
        pass
        
    # Concise Format:
    # TICKER | Title (Subtitle) | Close: ... | Y: $P | N: $P | Spread: $S | Lst: $P | V: Val | L: Val
    return f"{ticker} | {title} ({subtitle}) | Close:{market.get('close_time', '')} | Y:${yes_price} N:${no_price}{spread_str} | Last:${last_price} | Vol:{volume} Liq:{liquidity}"

def generate_llm_prompt(markets):
    """
    Generates the full prompt for the Thinking LLM.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    market_sections = []
    for m in markets:
        formatted = format_market_for_prompt(m)
        if formatted:
            market_sections.append(formatted)
            
    if not market_sections:
        return "No active markets found closing today with valid pricing."

    markets_text = "\n".join(market_sections)
    
    prompt = f"""
# Prediction Market Analysis Request for {today_str}

## Objective
Identify the SINGLE most profitable trading opportunity from the list below. 
These markets close between 24 hours and 7 days from now (avoiding immediate volatility).

## Analysis Criteria
1. **Spread & Vigorish**: Check the "Spread". If Yes+No > $1.02, the trade requires a significantly higher edge to be profitable. Avoid high-fee markets.
2. **Skepticism of Long Shots**: Apply a heavy penalty to any option priced below $0.05 ($1 to $5 bets). These are often "dead money" unless you identify specific breaking news.
3. **EV & Probability**: Compare implied probability (Price) vs real-world likelihood.
4. **Liquidity**: Ensure sufficient volume/liquidity to execute.

## Market Data
(Format: Ticker | Title (Subtitle) | Close: Time | Y: YesAsk | N: NoAsk | Spread: Sum | Last: LastPrice | Vol: Volume | Liq: Liquidity)
{markets_text}

## Required Output Format
Output ONLY your single best pick in this format:

### MATCH: [Ticker] [Buy YES/NO] @ [Price]
**Reasoning:** [Concise analysis of why EV is positive, accounting for spread/fees.]
**Confidence:** [High/Medium/Low]
"""
    return prompt

def main():
    client = KalshiClient()
    
    min_ts, max_ts = get_analysis_window()
    print(f"Fetching markets expiring between {min_ts} and {max_ts} (1 Day to 7 Days out)...")
    
    # Fetch all markets using pagination
    all_markets = client.get_all_markets(min_close_ts=min_ts, max_close_ts=max_ts)
    
    print(f"Found {len(all_markets)} markets potentially closing in this window.")

    # Filter out dead markets (no liquidity)
    # If volume is 0, it might still have liquidity (asks/bids)
    active_markets = [m for m in all_markets if m.get("liquidity", 0) > 0]
    
    print(f"Filtered to {len(active_markets)} active markets (Liquidity > 0).")

    # Sort by Volume (desc), then Liquidity (desc)
    active_markets.sort(key=lambda x: (x.get("volume", 0), x.get("liquidity", 0)), reverse=True)
    
    # Take top 50 to avoid token limits and noise
    top_markets = active_markets[:50]

    # Generate and print prompt
    prompt = generate_llm_prompt(top_markets)
    
    print("\n" + "="*50 + "\n")
    print(prompt)
    print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
