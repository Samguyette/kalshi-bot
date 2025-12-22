import requests
from typing import Dict, Any, Optional

class KalshiClient:
    """
    A lightweight wrapper for the Kalshi Public API (v2).
    Uses the elections.kalshi.com endpoint which does not require authentication
    for basic market data.
    """
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self):
        self.session = requests.Session()

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
