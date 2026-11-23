#!/usr/bin/env python3
"""List decision files from the private ticks repo.

Reads CA_TICKS_TOKEN from the environment. Prints the decisions as JSON.
With --archive, moves each decision from decisions/ to archive/<UTC date>/.
Never prints the token.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

TOOLS_DIR = __import__("pathlib").Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from decision_format import DecisionFormatError, parse_decision_record  # noqa: E402
from redact import scrub  # noqa: E402

TICKS_REPO = "ianbanner/christian-approvals-ticks"
API = "https://api.github.com"
USER_AGENT = "christian-approvals-tools"


class TicksError(RuntimeError):
    """A ticks repo request failed."""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print decisions from the private ticks repo.")
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Move decisions from decisions/ to archive/<date>/ in the ticks repo.",
    )
    args = parser.parse_args(argv)

    token = os.environ.get("CA_TICKS_TOKEN", "")
    if token == "":
        raise TicksError("CA_TICKS_TOKEN is not set.")

    records = list_decisions(token)
    print(json.dumps([public_decision(record) for record in records], indent=2, ensure_ascii=False))
    if args.archive:
        archive_decisions(token, records)
    return 0


def public_decision(record):
    shown = {field: record[field] for field in ("id", "decision", "note", "decided_at")}
    shown["path"] = record.get("path")
    return shown


def list_decisions(token):
    github(token, "GET", f"/repos/{TICKS_REPO}")
    listing = github(token, "GET", f"/repos/{TICKS_REPO}/contents/decisions")
    if listing is None:
        return []
    if isinstance(listing, dict):
        raise TicksError("decisions/ is not a directory in the ticks repo.")
    if not isinstance(listing, list):
        raise TicksError("Unexpected listing from the ticks repo.")

    records = []
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        if entry.get("type") != "file" or not name.endswith(".json"):
            continue
        path = entry.get("path") or f"decisions/{name}"
        document = github(token, "GET", f"/repos/{TICKS_REPO}/contents/{path}")
        try:
            decoded = _decode_content(document)
            record = parse_decision_record(json.loads(decoded.decode("utf-8")))
        except (TicksError, DecisionFormatError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"warning: skipped {path}: {scrub(str(exc))}", file=sys.stderr)
            continue
        record["path"] = path
        record["sha"] = document.get("sha")
        records.append(record)
    records.sort(key=lambda record: record["path"])
    return records


def archive_decisions(token, records):
    if not records:
        print("No decisions to archive.", file=sys.stderr)
        return
    repo = github(token, "GET", f"/repos/{TICKS_REPO}")
    branch = repo.get("default_branch") or "main"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for record in records:
        source = record["path"]
        name = source.rsplit("/", 1)[-1]
        destination = f"archive/{day}/{name}"
        document = github(token, "GET", f"/repos/{TICKS_REPO}/contents/{source}")
        content_b64 = _reencode_content(document)
        existing_sha = _existing_sha(token, destination)
        put_body = {
            "message": f"Archive decision {record['id']}",
            "content": content_b64,
            "branch": branch,
        }
        if existing_sha:
            put_body["sha"] = existing_sha
        github(token, "PUT", f"/repos/{TICKS_REPO}/contents/{destination}", put_body)
        source_sha = document.get("sha")
        if not source_sha:
            raise TicksError(f"Copied {source} but the original sha was missing, so it was left in place.")
        try:
            github(
                token,
                "DELETE",
                f"/repos/{TICKS_REPO}/contents/{source}",
                {"message": f"Archive decision {record['id']}", "sha": source_sha, "branch": branch},
            )
        except TicksError as exc:
            raise TicksError(
                f"Copied {source} to {destination} but could not remove the original. {exc}"
            ) from exc
        print(f"Archived {source} -> {destination}", file=sys.stderr)


def github(token, method, path, body=None):
    url = API + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET" and path.endswith("/contents/decisions"):
            return None
        detail = exc.read().decode("utf-8", "replace")
        message = _github_message(detail, exc.code)
        raise TicksError(f"GitHub returned {exc.code}: {scrub(message)}") from exc
    except urllib.error.URLError as exc:
        raise TicksError(f"Could not reach GitHub: {scrub(str(exc.reason))}") from exc
    if status == 204 or raw == b"":
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TicksError("GitHub returned a response that was not JSON.") from exc


def _github_message(detail, status):
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return f"HTTP {status}"
    message = parsed.get("message") if isinstance(parsed, dict) else None
    if isinstance(message, str) and message:
        return message
    return f"HTTP {status}"


def _decode_content(document):
    if not isinstance(document, dict) or "content" not in document:
        raise TicksError("Decision file content was missing.")
    try:
        return base64.b64decode(document["content"])
    except (ValueError, TypeError) as exc:
        raise TicksError("Decision file content was not base64.") from exc


def _reencode_content(document):
    return base64.b64encode(_decode_content(document)).decode("ascii")


def _existing_sha(token, path):
    try:
        document = github(token, "GET", f"/repos/{TICKS_REPO}/contents/{path}")
    except TicksError as exc:
        if str(exc).startswith("GitHub returned 404"):
            return None
        raise
    if isinstance(document, dict):
        return document.get("sha")
    return None


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TicksError as exc:
        print(f"error: {scrub(str(exc))}", file=sys.stderr)
        raise SystemExit(1)
