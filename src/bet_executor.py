"""
Bet execution logic.
"""
import math

from bet_tracker import log_bet_to_supabase


def execute_bet(client, decision, dry_run=False):
    """
    Executes the bet based on the parsed decision.
    Bet size is fixed at ~$4.00.
    """
    if not decision:
        return
        
    ticker = decision["ticker"]
    
    # CHECK MAX EXPOSURE (Max 2 bets per market ever)
    # We do this check first to save computation/logging for skipped bets
    from bet_tracker import get_bet_count_for_ticker
    existing_bets = get_bet_count_for_ticker(ticker)
    
    if existing_bets >= 2:
        print(f"\n" + "!"*50)
        print(f"SKIP: Max exposure reached for {ticker}")
        print(f"Existing bets: {existing_bets} (Limit: 2)")
        print("!"*50 + "\n")
        return

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
