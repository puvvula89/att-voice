from relay.call_steering import route, ROUTES, DEFAULT_KEY


def test_known_intents_route_to_correct_backend():
    assert route("internet").backend == "adk"
    assert route("phone_upgrade").backend == "adk"
    assert route("billing").backend == "ces"


def test_intent_is_normalized():
    assert route("  Billing ").key == "billing"


def test_unknown_intent_falls_back_to_default():
    assert route("nonsense").key == DEFAULT_KEY
    assert route("").key == DEFAULT_KEY


def test_registry_covers_three_specialists():
    assert set(ROUTES) == {"internet", "phone_upgrade", "billing"}
