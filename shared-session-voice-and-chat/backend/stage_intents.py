LINE_SELECTOR = "line_selector"
PHONE_OPTIONS = "phone_options"
CONFIRMATION = "confirmation"
RECEIPT = "receipt"

ALL = (LINE_SELECTOR, PHONE_OPTIONS, CONFIRMATION, RECEIPT)

def data_key(stage_intent: str) -> str:
    """Session-state key where a stage_intent's source data is stored."""
    return f"data:{stage_intent}"
