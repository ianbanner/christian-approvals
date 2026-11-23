"""Prove publish_data.py output decrypts with the browser WebCrypto steps."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from crypto_box import MAX_ITERATIONS, MIN_ITERATIONS, CryptoError, decrypt_payload, encrypt_payload  # noqa: E402
from redact import scrub  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data.enc.json"


class RoundTripTest(unittest.TestCase):
    def test_publish_output_decrypts_with_browser_module(self):
        items = [
            sample_item("sample-long-1", "long_form", draft="A café reply. UNIQUE_SUMMARY_MARKER"),
        ]
        token = "roundtrip-token-marker"
        passcode = "roundtrip-passcode-marker"
        with self.subTest("cli"):
            out, stdout, stderr = run_publish(items, passcode, token)
            combined = stdout + stderr
            self.assertNotIn(token, combined)
            self.assertNotIn(passcode, combined)
            self.assertNotIn("UNIQUE_SUMMARY_MARKER", combined)
            document = json.loads(out.read_text(encoding="utf-8"))
            self.assertGreaterEqual(document["iterations"], MIN_ITERATIONS)
            self.assertLessEqual(document["iterations"], MAX_ITERATIONS)
            self.assertEqual(document["kdf"], "PBKDF2-SHA256")
            self.assertEqual(document["version"], 1)
            self.assertNotIn(token.encode(), out.read_bytes())
            self.assertNotIn(passcode.encode(), out.read_bytes())

            payload = decrypt_payload(document, passcode)
            browser = decrypt_with_page(out, passcode)
            self.assertEqual(browser, payload)
            self.assertEqual(payload["ticks_repo"], "ianbanner/christian-approvals-ticks")
            self.assertEqual(payload["ticks_token"], token)
            self.assertEqual(payload["items"][0]["draft"], items[0]["draft"])
            self.assertTrue(payload["generated_at"].endswith("Z"))

        with self.assertRaises(CryptoError):
            decrypt_payload(document, "wrong-passcode")
        with self.assertRaises(AssertionError):
            decrypt_with_page(out, "wrong-passcode")

        weakened = dict(document)
        weakened["iterations"] = 1000
        with self.assertRaises(CryptoError) as caught:
            decrypt_payload(weakened, passcode)
        self.assertIn("too low", str(caught.exception).lower())

    def test_two_encryptions_use_fresh_salt(self):
        payload = {"items": []}
        first = encrypt_payload(payload, "example-only")
        second = encrypt_payload(payload, "example-only")
        self.assertNotEqual(first["salt"], second["salt"])
        self.assertNotEqual(first["iv"], second["iv"])
        self.assertNotEqual(first["ciphertext"], second["ciphertext"])
        self.assertEqual(decrypt_payload(first, "example-only"), payload)

    def test_publish_hides_missing_secret_names_only(self):
        env = os.environ.copy()
        env.pop("CA_TICKS_TOKEN", None)
        env["CA_PASSCODE"] = "only-a-passcode"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "publish_data.py"), str(ROOT / "does-not-matter.json")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("CA_TICKS_TOKEN", proc.stderr)
        self.assertNotIn("only-a-passcode", proc.stderr)

    def test_publish_does_not_echo_plaintext_on_validation_error(self):
        items_path = write_items([{"id": "sample-long-1", "draft": "SECRET_DRAFT_MARKER"}])
        proc = run_publish_raw(items_path, "passcode", "token-marker")
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotIn("SECRET_DRAFT_MARKER", proc.stdout + proc.stderr)
        self.assertIn("missing", proc.stderr.lower())

    def test_push_refuses_any_file_other_than_root_data_enc(self):
        items_path = write_items([sample_item("sample-long-1", "long_form")])
        out = items_path.parent / "other.enc.json"
        proc = run_publish_raw(items_path, "passcode", "token-marker", output=out, push=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("only publishes data.enc.json", proc.stderr)
        self.assertTrue(out.is_file())

    def test_items_json_is_gitignored(self):
        proc = subprocess.run(
            ["git", "check-ignore", "items.json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_committed_sample_is_placeholder_only(self):
        self.assertTrue(SAMPLE.is_file(), "data.enc.json sample is missing")
        raw = SAMPLE.read_text(encoding="utf-8")
        self.assertNotIn("example-only-not-a-real-token", raw)
        self.assertNotIn("example-only", raw)
        payload = decrypt_with_page(SAMPLE, "example-only")
        python_payload = decrypt_payload(json.loads(raw), "example-only")
        self.assertEqual(payload, python_payload)
        token = payload["ticks_token"]
        self.assertIn("example-only", token)
        self.assertIn("not-a-real", token)
        self.assertNotIn("ghp_", token)
        self.assertNotIn("github_pat_", token)
        self.assertEqual(payload["ticks_repo"], "ianbanner/christian-approvals-ticks")
        sections = {item["section"] for item in payload["items"]}
        self.assertEqual(sections, {"long_form", "short_form", "audiences"})
        for item in payload["items"]:
            self.assertTrue(item["url"].startswith("https://example.com/"))
            self.assertNotIn("ghp_", json.dumps(item))
        expired = [item for item in payload["items"] if item["deadline_iso"].startswith("2020-")]
        self.assertTrue(expired)

    def test_ui_copy_avoids_em_dash_and_banned_styling(self):
        import re

        for name in ("index.html", "app.js", "styles.css", "decision.js", "crypto.js"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("\u2014", text, name)
            self.assertNotIn("\u2013", text, name)
            self.assertIsNone(re.search(r"\bInter\b", text), name)
            self.assertIsNone(re.search(r"indigo", text, re.IGNORECASE), name)

    def test_scrub_removes_credentials_from_errors(self):
        previous_token = os.environ.get("CA_TICKS_TOKEN")
        previous_pass = os.environ.get("CA_PASSCODE")
        token = "ticks-token-value"
        passcode = "passcode-value"
        embedded = "ghp_" + ("b" * 36)
        os.environ["CA_TICKS_TOKEN"] = token
        os.environ["CA_PASSCODE"] = passcode
        try:
            cleaned = scrub(f"https://x-access-token:{embedded}@github.com/ianbanner/x {token} {passcode}")
        finally:
            restore_env("CA_TICKS_TOKEN", previous_token)
            restore_env("CA_PASSCODE", previous_pass)
        self.assertNotIn(token, cleaned)
        self.assertNotIn(passcode, cleaned)
        self.assertNotIn(embedded, cleaned)
        self.assertNotIn("x-access-token:ghp_", cleaned)


def sample_item(item_id, section, draft="Placeholder draft."):
    return {
        "id": item_id,
        "section": section,
        "platform": "Example",
        "kind": "Note",
        "author": "Sample Author",
        "url": "https://example.com/item",
        "summary": "Placeholder summary.",
        "read_in_full": True,
        "draft": draft,
        "flags": ["tone"],
        "deadline_iso": "2026-12-01T17:00:00Z",
        "deadline_label": "1 Dec",
        "status": "needs review",
        "source_bot": "sample-bot",
    }


def write_items(items):
    import tempfile

    directory = Path(tempfile.mkdtemp(prefix="ca-items-"))
    path = directory / "items.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def run_publish(items, passcode, token):
    path = write_items(items)
    out = path.parent / "data.enc.json"
    proc = run_publish_raw(path, passcode, token, output=out)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return out, proc.stdout, proc.stderr


def run_publish_raw(items_path, passcode, token, output=None, push=False):
    env = os.environ.copy()
    env["CA_PASSCODE"] = passcode
    env["CA_TICKS_TOKEN"] = token
    command = [sys.executable, str(ROOT / "tools" / "publish_data.py"), str(items_path)]
    if output is not None:
        command.extend(["--output", str(output)])
    if push:
        command.append("--push")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def decrypt_with_page(path, passcode):
    script = r"""
import { readFile } from "node:fs/promises";
import { decryptPayload } from "./crypto.js";
const file = JSON.parse(await readFile(process.argv[1], "utf8"));
try {
  const payload = await decryptPayload(file, process.argv[2]);
  process.stdout.write(JSON.stringify(payload));
} catch (error) {
  process.stderr.write(error.message || String(error));
  process.exit(1);
}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(path), passcode],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def restore_env(key, value):
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
