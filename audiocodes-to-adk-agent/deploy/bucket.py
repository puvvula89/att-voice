"""Staging-bucket resolution for Agent Engine deploys.

The bucket name is derived from the project id + project number so it is
globally unique and never hardcoded; an explicit STAGING_BUCKET overrides it.
"""

from __future__ import annotations


def derive_bucket_name(project: str, project_number: str | None = None,
                       override: str = "") -> str:
    """Return the staging-bucket NAME (no ``gs://`` prefix).

    Precedence: an explicit ``override`` wins; otherwise derive
    ``{project}-{project_number}-agent-engine`` (or ``{project}-agent-engine``
    when no number is given). Lowercased to satisfy GCS naming rules.
    """
    if override and override.strip():
        return override.strip()
    suffix = f"-{project_number}" if project_number else ""
    return f"{project}{suffix}-agent-engine".lower()


def ensure_staging_bucket(project: str, project_number: str | None,
                          location: str, override: str = "") -> str:
    """Resolve the bucket name and create it in ``project``/``location`` if missing.

    Idempotent: returns the existing bucket when present. Returns the bucket name.
    """
    name = derive_bucket_name(project, project_number, override)
    from google.cloud import storage

    client = storage.Client(project=project)
    bucket = client.bucket(name)
    if bucket.exists():
        print(f"Using existing staging bucket gs://{name}")
    else:
        print(f"Creating staging bucket gs://{name} in {location}...")
        client.create_bucket(bucket, location=location)
    return name
