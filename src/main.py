"""
Daily analysis orchestration - entry point for the Kalshi trading bot.
"""
import os
from dotenv import load_dotenv

from kalshi_client import KalshiClient
from market_formatter import fetch_and_process_markets
from llm_service import generate_llm_prompt, call_google_llm, parse_llm_decision
from bet_executor import execute_bet
from bet_tracker import check_and_update_bet_statuses, get_active_bets





def clean_markdown(text):
    """Simple helper to strip markdown syntax like bolding."""
    if not isinstance(text, str):
        return text
    return text.replace("**", "")


def main():
    load_dotenv()
    client = KalshiClient()
    
    # Check and update statuses of existing open bets
    check_and_update_bet_statuses(client)
    
    # Fetch and process top markets (fetching, filtering, enriching)
    top_markets = fetch_and_process_markets(client)

    # Fetch active bets for portfolio context
    active_bets = get_active_bets()

    # Generate and print prompt
    PROMPT_VERSION = "v4"
    prompt = generate_llm_prompt(top_markets, active_bets=active_bets, prompt_version=PROMPT_VERSION)
    
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
            if decision.get("decision") == "PASS":
                print(f"Decided to PASS. Reasoning: {decision.get('reasoning')}")
                return

            # Enrich decision with market details (Title, Subtitle, Rules)
            # Find the market in top_markets that matches the ticker
            matching_market = next((m for m in top_markets if m.get("ticker") == decision["ticker"]), None)
            
            if matching_market:
                decision["title"] = clean_markdown(matching_market.get("title", ""))
                decision["subtitle"] = clean_markdown(matching_market.get("subtitle") or matching_market.get("yes_sub_title", ""))
                decision["rules"] = clean_markdown(matching_market.get("rules_primary", ""))
                decision["prompt_used"] = PROMPT_VERSION
                
            execute_bet(client, decision, dry_run=dry_run)
        else:
            print("Could not parse a valid trade decision from the LLM output.")


if __name__ == "__main__":
    main()
