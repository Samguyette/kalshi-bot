# Kalshi Analysis Bot

Automated analysis and trading tool for Kalshi prediction markets using Google's Gemini models.

## Features

*   **Smart Analysis**: Filters liquid markets (1-7 day expiry) to find high EV trades.
*   **LLM Integration**: Uses Google's Gemini models for probability estimation.
*   **Automated Trading**: Executes bets based on LLM confidence.

## Quick Start

1.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Environment** (`.env`):
    ```bash
    GEMINI_API_KEY="your_google_api_key"
    KALSHI_API_KEY_ID="your_kalshi_key_id"
    KALSHI_PRIVATE_KEY_PATH="/abspath/to/private_key.pem"
    DRY_RUN=true # Set to false to enable real trading
    ```

3.  **Run**:
    ```bash
    python3 src/daily_analysis.py
    ```

## Structure

*   `src/daily_analysis.py`: Orchestrates fetching, analysis, and betting.
*   `src/kalshi_client.py`: Kalshi V2 API wrapper (RSA-PSS signing).
