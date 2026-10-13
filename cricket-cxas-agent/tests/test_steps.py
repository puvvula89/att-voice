from knowledge.steps import normalize_step


def mk(text, notes=None):
    return {"n": 3, "text": text, "notes": notes or [], "links": [], "options": [], "substeps": [], "image_url": ""}


def test_restart_is_call_ending():
    s = normalize_step(mk("Restart your iPhone by holding the side button."), "x")
    assert s["call_ending"] and not s["destructive"]


def test_network_reset_is_call_ending_not_destructive():
    s = normalize_step(mk("Tap Reset Network Settings."), "x")
    assert s["call_ending"] and not s["destructive"]


def test_erase_is_destructive():
    s = normalize_step(mk("Tap Erase All Content and Settings."), "x")
    assert s["destructive"]


def test_keyword_in_warning_note_does_not_flag_the_step():
    s = normalize_step(mk("Tap Reset.", notes=["Erase All Content and Settings - this wipes the phone."]), "x")
    assert not s["destructive"] and not s["call_ending"]
    assert s["warning"] and "Erase" in s["warning"]


def test_article_heading_split():
    s = normalize_step(mk("Check your connection\nCheck the cellular signal status icon."), "x")
    assert s["heading"] == "Check your connection" and s["text"].startswith("Check the cellular")


def test_short_procedure_step_has_no_heading():
    s = normalize_step(mk("From within Settings, tap General."), "x")
    assert s["heading"] == ""


def test_menu_prompt_step_takes_flags_from_its_option_notes():
    # "From this screen…:" lists the options as notes; tapping Reset Network Settings ends the call.
    s = normalize_step(mk("From this screen, you can perform a variety of actions:",
                          notes=["Reset Network Settings - resets just your network settings.",
                                 "Erase All Content and Settings - returns the device to factory settings."]), "x")
    assert s["call_ending"] and s["destructive"]
