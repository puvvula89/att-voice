from backend.voice_shaping import flatten_events


def test_returns_final_model_text():
    events = [
        {"content": {"role": "model", "parts": [{"text": "Hello there."}]}},
    ]
    assert flatten_events(events) == "Hello there."


def test_drops_pending_ui_and_keeps_text():
    events = [
        {"actions": {"stateDelta": {"pending_ui": {"stage_intent": "line_selector"}}}},
        {"content": {"role": "model", "parts": [{"text": "Pick a line."}]}},
    ]
    assert flatten_events(events) == "Pick a line."


def test_ignores_partial_events():
    events = [
        {"content": {"role": "model", "parts": [{"text": "Pick"}]}, "partial": True},
        {"content": {"role": "model", "parts": [{"text": "Pick a line."}]}},
    ]
    assert flatten_events(events) == "Pick a line."


def test_ignores_non_model_roles_and_control_messages():
    events = [
        {"type": "session_info", "session_id": "s1", "resumed": False},
        {"content": {"role": "user", "parts": [{"text": "trade in my phone"}]}},
        {"content": {"role": "model", "parts": [{"text": "Sure, let's do that."}]}},
    ]
    assert flatten_events(events) == "Sure, let's do that."


def test_joins_multiple_final_model_events_with_space():
    events = [
        {"content": {"role": "model", "parts": [{"text": "One."}]}},
        {"content": {"role": "model", "parts": [{"text": "Two."}]}},
    ]
    assert flatten_events(events) == "One. Two."


def test_empty_stream_returns_empty_string():
    assert flatten_events([]) == ""


def test_stream_without_text_returns_empty_string():
    events = [
        {"actions": {"stateDelta": {"pending_ui": {"stage_intent": "receipt"}}}},
        {"content": {"role": "model", "parts": [{"functionCall": {"name": "x"}}]}},
    ]
    assert flatten_events(events) == ""


def test_tolerates_events_missing_content():
    events = [
        {},
        {"content": {"role": "model", "parts": [{"text": "Still fine."}]}},
    ]
    assert flatten_events(events) == "Still fine."
