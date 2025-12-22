# Kalshi Analysis Bot

A Python tool to analyze prediction markets on Kalshi. It fetches markets closing within the next 7 days, filters for liquidity, and generates a prompt for a thinking LLM to identify the best Expected Value (EV) trades.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install requests
    ```

2.  **Usage**:
    Run the analysis script:
    ```bash
    python3 src/daily_analysis.py
    ```

## Features

*   **Time Window**: Analyzes markets closing between **24 hours and 7 days** from now (skips immediate volatility).
*   **Liquidity Filter**: Removes inactive markets (Volume/Liquidity = 0).
*   **Smart Prompting**: Generates a structured prompt that calculates Spread (Vigorish) and penalizes long-shot bets keying the LLM into profitable EV strategies.
*   **Pagination**: Fetches all available markets from the API.

## Structure

*   `src/daily_analysis.py`: Main entry point. Fetches data and prints the LLM prompt.
*   `src/kalshi_client.py`: API client for `api.elections.kalshi.com`.
