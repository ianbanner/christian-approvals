"""Decision file format written by the dashboard.

Each file is decisions/<id>.json and contains exactly:
  id, decision (approve|reject|change), note, decided_at (UTC ISO-8601)
"""

import re

DECISIONS = ("approve", "reject", "change")
FIELDS = ("id", "decision", "note", "decided_at")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


class DecisionFormatError(ValueError):
    """The decision record does not match the file format."""


def build_decision_record(item_id, decision, note, decided_at):
    """Return the object stored in decisions/<id>.json."""
    if not isinstance(item_id, str) or ID_RE.fullmatch(item_id) is None:
        raise DecisionFormatError("id must be a safe file name token.")
    if decision not in DECISIONS:
        raise DecisionFormatError("decision must be approve, reject, or change.")
    if not isinstance(note, str):
        raise DecisionFormatError("note must be a string.")
    if not isinstance(decided_at, str) or ISO_RE.fullmatch(decided_at) is None:
        raise DecisionFormatError("decided_at must be a UTC ISO-8601 timestamp.")
    return {
        "id": item_id,
        "decision": decision,
        "note": note,
        "decided_at": decided_at,
    }


def parse_decision_record(data):
    """Validate a decoded decision file and return a normalised record."""
    if not isinstance(data, dict):
        raise DecisionFormatError("decision file must be a JSON object.")
    extra = set(data) - set(FIELDS)
    if extra:
        raise DecisionFormatError("decision file has unexpected fields.")
    missing = [field for field in FIELDS if field not in data]
    if missing:
        raise DecisionFormatError("decision file is missing required fields.")
    return build_decision_record(data["id"], data["decision"], data["note"], data["decided_at"])


def decision_relpath(item_id):
    """Relative path inside the ticks repo for an item id."""
    record_id = build_decision_record(item_id, "approve", "", "2020-01-01T00:00:00Z")["id"]
    return f"decisions/{record_id}.json"
