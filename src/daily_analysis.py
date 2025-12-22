import os
import sys
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types
import json
from dotenv import load_dotenv
from kalshi_client import KalshiClient
import re
import math

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

## Role & Objective
You are a World-Class Superforecaster and Hedge Fund Manager. Your goal is to identify the SINGLE best risk-adjusted trade from the list below.
You do NOT care about "excitement" or "narrative". You care about Expected Value (EV) and mispricing relative to base rates.

## Analysis Framework
1. **Base Rate Anchoring**: For each potential candidate, ask: "What is the historical frequency of this event?" (e.g., How often does a bill pass in 3 days? How often does a movie make $100M?).
2. **True Probability Estimation**: Derived from base rates + specific news.
3. **EV Calculation**: Compare your True Probability vs. the Market Implied Probability (Price).
   - If True Prob > Price (for YES), EV is positive.
   - If True Prob < Price (for NO), EV is positive.
   - EV = (Prob_Win * $Profit_if_Win) - (Prob_Loss * Cost_of_Bet)
   - $Profit_if_Win approx ($1.00 - Price). Cost_of_Bet = Price.

## Constraints & Rules
1. **Spread / Vig**: Ignore markets with Spread > $1.05 unless the edge is massive.
2. **Liquidity**: Avoid markets with Liquidity < $100 unless you are 99% certain.
3. **Long Shot Penalty**: Be extremely skeptical of prices < $0.05 or > $0.95. The market is usually right at extremes.
4. **Execution**: You can buy "YES" or "NO".

## Market Data
(Format: Ticker | Title (Subtitle) | Close: Time | Y: YesAsk | N: NoAsk | Spread: Sum | Last: LastPrice | Vol: Volume | Liq: Liquidity | Rules: RulesSummary)
{markets_text}

## Required Output Format (JSON ONLY)
You must output a single valid JSON object. Do not output markdown code blocks.
{{
  "ticker": "MARKET-TICKER",
  "side": "YES" or "NO",
  "price": 0.45,
  "estimated_true_probability": 0.65,
  "confidence": "High" or "Medium",
  "reasoning": "Step-by-step superforecasting analysis: Base rate is X. Specifics are Y. Market is mispriced because Z. EV calculation..."
}}
"""
    return prompt


def call_google_llm(prompt, dry_run=False):
    """
    Calls Google's Gemini models with fallback logic.
    Attempts models in order: Gemini 3 -> Gemini 2.0 Flash Thinking -> Gemini 2.0 Flash
    If dry_run=True, prioritizes faster/cheaper models.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("\n" + "!"*50)
        print("ERROR: GEMINI_API_KEY not found in environment variables.")
        print("Please check your .env file.")
        print("!"*50 + "\n")
        return None

    client = genai.Client(api_key=api_key)
    
    # Priority list of models to try
    if dry_run:
        print("[DRY RUN] Using faster/cheaper models for testing.")
        models_to_try = [
            "gemini-2.0-flash",           # Standard Flash 2.0 (Fast & Cheap)
            "gemini-flash-latest",        # Fallback to 1.5 Flash
            "gemini-2.0-flash-exp"
        ]
    else:
        models_to_try = [
            "gemini-3-pro-preview",       # Best (likely paid/limited)
            "gemini-2.0-flash-exp",       # Experimental Flash (often has thinking/better reasing)
            "gemini-2.0-flash",           # Standard Flash 2.0 (Solid)
            "gemini-flash-latest"         # Fallback to 1.5 Flash
        ]

    for model_name in models_to_try:
        try:
            print(f"Sending analysis request to Google (Model: {model_name})...")
            response = client.models.generate_content(
                model=model_name,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
                contents=[prompt]
            )
            return response.text
        except Exception as e:
            # Check if it looks like a quota error (429) or other resource exhaustion
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                print(f"Warning: Quota exceeded/Error with {model_name}. Falling back...")
            else:
                # For other errors, we might also want to try the next model just in case,
                # but print the specific error.
                print(f"Warning: Error with {model_name}: {e}. Falling back...")
            
            # Continue to next model
            continue

    print("ERROR: All models failed to generate a response.")
    return None

def parse_llm_decision(llm_output):
    """
    Parses the LLM output to extract the trade decision from JSON.
    """
    if not llm_output:
        return None
        
    try:
        # Clean up any potential markdown code blocks like ```json ... ```
        cleaned_output = llm_output.strip()
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output.split("\n", 1)[1]
            if cleaned_output.endswith("```"):
                cleaned_output = cleaned_output.rsplit("\n", 1)[0]
        
        data = json.loads(cleaned_output)
        
        return {
            "ticker": data.get("ticker"),
            "side": data.get("side"),
            "price": float(data.get("price", 0.0))
        }
    except Exception as e:
        print(f"Error parsing JSON from LLM: {e}")
        return None

def execute_bet(client, decision, dry_run=False):
    """
    Executes the bet based on the parsed decision.
    Bet size is fixed at ~$5.00.
    """
    if not decision:
        return
        
    ticker = decision["ticker"]
    side = decision["side"]
    price = decision["price"]
    
    bet_amount = 5.00
    
    # Calculate count: Floor(5.00 / Price)
    if price <= 0:
        print("Error: Invalid price detected.")
        return
        
    count = math.floor(bet_amount / price)
    
    if count < 1:
        print(f"Price (${price}) is too high for a $5 bet.")
        return
        
    print(f"\n" + "="*50)
    print(f"EXECUTING AUTOMATED BET")
    print(f"Target: {ticker}")
    print(f"Side:   {side}")
    print(f"Price:  ${price}")
    print(f"Count:  {count} contracts")
    print(f"Total:  ${count * price:.2f}")
    print("="*50 + "\n")
    
    # Determine if DRY RUN is enabled (passed from main now, but keeping for safety)
    # dry_run arg is now passed in execute_bet call
    
    # Place the order
    client.place_order(ticker, side, count, price, dry_run=dry_run)

def main():
    load_dotenv()
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
    print("Generated Prompt (feeding to LLM...):")
    print(prompt)
    print("="*50 + "\n")

    # Determine if DRY RUN is enabled
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"

    # Call Google LLM
    analysis = call_google_llm(prompt, dry_run=dry_run)
    
    if analysis:
        print("\n" + "*"*20 + " GOOGLE THINKING LLM PREDICTION " + "*"*20 + "\n")
        print(analysis)
        print("\n" + "*"*70 + "\n")
        
        # Parse and Bet
        decision = parse_llm_decision(analysis)
        if decision:
            execute_bet(client, decision, dry_run=dry_run)
        else:
            print("Could not parse a valid trade decision from the LLM output.")

if __name__ == "__main__":
    main()
