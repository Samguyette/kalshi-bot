"""
Daily analysis orchestration - entry point for the Kalshi trading bot.
"""
import os
from dotenv import load_dotenv

from kalshi_client import KalshiClient
from market_formatter import get_analysis_window
from llm_service import generate_llm_prompt, call_google_llm, parse_llm_decision
from bet_executor import execute_bet
from bet_tracker import check_and_update_bet_statuses


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
    
    # Take top 15 to avoid token limits and noise
    top_markets = active_markets[:15]

    # Generate and print prompt
    PROMPT_VERSION = "v2"
    prompt = generate_llm_prompt(top_markets, prompt_version=PROMPT_VERSION)
    
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
                decision["prompt_used"] = PROMPT_VERSION
                
            execute_bet(client, decision, dry_run=dry_run)
        else:
            print("Could not parse a valid trade decision from the LLM output.")


if __name__ == "__main__":
    main()
