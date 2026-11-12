"""Short-lived links to tutorial step images in the private images bucket, for the chat channel.

The bucket is never public. The server signs V4 links with its own service account through the IAM
signBlob API (no key file), so the runtime identity needs Token Creator on itself and read access to
the bucket; deploy.sh grants both.
"""
import datetime as dt
import os
import re

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

LINK_MINUTES = int(os.environ.get("IMAGE_LINK_MINUTES", "60"))
_NAME = re.compile(r"^[0-9a-f]{16}\.(jpeg|jpg|png)$")
_client = None


def _bucket():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client.bucket(os.environ["IMAGES_BUCKET"])


def sign_images(names: str) -> dict:
    """{"images": {name: signed link}} for the comma-separated image names; unknown names are skipped."""
    wanted = [n.strip() for n in (names or "").split(",") if _NAME.match(n.strip())]
    if not wanted:
        return {"images": {}}
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    bucket = _bucket()
    links = {n: bucket.blob(n).generate_signed_url(
                 version="v4", expiration=dt.timedelta(minutes=LINK_MINUTES), method="GET",
                 service_account_email=creds.service_account_email, access_token=creds.token)
             for n in dict.fromkeys(wanted)}
    return {"images": links}
