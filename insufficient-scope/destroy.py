"""Delete the scope-probe engine left behind by a KEEP_ENGINE=1 deploy."""
import os
import sys

import vertexai

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
if not PROJECT:
    sys.exit("ERROR: set GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".engine_name")
name = os.environ.get("ENGINE_NAME") or (open(path).read().strip() if os.path.exists(path) else "")
if not name:
    sys.exit("No engine to delete (set ENGINE_NAME or run a KEEP_ENGINE=1 deploy first).")

client = vertexai.Client(project=PROJECT, location=LOCATION)
client.agent_engines.delete(name=name, force=True)
print("DESTROYED:", name)
if os.path.exists(path):
    os.remove(path)
