"""
Market data formatting utilities.
"""
from datetime import datetime, timezone, timedelta


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
        
    # Rules
    rules = market.get("rules_primary", "")
    if rules:
        # Truncate to keep it concise but useful (first 300 chars)
        if len(rules) > 300:
            rules = rules[:297] + "..."
        rules_str = f" | Rules: {rules}"
    else:
        rules_str = ""

    # Concise Format:
    # TICKER | Title (Subtitle) | Close: ... | Y: $P | N: $P | Spread: $S | Lst: $P | V: Val | L: Val | Rules: ...
    return f"{ticker} | {title} ({subtitle}) | Close:{market.get('close_time', '')} | Y:${yes_price} N:${no_price}{spread_str} | Last:${last_price} | Vol:{volume} Liq:{liquidity}{rules_str}"
