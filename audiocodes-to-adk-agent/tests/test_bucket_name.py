from deploy.bucket import derive_bucket_name


def test_derives_from_project_and_number():
    assert derive_bucket_name("acme-demo", "1234567890") == "acme-demo-1234567890-agent-engine"


def test_override_wins():
    assert derive_bucket_name("proj", "123", override="my-bucket") == "my-bucket"


def test_no_number_falls_back():
    assert derive_bucket_name("proj", None) == "proj-agent-engine"


def test_lowercased():
    assert derive_bucket_name("Proj-ID", "9") == "proj-id-9-agent-engine"
