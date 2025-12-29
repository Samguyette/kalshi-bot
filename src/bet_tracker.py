"""
Bet tracking and persistence layer (Supabase).
"""
import os
from datetime import datetime, timezone
from supabase import create_client, Client


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
            "fee": fee_amount,
            "prompt_used": decision.get("prompt_used", "unknown")
        }
        
        fee_msg = f" | Fee: ${fee_amount:.2f}" if fee_amount else ""
        balance_msg = f" | Balance: ${portfolio_balance:.2f}" if portfolio_balance else ""
        prompt_msg = f" | Prompt: {data['prompt_used']}"
        print(f"Logging bet to Supabase: {data['ticker']} ({data['side']}){fee_msg}{balance_msg}{prompt_msg}")
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
                
                # Normalize result string
                result_clean = str(result).lower().strip()
                
                if result_clean == "yes":
                    new_status = "won" if side == "YES" else "lost"
                elif result_clean == "no":
                    new_status = "won" if side == "NO" else "lost"
                elif result_clean in ["void", "canceled", "cancelled", "refunded"]:
                    new_status = "void"
                elif result_clean == "" and market_status == "finalized":
                    # Market finalized but no binary result (likely fair value settlement)
                    new_status = "settled"
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
