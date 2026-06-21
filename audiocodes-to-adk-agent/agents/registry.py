from __future__ import annotations

from agents.greeter import greeter_agent
from agents.internet import internet_agent
from agents.phone_upgrade import phone_upgrade_agent

# Shared by the Agent Engine app and the local factory.
ADK_AGENTS = {
    "greeter": greeter_agent,
    "internet": internet_agent,
    "phone_upgrade": phone_upgrade_agent,
}
