import re
import unicodedata

def normalize_text_spacing(text: str) -> str:
    """Collapses consecutive whitespace and trims."""
    # Replace non-breaking spaces, zero-width spaces, etc with standard space
    # \s also matches \n, \t, etc.
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def standardize_quotes(text: str) -> str:
    """Standardizes typographic quotes and apostrophes."""
    text = re.sub(r'[‘’´]', "'", text)
    text = re.sub(r'[“”]', '"', text)
    return text

def normalize_jd_text_for_spans(text: str) -> str:
    """Applies NFKC normalization and standardizes quotes on the full text."""
    text = unicodedata.normalize('NFKC', text)
    text = standardize_quotes(text)
    return text

def split_jd_into_spans(raw_text: str) -> dict[str, str]:
    """
    Deterministically splits the raw JD into stable spans.
    Returns mapping of span_id -> normalized span text.
    """
    text = normalize_jd_text_for_spans(raw_text)
    
    # Split by paragraph breaks or list item markers
    # List markers: lines starting with -, *, •, or \d+.
    # We'll split on double newlines OR before a line that starts with a list marker.
    # To keep things simple and robust:
    blocks = re.split(r'\n\s*\n|(?=\n\s*(?:[-*•]|\d+\.)\s)', text)
    
    spans = {}
    for i, block in enumerate(blocks):
        span_text = normalize_text_spacing(block)
        if span_text:
            span_id = f"jd_{i:03d}"
            spans[span_id] = span_text
            
    return spans

def normalize_quote_for_match(quote: str) -> str:
    """Applies normalization steps 2, 3, 4, 6 to the raw quote for substring matching."""
    q = unicodedata.normalize('NFKC', quote)
    q = standardize_quotes(q)
    return normalize_text_spacing(q)

def extract_digit_sequences(text: str) -> set[str]:
    """
    Extracts base digit sequences after removing commas, currency, %, and approx symbols.
    """
    # 1. Strip commas surrounded by digits
    text = re.sub(r'(?<=\d),(?=\d)', '', text)
    
    # 2. Remove currency symbols and percentages
    # 3. Remove approximation words/symbols
    # To avoid complex regex for all currency symbols, we can just find the digits themselves.
    # The rule says: remove approximation words/symbols. This doesn't affect the digit extraction
    # if we just extract \b\d+(?:\.\d+)?\b.
    # But wait, words like "roughly" or symbols like "~" don't get matched by \d+.
    # So we can just extract digit sequences directly.
    # E.g. "$100" -> "100". "~60%" -> "60". "1,000" -> "1000" (comma removed first).
    
    matches = re.findall(r'\d+(?:\.\d+)?', text)
    return set(matches)
