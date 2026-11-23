"""Scrub secrets out of text before it is printed."""

import os
import re

def scrub(text):
    """Return text with passcodes, tokens, and credential URLs removed."""
    if text is None:
        return ""
    cleaned = str(text)
    for key in ("CA_PASSCODE", "CA_TICKS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value and len(value) >= 4:
            cleaned = cleaned.replace(value, "[redacted]")
    cleaned = re.sub(r"x-access-token:[^\s@]+", "x-access-token:[redacted]", cleaned)
    cleaned = re.sub(r"https://[^/\s:@]+:[^/\s@]+@", "https://", cleaned)
    cleaned = re.sub(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "[redacted]", cleaned)
    cleaned = re.sub(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", "[redacted]", cleaned)
    return cleaned
