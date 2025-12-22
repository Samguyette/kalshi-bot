import requests
import os
import time
import base64
import json
from typing import Dict, Any, Optional
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

class KalshiClient:
    """
    A lightweight wrapper for the Kalshi Public API (v2).
    """
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self):
        self.session = requests.Session()
        self.key_id = os.environ.get("KALSHI_API_KEY_ID")
        self.private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        self.private_key = None
        
        if self.private_key_path:
            try:
                with open(self.private_key_path, "rb") as key_file:
                    self.private_key = serialization.load_pem_private_key(
                        key_file.read(),
                        password=None
                    )
            except Exception as e:
                print(f"Error loading private key: {e}")

    def sign_request(self, method: str, path: str, timestamp: str) -> str:
        """
        Generates the RSA-PSS signature required for Kalshi authentication.
        Message format: timestamp + method + path (body is NOT included in V2 signature)
        """
        if not self.private_key:
            return ""
            
        # Message = timestamp + method + path (body is NOT included in V2 signature)
        message = f"{timestamp}{method}{path}".encode('utf-8')
        
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode('utf-8')

    def get_markets(self, min_close_ts: Optional[int] = None, max_close_ts: Optional[int] = None, limit: int = 1000, cursor: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetches a single page of markets from the API.
        """
        url = f"{self.BASE_URL}/markets"
        params = {"limit": limit}
        
        if min_close_ts:
            params["min_close_ts"] = min_close_ts
        if max_close_ts:
            params["max_close_ts"] = max_close_ts
        if cursor:
            params["cursor"] = cursor
            
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching markets: {e}")
            return {"markets": []}

    def get_all_markets(self, min_close_ts: Optional[int] = None, max_close_ts: Optional[int] = None) -> list:
        """
        Fetches ALL markets by paginating through results.
        """
        all_markets = []
        cursor = None
        
        while True:
            data = self.get_markets(min_close_ts, max_close_ts, limit=1000, cursor=cursor)
            markets = data.get("markets", [])
            if not markets:
                break
                
            all_markets.extend(markets)
            cursor = data.get("cursor")
            
            if not cursor:
                break
                
        return all_markets

    def place_order(self, ticker: str, side: str, count: int, price: float) -> Optional[Dict[str, Any]]:
        """
        Places a limit order on Kalshi.
        """
        if not self.key_id or not self.private_key:
            print("Error: Missing credentials for order placement.")
            return None
            
        path = "/portfolio/orders"
        url = f"{self.BASE_URL}{path}"
        method = "POST"
        timestamp = str(int(time.time() * 1000))
        
        # Format price to dollars (Kalshi expects dollars for yes_price/no_price?) 
        # Actually in V2 docs, for 'yes_price' it is usually in cents.
        # WAIT: Let's check docs or assume dollars from the variable name but API usually takes cents?
        # Re-reading gathered context: "yes_price or no_price: The price in cents if using a limit order."
        # The tool response regarding place_order says "yes_price or no_price: The price in cents". 
        # But let's be careful. The code currently parses dollars. 
        # If the input `price` is in dollars (e.g. 0.50), convert to cents (50).
        
        price_cents = int(price * 100)
        
        payload = {
            "ticker": ticker,
            "action": "buy",
            "side": side.lower(), # "yes" or "no"
            "count": count,
            "type": "limit",
            "client_order_id": str(int(time.time() * 1000000)) # Simple unique ID
        }
        
        if side.lower() == "yes":
            payload["yes_price"] = price_cents
        else:
            payload["no_price"] = price_cents
        
        # Serialize the body for signing
        body_str = json.dumps(payload, separators=(',', ':'))
            
        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": self.sign_request(method, "/trade-api/v2" + path, timestamp),
            "Content-Type": "application/json"
        }
        
        try:
            print(f"Placing order: {json.dumps(payload, indent=2)}")
            response = self.session.post(url, data=body_str, headers=headers)
            response.raise_for_status()
            print("Order placed successfully!")
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error placing order: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None

    def get_balance(self) -> Optional[Dict[str, Any]]:
        """
        Fetches the user's balance. Useful for verifying authentication.
        """
        if not self.key_id or not self.private_key:
            print("Error: Missing credentials for balance check.")
            return None
            
        path = "/portfolio/balance"
        url = f"{self.BASE_URL}{path}"
        method = "GET"
        timestamp = str(int(time.time() * 1000))
        
        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": self.sign_request(method, "/trade-api/v2" + path, timestamp),
            "Content-Type": "application/json"
        }
        
        try:
            print(f"Fetching balance...")
            response = self.session.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching balance: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None
