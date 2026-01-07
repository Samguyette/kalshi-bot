"""
Market data formatting and filtering utilities.

This module handles:
- Fetching markets from Kalshi within a specific time window
- Filtering markets based on category, pricing, and liquidity criteria
- Formatting market data for LLM consumption
- Enforcing position limits and token constraints
"""
from datetime import datetime, timezone, timedelta
from bet_tracker import get_bet_count_for_ticker, get_bet_count_for_series_prefix


# =============================================================================
# CONFIGURATION
# =============================================================================

CULTURE_TICKER_PREFIXES = [
    "KXRT",            # Rotten Tomatoes
    "KXSPOTIFY",       # Spotify
    "KXNETFLIX",       # Netflix
    "KXMOVI",          # Movies
    "KXBILLBOARD",     # Billboard
    "KXRANKLISTSONG",  # Ranked Songs
    "KXSONG",          # Songs
    "KXALBUM",         # Albums
    "KXTV"             # TV
]

# Filtering thresholds
MIN_VOLUME = 50
MIN_YES_PRICE = 0.15
MAX_YES_PRICE = 0.85
MAX_SPREAD = 1.08  # Loosened from 1.05 to capture markets with standard fee spreads

# Exposure limits
MAX_BETS_PER_TICKER = 2
MAX_EXPOSURE_PER_SERIES = 4
MAX_MARKETS_FOR_LLM = 15


# =============================================================================
# TIME WINDOW
# =============================================================================

def get_market_time_window():
    """Return time window for markets closing 1-14 days out (Unix timestamps)."""
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1)
    end_time = now + timedelta(days=14)
    
    return int(start_time.timestamp()), int(end_time.timestamp())


# =============================================================================
# MARKET FILTERING
# =============================================================================

def _is_valid_culture_market(market):
    """Check if market meets culture category, volume, pricing, and spread criteria."""
    ticker = market.get("ticker", "")
    volume = market.get("volume", 0)
    
    # Check ticker prefix
    if not any(ticker.startswith(prefix) for prefix in CULTURE_TICKER_PREFIXES):
        return False
    
    # Check volume
    if volume <= MIN_VOLUME:
        return False
    
    # Check pricing and spread
    try:
        yes_ask = float(market.get("yes_ask_dollars", 0))
        no_ask = float(market.get("no_ask_dollars", 0))
        
        if not (MIN_YES_PRICE <= yes_ask <= MAX_YES_PRICE):
            return False
        
        spread = yes_ask + no_ask
        if spread > MAX_SPREAD:
            return False
        
        return True
    except (ValueError, TypeError):
        return False


def filter_culture_markets(markets):
    """Filter for culture markets with sufficient volume, reasonable pricing, and low spread."""
    print(f"Initial market count: {len(markets)}")
    
    filtered = [market for market in markets if _is_valid_culture_market(market)]
    
    print(f"Markets after filtering: {len(filtered)}")
    return filtered


def filter_by_position_limits(markets):
    """Remove markets where we've reached max exposure."""
    print("Filtering out markets with max exposure...")
    available_markets = []
    
    for market in markets:
        ticker = market.get("ticker", "")
        
        # 1. Check Ticker Limit
        bet_count = get_bet_count_for_ticker(ticker)
        if bet_count >= MAX_BETS_PER_TICKER:
            print(f"  Skipping {ticker}: Max exposure reached ({bet_count}/{MAX_BETS_PER_TICKER} bets)")
            continue

        # 2. Check Series Limit
        # Extract series (e.g., 'KXRTPRIMATE' from 'KXRTPRIMATE-85')
        series_prefix = ticker.split("-")[0]
        series_count = get_bet_count_for_series_prefix(series_prefix)
        if series_count >= MAX_EXPOSURE_PER_SERIES:
            print(f"  Skipping {ticker}: Max series exposure reached ({series_count}/{MAX_EXPOSURE_PER_SERIES} bets on {series_prefix})")
            continue
            
        available_markets.append(market)
    
    return available_markets


# =============================================================================
# MARKET FORMATTING
# =============================================================================

def format_market_for_prompt(market):
    """Format market into compact string for LLM prompt."""
    ticker = market.get("ticker", "N/A")
    title = market.get("title", "N/A")
    subtitle = market.get("subtitle") or market.get("yes_sub_title", "")
    

    yes_price = market.get("yes_ask_dollars", "N/A")
    no_price = market.get("no_ask_dollars", "N/A")
    
    if yes_price != "N/A":
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


    if yes_price == "N/A" and no_price == "N/A":
        return None
    

    spread_str = ""
    try:
        spread = float(yes_price) + float(no_price)
        spread_str = f" | Spread:${spread:.2f}"
    except:
        pass
    
    volume = market.get("volume", 0)
    liquidity = market.get("liquidity", 0)
    rules_text = _build_rules_section(market)
    rules_str = f" | Rules: {rules_text}" if rules_text else ""

    return (
        f"{ticker} | {title} ({subtitle}) | Close:{market.get('close_time', '')} | "
        f"Y:${yes_price} N:${no_price}{spread_str} | Last:${last_price} | "
        f"Vol:{volume} Liq:{liquidity}{rules_str}"
    )


def _build_rules_section(market):
    """Build rules section with settlement sources."""
    rules_primary = market.get("rules_primary", "")
    rules_secondary = market.get("rules_secondary", "")
    
    full_rules = rules_primary
    settlement_sources = market.get("settlement_sources", [])
    if settlement_sources:
        source_names = [s.get("name", "") for s in settlement_sources if s.get("name")]
        if source_names:
            if len(source_names) == 1:
                full_rules += f" Outcome verified from {source_names[0]}."
            else:
                sources_str = " and ".join([", ".join(source_names[:-1]), source_names[-1]])
                full_rules += f" Outcome verified from {sources_str}."
    
    if rules_secondary:
        full_rules += " " + rules_secondary
    
    return full_rules


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def fetch_filtered_markets(client, limit=50):
    """Fetch, filter, and enrich markets for LLM analysis."""

    min_ts, max_ts = get_market_time_window()
    print(f"Fetching markets closing between {min_ts} and {max_ts} (1-14 days out)...")
    
    all_markets = client.get_all_markets(min_close_ts=min_ts, max_close_ts=max_ts)
    print(f"Found {len(all_markets)} markets in time window")


    filtered_markets = filter_culture_markets(all_markets)
    

    top_markets = filtered_markets[:limit]
    

    available_markets = filter_by_position_limits(top_markets)
    

    if len(available_markets) > MAX_MARKETS_FOR_LLM:
        print(f"Capping {len(available_markets)} markets to {MAX_MARKETS_FOR_LLM} for LLM")
        available_markets = available_markets[:MAX_MARKETS_FOR_LLM]


    print("Enriching markets with series-level settlement sources...")
    for market in available_markets:
        ticker = market.get("ticker", "")
        if "-" in ticker:
            series_ticker = ticker.split("-")[0]
            series_data = client.get_series(series_ticker)
            if series_data:
                market["settlement_sources"] = series_data.get("settlement_sources", [])
                
    return available_markets

