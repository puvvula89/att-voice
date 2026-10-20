"""Shared names and guards for the bootstrap scripts. Every value comes from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROJECT = os.environ.get("CXAS_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = os.environ.get("CXAS_LOCATION", "us")
MODEL = os.environ["CARE_LIVE_MODEL"]
APP_ID = os.environ.get("CARE_APP_ID", "cricket-care")
APP = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
DEMO_CUSTOMER_ID = os.environ.get("DEMO_CUSTOMER_ID", "cust_2001")

CONCIERGE_ID = "care-concierge"
TECH_ID = "tech-support"
BILLING_ID = "billing-support"
SUPPORT_TOOLSET_ID = "support"
END_SESSION = f"{APP}/tools/end_session"
SEARCH_TOOL = f"{APP}/tools/search-tutorials"
NEXT_STEP_TOOL = f"{APP}/tools/next-step"
DATASTORE = (f"projects/{PROJECT}/locations/global/collections/default_collection/dataStores/"
             f"{os.environ.get('DATASTORE_ID', 'cricket-tutorials')}")


def agent_name(agent_id: str) -> str:
    return f"{APP}/agents/{agent_id}"


def source(agent_dir: str, name: str) -> str:
    return (ROOT / "agents" / agent_dir / name).read_text()


def instruction(agent_dir: str) -> str:
    text = (ROOT / "agents" / agent_dir / "instruction.txt").read_text()
    return text.replace("{{DEMO_CUSTOMER_ID}}", DEMO_CUSTOMER_ID)


def existing(fn, *a, **k):
    """Create-if-missing guard: the platform reports an existing resource inconsistently."""
    from google.api_core import exceptions as gax

    try:
        return fn(*a, **k)
    except (gax.AlreadyExists, gax.InternalServerError) as e:
        # InternalServerError is how the platform sometimes reports a duplicate.
        print(f"   (create skipped: {type(e).__name__}) — will update in place")
        return None
