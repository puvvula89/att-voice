import asyncio

from support_mcp.server import mcp

EXPECTED = {"get_progress", "save_progress", "get_lines",
            "get_line_status", "check_outage", "get_data_usage", "get_sim_status", "refresh_network",
            "send_guide_link", "open_ticket"}


def test_exactly_the_expected_tools_are_registered():
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED


def test_every_tool_description_says_when_to_call_it():
    for t in asyncio.run(mcp.list_tools()):
        d = t.description.lower()
        assert "call this" in d or "use this" in d, t.name
