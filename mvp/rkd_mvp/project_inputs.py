"""Shared project rules for both explicit persistence adapters."""


def project_name(value):
    name = str(value or "").strip()
    if not name or len(name) > 200:
        raise ValueError("name must contain 1 to 200 characters")
    return name


def project_version(value):
    if isinstance(value, bool):
        raise ValueError("expected_version must be a non-negative integer")
    text = str(value)
    if not text.isdecimal():
        raise ValueError("expected_version must be a non-negative integer")
    return int(text)
