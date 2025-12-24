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
from supabase import create_client, Client

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
    Generates the full prompt for the Thinking LLM using the template file.
    """
    # Load the prompt template
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', 'v2.md')
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read()
    except FileNotFoundError:
        # Fallback error message if template file is missing
        return "Error: Prompt template file not found at " + template_path
    
    # Format market data
    market_sections = []
    for m in markets:
        formatted = format_market_for_prompt(m)
        if formatted:
            market_sections.append(formatted)
            
    if not market_sections:
        return "No active markets found closing today with valid pricing."

    markets_text = "\n".join(market_sections)
    
    # Replace the placeholders
    prompt = prompt_template.replace("[MARKET DATA GOES HERE]", markets_text)
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = prompt.replace("[DATE]", today_str)
    
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
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
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
    Handles markdown code blocks and other formatting issues.
    """
    if not llm_output:
        return None
        
    try:
        cleaned_output = llm_output.strip()
        
        # Remove markdown code blocks (```json ... ``` or ``` ... ```)
        if cleaned_output.startswith("```"):
            # Find the first newline after opening ```
            first_newline = cleaned_output.find("\n")
            if first_newline != -1:
                cleaned_output = cleaned_output[first_newline + 1:]
            
            # Remove closing ```
            if cleaned_output.endswith("```"):
                last_backticks = cleaned_output.rfind("```")
                cleaned_output = cleaned_output[:last_backticks]
        
        # Strip whitespace again after removing markdown
        cleaned_output = cleaned_output.strip()
        
        # Remove trailing comma before closing brace (common LLM mistake)
        # Match pattern like: ,"  } or ,\n}
        import re
        cleaned_output = re.sub(r',(\s*})$', r'\1', cleaned_output)
        
        # Parse JSON
        data = json.loads(cleaned_output)
        
        return {
            "ticker": data.get("ticker"),
            "side": data.get("side"),
            "price": float(data.get("price", 0.0)),
            "reasoning": data.get("reasoning"),
            "confidence": data.get("confidence")
        }
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from LLM: {e}")
        print(f"Attempted to parse: {cleaned_output[:500]}...")
        return None
    except Exception as e:
        print(f"Unexpected error parsing LLM output: {e}")
        return None

def execute_bet(client, decision, dry_run=False):
    """
    Executes the bet based on the parsed decision.
    Bet size is fixed at ~$4.00.
    """
    if not decision:
        return
        
    ticker = decision["ticker"]
    side = decision["side"]
    price = decision["price"]
    
    bet_amount = 4.00
    
    # Calculate count: Floor(bet_amount / Price)
    if price <= 0:
        print("Error: Invalid price detected.")
        return
        
    count = math.floor(bet_amount / price)
    
    if count < 1:
        print(f"Price (${price}) is too high for a ${bet_amount} bet.")
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
    order_response = client.place_order(ticker, side, count, price, dry_run=dry_run)
    
    # Extract fee information from order response
    fee_amount = None
    if order_response and not dry_run:
        # The response contains an "order" object with fee details
        order_data = order_response.get("order", {})
        taker_fees = order_data.get("taker_fees_dollars", 0)
        maker_fees = order_data.get("maker_fees_dollars", 0)
        
        # Total fees incurred
        fee_amount = float(taker_fees) + float(maker_fees)
        
        if fee_amount > 0:
            print(f"Fees: Taker: ${taker_fees} | Maker: ${maker_fees} | Total: ${fee_amount:.2f}")
    
    # Get current portfolio balance
    balance_info = client.get_balance()
    balance = None
    if balance_info:
        # Extract the balance from the response
        # Kalshi API returns values in cents
        cash_balance = balance_info.get("balance", 0) / 100.0
        position_value = balance_info.get("portfolio_value", 0) / 100.0
        
        balance = cash_balance + position_value
        print(f"Portfolio Status: Cash: ${cash_balance:.2f} | Positions: ${position_value:.2f} | Total Equity: ${balance:.2f}")
    
    # Log to Supabase if order was seemingly successful (or dry run)
    if order_response:
        log_bet_to_supabase(decision, count, bet_amount, balance, fee_amount, dry_run)

def log_bet_to_supabase(decision, count, amount, portfolio_balance, fee_amount=None, dry_run=False):
    """
    Logs the bet details to Supabase.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Warning: SUPABASE_URL or SUPABASE_KEY not found. Skipping DB log.")
        return

    try:
        supabase: Client = create_client(url, key)
        
        data = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "ticker": decision["ticker"],
            "title": decision.get("title", ""),
            "subtitle": decision.get("subtitle", ""),
            "rules": decision.get("rules", ""),
            "side": decision["side"],
            "price": decision["price"],
            "count": count,
            "amount": amount,
            "reasoning": decision.get("reasoning", ""),
            "confidence": decision.get("confidence", ""),
            "status": "dry_run" if dry_run else "open",
            "portfolio_balance": portfolio_balance,
            "fee": fee_amount
        }
        
        fee_msg = f" | Fee: ${fee_amount:.2f}" if fee_amount else ""
        balance_msg = f" | Balance: ${portfolio_balance:.2f}" if portfolio_balance else ""
        print(f"Logging bet to Supabase: {data['ticker']} ({data['side']}){fee_msg}{balance_msg}")
        supabase.table("bets").insert(data).execute()
        print("Successfully logged to Supabase.")
        
    except Exception as e:
        print(f"Error logging to Supabase: {e}")

def check_and_update_bet_statuses(client):
    """
    Queries Supabase for all bets with status == 'open', checks with Kalshi 
    if they are still open, and if settled, determines if won or lost and updates status.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        print("Warning: SUPABASE_URL or SUPABASE_KEY not found. Skipping status check.")
        return
    
    try:
        supabase: Client = create_client(url, key)
        
        # Query for all open bets
        print("\n" + "="*50)
        print("CHECKING STATUS OF OPEN BETS")
        print("="*50 + "\n")
        
        response = supabase.table("bets").select("*").eq("status", "open").execute()
        open_bets = response.data
        
        if not open_bets:
            print("No open bets found.\n")
            return
        
        print(f"Found {len(open_bets)} open bet(s) to check.\n")
        
        for bet in open_bets:
            bet_id = bet.get("id")
            ticker = bet.get("ticker")
            side = bet.get("side", "").upper()
            price = bet.get("price", 0)
            count = bet.get("count", 0)
            
            print(f"Checking bet #{bet_id}: {ticker} ({side})...")
            
            # Get market info from Kalshi
            market = client.get_market(ticker)
            
            if not market:
                print(f"  Warning: Could not fetch market data for {ticker}. Skipping.\n")
                continue
            
            market_status = market.get("status", "")
            result = market.get("result", "")
            
            print(f"  Market Status: {market_status}")
            
            # Check if market is settled
            if market_status in ["closed", "settled", "finalized"]:
                print(f"  Market Result: {result}")
                
                # Determine if bet won or lost
                new_status = None
                
                if result == "yes":
                    new_status = "won" if side == "YES" else "lost"
                elif result == "no":
                    new_status = "won" if side == "NO" else "lost"
                else:
                    print(f"  Warning: Unknown result '{result}' for {ticker}. Leaving as open.\n")
                    continue
                
                # Update the bet status in Supabase
                print(f"  Updating bet to: {new_status.upper()}")
                supabase.table("bets").update({"status": new_status}).eq("id", bet_id).execute()
                print(f"  ✓ Successfully updated bet #{bet_id} to {new_status}\n")
                
            else:
                print(f"  Market still open. No update needed.\n")
        
        print("="*50)
        print("FINISHED CHECKING BET STATUSES")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"Error checking bet statuses: {e}\n")


def main():
    load_dotenv()
    client = KalshiClient()
    
    # Check and update statuses of existing open bets
    check_and_update_bet_statuses(client)
    
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
    
    # Take top 25 to avoid token limits and noise
    top_markets = active_markets[:15]

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
            # Enrich decision with market details (Title, Subtitle, Rules)
            # Find the market in top_markets that matches the ticker
            matching_market = next((m for m in top_markets if m.get("ticker") == decision["ticker"]), None)
            
            if matching_market:
                decision["title"] = matching_market.get("title", "")
                decision["subtitle"] = matching_market.get("subtitle") or matching_market.get("yes_sub_title", "")
                decision["rules"] = matching_market.get("rules_primary", "")
                
            execute_bet(client, decision, dry_run=dry_run)
        else:
            print("Could not parse a valid trade decision from the LLM output.")

if __name__ == "__main__":
    main()
