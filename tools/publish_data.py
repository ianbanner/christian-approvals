#!/usr/bin/env python3
"""Encrypt a plaintext items.json file into data.enc.json.

Reads CA_PASSCODE and CA_TICKS_TOKEN from the environment. With --push,
commits and pushes only data.enc.json onto main. Never prints the passcode,
the token, or the plaintext items.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from crypto_box import MIN_ITERATIONS, encrypt_payload  # noqa: E402
from decision_format import ID_RE, ISO_RE  # noqa: E402
from redact import scrub  # noqa: E402

TICKS_REPO = "ianbanner/christian-approvals-ticks"
SECTIONS = {"long_form", "short_form", "audiences"}
ITEM_FIELDS = (
    "id",
    "section",
    "platform",
    "kind",
    "author",
    "url",
    "summary",
    "read_in_full",
    "draft",
    "flags",
    "deadline_iso",
    "deadline_label",
    "status",
    "source_bot",
)
STRING_FIELDS = (
    "id",
    "section",
    "platform",
    "kind",
    "author",
    "url",
    "summary",
    "draft",
    "deadline_iso",
    "deadline_label",
    "status",
    "source_bot",
)


class PublishError(RuntimeError):
    """The publish command cannot continue."""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Encrypt items.json into data.enc.json.")
    parser.add_argument("items_path", help="Path to plaintext items.json. Do not commit this file.")
    parser.add_argument(
        "--output",
        default="data.enc.json",
        help="Where to write the encrypted file (default: data.enc.json).",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Commit and push only data.enc.json to main.",
    )
    args = parser.parse_args(argv)

    passcode = os.environ.get("CA_PASSCODE", "")
    token = os.environ.get("CA_TICKS_TOKEN", "")
    if passcode == "":
        raise PublishError("CA_PASSCODE is not set.")
    if token == "":
        raise PublishError("CA_TICKS_TOKEN is not set.")

    items = load_items(Path(args.items_path))
    payload = build_payload(items, token)
    document = encrypt_payload(payload, passcode, MIN_ITERATIONS)
    output_path = Path(args.output)
    write_document(output_path, document)
    print(f"Wrote {output_path}")

    if args.push:
        push_data_enc(output_path)
    return 0


def load_items(path):
    if not path.is_file():
        raise PublishError(f"Items file not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishError("Items file is not valid UTF-8 JSON.") from exc
    if not isinstance(raw, list):
        raise PublishError("items.json must be a JSON array.")
    items = []
    seen = set()
    for index, item in enumerate(raw):
        normalised = validate_item(item, index)
        if normalised["id"] in seen:
            raise PublishError(f"Duplicate item id: {normalised['id']}")
        seen.add(normalised["id"])
        items.append(normalised)
    return items


def validate_item(item, index):
    label = f"item {index + 1}"
    if not isinstance(item, dict):
        raise PublishError(f"{label} must be an object.")
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        label = f"item {item_id}"
    missing = [field for field in ITEM_FIELDS if field not in item]
    if missing:
        raise PublishError(f"{label} is missing {', '.join(missing)}.")
    for field in STRING_FIELDS:
        if not isinstance(item[field], str):
            raise PublishError(f"{label} field {field} must be a string.")
    if item["section"] not in SECTIONS:
        raise PublishError(f"{label} section must be long_form, short_form, or audiences.")
    if not isinstance(item["read_in_full"], bool):
        raise PublishError(f"{label} field read_in_full must be true or false.")
    if not isinstance(item["flags"], list) or not all(isinstance(flag, str) for flag in item["flags"]):
        raise PublishError(f"{label} field flags must be an array of strings.")
    if ID_RE.fullmatch(item["id"]) is None:
        raise PublishError(f"{label} id cannot be used as a file name.")
    url = item["url"]
    if url and not (url.startswith("https://") or url.startswith("http://")):
        raise PublishError(f"{label} url must start with http:// or https://.")
    if item["deadline_iso"]:
        if ISO_RE.fullmatch(item["deadline_iso"]) is None:
            raise PublishError(f"{label} deadline_iso must be a UTC ISO-8601 timestamp or empty.")
    cleaned = dict(item)
    return cleaned


def build_payload(items, token, generated_at=None):
    if not isinstance(token, str) or token == "":
        raise PublishError("CA_TICKS_TOKEN is not set.")
    stamp = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_at": stamp,
        "ticks_repo": TICKS_REPO,
        "ticks_token": token,
        "items": items,
    }


def write_document(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def push_data_enc(output_path):
    """Commit the working tree data.enc.json onto origin/main and push that file only."""
    repo_root = _repo_root()
    target = (repo_root / "data.enc.json").resolve()
    written = output_path.resolve()
    if written != target:
        raise PublishError("--push only publishes data.enc.json at the repository root.")
    if not target.is_file():
        raise PublishError("data.enc.json is missing, so there is nothing to push.")

    _git(["fetch", "origin", "main"], repo_root)
    main_sha = _git(["rev-parse", "origin/main"], repo_root)
    main_tree = _git(["rev-parse", f"{main_sha}^{{tree}}"], repo_root)

    index_handle, index_name = tempfile.mkstemp(prefix="ca-index-")
    os.close(index_handle)
    index_path = Path(index_name)
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    try:
        _git(["read-tree", main_sha], repo_root, env=env)
        _git(["add", "--", "data.enc.json"], repo_root, env=env)
        new_tree = _git(["write-tree"], repo_root, env=env)
        if new_tree == main_tree:
            print("data.enc.json already matches main. Nothing to push.")
            return
        changed = _git(
            ["diff-tree", "--name-only", "-r", main_tree, new_tree],
            repo_root,
        )
        names = [line for line in changed.splitlines() if line]
        if names != ["data.enc.json"]:
            raise PublishError("Refusing to push because the commit would change more than data.enc.json.")
        new_commit = _git(
            ["commit-tree", new_tree, "-p", main_sha, "-m", "Update encrypted approvals data"],
            repo_root,
        )
        _git(["push", "origin", f"{new_commit}:main"], repo_root)
        print("Pushed data.enc.json to main.")
    finally:
        index_path.unlink(missing_ok=True)


def _repo_root():
    try:
        root = _git(["rev-parse", "--show-toplevel"], Path.cwd())
    except PublishError as exc:
        raise PublishError("This directory is not inside a git repository.") from exc
    return Path(root)


def _git(args, cwd, env=None):
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = scrub(((proc.stderr or "") + "\n" + (proc.stdout or "")).strip())
        raise PublishError(f"git {args[0]} failed: {detail}")
    return (proc.stdout or "").strip()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublishError as exc:
        print(f"error: {scrub(str(exc))}", file=sys.stderr)
        raise SystemExit(1)
