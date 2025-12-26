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
    rules_primary = market.get("rules_primary", "")
    rules_secondary = market.get("rules_secondary", "")
    
    full_rules = rules_primary
    
    # Add Settlement Sources
    settlement_sources = market.get("settlement_sources", [])
    if settlement_sources:
        # Extract names like "ESPN", "Fox Sports"
        source_names = [s.get("name", "") for s in settlement_sources if s.get("name")]
        if source_names:
            if len(source_names) == 1:
                full_rules += f" Outcome verified from {source_names[0]}."
            else:
                # Join with "and" for the last one
                sources_str = " and ".join([", ".join(source_names[:-1]), source_names[-1]]) if len(source_names) > 1 else source_names[0]
                full_rules += f" Outcome verified from {sources_str}."
    
    if rules_secondary:
        full_rules += " " + rules_secondary
        
    if full_rules:
        rules_str = f" | Rules: {full_rules}"
    else:
        rules_str = ""


    return f"{ticker} | {title} ({subtitle}) | Close:{market.get('close_time', '')} | Y:${yes_price} N:${no_price}{spread_str} | Last:${last_price} | Vol:{volume} Liq:{liquidity}{rules_str}"


def filter_and_diversify_markets(markets):
    """
    Filters markets to ensure quality and diversity.
    1. Odds Filter: Keep markets between 10 cents and 90 cents (avoid lottery/sure things).
    2. Spread Filter: Keep markets with spread <= $1.05.
    3. Diversity Filter: Max 3 markets per series (e.g. KXETH).
    """
    print(f"Initial market count: {len(markets)}")
    
    filtered = []
    for m in markets:
        # Liquidity check
        if m.get("liquidity", 0) <= 0:
            continue
            
        # Price & Spread check
        try:
            yes_ask = float(m.get("yes_ask_dollars", 0))
            no_ask = float(m.get("no_ask_dollars", 0))
            
            # Filter 1: Odds (0.10 to 0.90)
            if not (0.10 <= yes_ask <= 0.90):
                continue
                
            # Filter 2: Spread (Max $1.05)
            spread = yes_ask + no_ask
            if spread > 1.05:
                continue
                
            filtered.append(m)
        except (ValueError, TypeError):
            continue
            
    print(f"Markets after odds (10c-90c) & spread (<1.05) filter: {len(filtered)}")
    
    # Filter 3: Diversity (Max 3 per series)
    # Sort by volume first so we keep the most active ones in each series
    filtered.sort(key=lambda x: x.get("volume", 0), reverse=True)
    
    diversity_buckets = {}
    final_list = []
    
    for m in filtered:
        ticker = m.get("ticker", "")
        # Extract series (e.g. KXETH from KXETH-25DEC31...)
        series = ticker.split('-')[0] if '-' in ticker else ticker
        
        if diversity_buckets.get(series, 0) < 3:
            final_list.append(m)
            diversity_buckets[series] = diversity_buckets.get(series, 0) + 1
            
    print(f"Markets after diversity filter (max 3 per series): {len(final_list)}")
    return final_list


def fetch_and_process_markets(client, limit=15):
    """
    Orchestrates the fetching, filtering, and enriching of markets.
    """
    min_ts, max_ts = get_analysis_window()
    print(f"Fetching markets expiring between {min_ts} and {max_ts} (1 Day to 7 Days out)...")
    
    # Fetch all markets using pagination
    all_markets = client.get_all_markets(min_close_ts=min_ts, max_close_ts=max_ts)
    print(f"Found {len(all_markets)} markets potentially closing in this window.")

    # Apply filters (Odds, Spread, Diversity)
    active_markets = filter_and_diversify_markets(all_markets)
    
    # Take top N to avoid token limits and noise
    top_markets = active_markets[:limit]

    # Enrich with Series Data (Settlement Sources)
    print("Fetching series data for top markets to get full rules...")
    for m in top_markets:
        ticker = m.get("ticker", "")
        if "-" in ticker:
            series_ticker = ticker.split("-")[0]
            series_data = client.get_series(series_ticker)
            if series_data:
                m["settlement_sources"] = series_data.get("settlement_sources", [])
                
    return top_markets

