from relay.session import SessionRecord


def test_add_turn_and_transcript():
    r = SessionRecord(session_id="X", caller="+15551234567")
    r.add_turn("user", "my internet is down")
    r.add_turn("agent", "let's take a look")
    r.add_turn("user", "")  # empty ignored
    assert len(r.turns) == 2
    assert r.transcript_text() == "user: my internet is down\nagent: let's take a look"


def test_set_intent():
    r = SessionRecord(session_id="X")
    assert r.intent is None
    r.set_intent("billing")
    assert r.intent == "billing"


def test_context_summary_includes_intent_and_transcript():
    r = SessionRecord(session_id="X")
    r.set_intent("billing")
    r.add_turn("user", "I have a question about my bill")
    s = r.context_summary()
    assert "billing" in s
    assert "question about my bill" in s
