"""
LLM service layer for prompt generation and API calls.
"""
import os
import json
import re
from datetime import datetime, timezone
from google import genai
from google.genai import types

from market_formatter import format_market_for_prompt


def generate_llm_prompt(markets, active_bets, prompt_version):
    """
    Generates the full prompt for the Thinking LLM using the template file.
    """
    # Load the prompt template
    template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts', f'{prompt_version}.md')
    
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
    
    # Format active portfolio/bets
    if active_bets:
        portfolio_lines = []
        for bet in active_bets:
            # Simplify output: Ticker, Side, Title
            line = f"- {bet.get('side')} on {bet.get('ticker')} ({bet.get('title')})"
            portfolio_lines.append(line)
        portfolio_text = "\n".join(portfolio_lines)
    else:
        portfolio_text = "No active positions."
    
    # Replace the placeholders
    prompt = prompt_template.replace("[MARKET DATA GOES HERE]", markets_text)
    prompt = prompt.replace("[PORTFOLIO_DATA]", portfolio_text)
    
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
        
        # Method 1: Regex for ```json ... ``` blocks
        json_block_match = re.search(r"```json\s*(.*?)```", cleaned_output, re.DOTALL)
        if json_block_match:
            cleaned_output = json_block_match.group(1)
        else:
            # Method 2: Regex for generic ``` ... ``` blocks
            # We look for the first block that looks like it might contain a JSON object (starts with {)
            code_block_match = re.search(r"```\s*({.*})\s*```", cleaned_output, re.DOTALL)
            if code_block_match:
                cleaned_output = code_block_match.group(1)
            else:
                # Method 3: Fallback - find the first '{' and last '}'
                start_idx = cleaned_output.find("{")
                end_idx = cleaned_output.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    cleaned_output = cleaned_output[start_idx:end_idx+1]
        
        # Strip whitespace again after extraction
        cleaned_output = cleaned_output.strip()
        
        # Remove trailing comma before closing brace (common LLM mistake)
        # Match pattern like: ,"  } or ,\n}
        cleaned_output = re.sub(r',(\s*})$', r'\1', cleaned_output)
        
        # Parse JSON
        data = json.loads(cleaned_output)
        
        def clean_str(s):
            if isinstance(s, str):
                return s.replace("**", "")
            return s
        
        # Use .get() defensively
        decision_type = clean_str(data.get("decision", "BET"))
        
        if decision_type == "PASS":
            return {
                "decision": "PASS",
                "reasoning": clean_str(data.get("reasoning"))
            }

        return {
            "decision": "BET",
            "ticker": clean_str(data.get("ticker")),
            "side": clean_str(data.get("side")),
            "price": float(data.get("price", 0.0)),
            "reasoning": clean_str(data.get("reasoning")),
            "confidence": clean_str(data.get("confidence"))
        }
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from LLM: {e}")
        print(f"Attempted to parse: {cleaned_output[:500]}...")
        return None
    except Exception as e:
        print(f"Unexpected error parsing LLM output: {e}")
        return None
