"""Archive keeps moving a decision if the page updates it mid-flight."""

import base64
import io
import json
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import read_ticks
from read_ticks import TicksError, _archive_one

PAYLOAD = json.dumps(
    {
        "id": "sample-long-1",
        "decision": "approve",
        "note": "",
        "decided_at": "2026-11-23T22:05:00Z",
    }
).encode("utf-8")


class ArchiveMoveTest(unittest.TestCase):
    def test_refreshes_sha_when_the_page_updates_before_delete(self):
        source = {"sha": "sha-old", "body": b"old"}
        dest = None
        deleted = []

        def fake(token, method, path, body=None):
            nonlocal dest
            if path.endswith("/decisions/sample-long-1.json"):
                if method == "GET":
                    if source["sha"] is None:
                        raise TicksError("GitHub returned 404: Not Found")
                    return {"sha": source["sha"], "content": base64.b64encode(source["body"]).decode("ascii")}
                if method == "DELETE":
                    if body.get("sha") != source["sha"]:
                        raise TicksError(f"GitHub returned 409: is at {source['sha']} but expected {body.get('sha')}")
                    deleted.append(body["sha"])
                    source["sha"] = None
                    return {}
            if path.endswith("/archive/2026-11-23/sample-long-1.json"):
                if method == "GET":
                    if dest is None:
                        raise TicksError("GitHub returned 404: Not Found")
                    return {"sha": dest["sha"], "content": dest["content"]}
                if method == "PUT":
                    if dest is not None and body.get("sha") != dest["sha"]:
                        raise TicksError("GitHub returned 409: is at dest but expected stale")
                    dest = {"sha": "dest-" + str(len(body["content"])), "content": body["content"]}
                    if source["sha"] == "sha-old":
                        source["sha"] = "sha-new"
                        source["body"] = PAYLOAD
                    return {"content": {"sha": dest["sha"]}}
            raise AssertionError(f"unexpected {method} {path}")

        original = read_ticks.github
        read_ticks.github = fake
        try:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                _archive_one(
                    "token",
                    {"id": "sample-long-1", "path": "decisions/sample-long-1.json"},
                    "main",
                    "2026-11-23",
                )
        finally:
            read_ticks.github = original

        self.assertEqual(deleted, ["sha-new"])
        self.assertIn("Archived decisions/sample-long-1.json -> archive/2026-11-23/sample-long-1.json", stderr.getvalue())
        self.assertEqual(base64.b64decode(dest["content"]), PAYLOAD)

    def test_skips_a_file_that_was_already_moved(self):
        def fake(token, method, path, body=None):
            raise TicksError("GitHub returned 404: Not Found")

        original = read_ticks.github
        read_ticks.github = fake
        try:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                _archive_one(
                    "token",
                    {"id": "sample-long-1", "path": "decisions/sample-long-1.json"},
                    "main",
                    "2026-11-23",
                )
        finally:
            read_ticks.github = original
        self.assertIn("no longer in decisions", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
