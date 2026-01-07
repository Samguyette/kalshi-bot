"""
Shared utilities.
"""

def clean_markdown(text):
    """Simple helper to strip markdown syntax like bolding."""
    if not isinstance(text, str):
        return text
    return text.replace("**", "")


def check_sufficient_balance(client, min_cents=500):
    """
    Checks if the user has sufficient balance.
    Returns True if balance >= min_cents, False otherwise.
    """
    balance_data = client.get_balance()
    if balance_data:
        balance_cents = balance_data.get("balance", 0)
        if balance_cents < min_cents:
            print(f"Insufficient balance: ${balance_cents/100:.2f} < ${min_cents/100:.2f}. Exiting.")
            return False
    return True
