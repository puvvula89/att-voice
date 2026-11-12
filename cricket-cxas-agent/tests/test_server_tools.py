import asyncio

from support_mcp.server import mcp

EXPECTED = {"get_progress", "save_progress", "get_lines",
            "get_line_status", "check_outage", "get_data_usage", "get_sim_status", "refresh_network",
            "send_guide_link", "open_ticket", "sign_images"}


def test_exactly_the_expected_tools_are_registered():
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED


def test_every_tool_description_says_when_to_call_it():
    for t in asyncio.run(mcp.list_tools()):
        d = t.description.lower()
        assert "call this" in d or "use this" in d, t.name


def test_sign_images_signs_only_valid_names(monkeypatch):
    from support_mcp import tools_images as I

    class Blob:
        def __init__(self, name): self.name = name
        def generate_signed_url(self, **kw): return f"https://signed/{self.name}?by={kw['service_account_email']}"

    class Bucket:
        def blob(self, name): return Blob(name)

    class Creds:
        service_account_email, token = "sa@x", "t"
        def refresh(self, _): pass

    monkeypatch.setattr(I, "_bucket", lambda: Bucket())
    monkeypatch.setattr(I.google.auth, "default", lambda scopes: (Creds(), "p"))
    out = I.sign_images("0123456789abcdef.jpeg, ../etc/passwd, 0123456789abcdef.jpeg,fedcba9876543210.png")
    assert out == {"images": {"0123456789abcdef.jpeg": "https://signed/0123456789abcdef.jpeg?by=sa@x",
                              "fedcba9876543210.png": "https://signed/fedcba9876543210.png?by=sa@x"}}
    assert I.sign_images("") == {"images": {}}
