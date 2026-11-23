"""Unit tests for the decision file written by the dashboard."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from decision_format import (
    DecisionFormatError,
    build_decision_record,
    decision_relpath,
    parse_decision_record,
)

ROOT = Path(__file__).resolve().parents[1]


class DecisionFormatTest(unittest.TestCase):
    def test_record_has_exact_fields(self):
        record = build_decision_record(
            "sample-long-1",
            "approve",
            "Ship it.",
            "2026-11-23T19:04:00Z",
        )
        self.assertEqual(list(record.keys()), ["id", "decision", "note", "decided_at"])
        self.assertEqual(
            record,
            {
                "id": "sample-long-1",
                "decision": "approve",
                "note": "Ship it.",
                "decided_at": "2026-11-23T19:04:00Z",
            },
        )
        parsed = parse_decision_record(json.loads(json.dumps(record)))
        self.assertEqual(parsed, record)

    def test_accepts_each_decision_and_fractional_timestamp(self):
        for decision, stamp in (
            ("approve", "2026-11-23T19:04:00Z"),
            ("reject", "2026-11-23T19:04:00.123Z"),
            ("change", "2026-11-23T19:04:00.123456Z"),
        ):
            record = build_decision_record("sample-short-2", decision, "", stamp)
            self.assertEqual(record["decision"], decision)
            self.assertEqual(parse_decision_record(record)["decided_at"], stamp)

    def test_rejects_unknown_decision_and_bad_timestamp(self):
        with self.assertRaises(DecisionFormatError):
            build_decision_record("sample-long-1", "publish", "", "2026-11-23T19:04:00Z")
        with self.assertRaises(DecisionFormatError):
            build_decision_record("sample-long-1", "reject", "", "yesterday")
        with self.assertRaises(DecisionFormatError):
            build_decision_record("sample-long-1", "reject", None, "2026-11-23T19:04:00Z")

    def test_rejects_extra_fields_and_path_ids(self):
        record = build_decision_record("sample-long-1", "approve", "", "2026-11-23T19:04:00Z")
        record["sha"] = "abc"
        with self.assertRaises(DecisionFormatError):
            parse_decision_record(record)
        with self.assertRaises(DecisionFormatError):
            decision_relpath("../evil")
        self.assertEqual(decision_relpath("sample-long-1"), "decisions/sample-long-1.json")

    def test_browser_module_matches_python_format(self):
        cases = [
            ("sample-long-1", "approve", "", "2026-11-23T19:04:00Z"),
            ("sample-short-2", "reject", "Not this one.", "2026-11-23T19:04:00.123Z"),
            ("sample-audience-1", "change", "Tighten the opening.", "2026-11-23T19:04:00.123456Z"),
        ]
        for item_id, decision, note, decided_at in cases:
            expected = build_decision_record(item_id, decision, note, decided_at)
            actual = node_json(
                "record",
                item_id,
                decision,
                note,
                decided_at,
            )
            self.assertEqual(actual["record"], expected)
            self.assertEqual(actual["path"], decision_relpath(item_id))
            file_text = actual["file"]
            self.assertTrue(file_text.endswith("\n"))
            self.assertEqual(json.loads(file_text), expected)

    def test_change_notes_become_the_note_field(self):
        missing = node_json("note", "change", "   ", "optional")
        self.assertFalse(missing["ok"])
        self.assertIn("change notes", missing["error"].lower())

        combined = node_json("note", "change", " Tighten the opening. ", " Mention the psalm. ")
        self.assertTrue(combined["ok"])
        self.assertEqual(combined["note"], "Tighten the opening.\n\nMention the psalm.")

        approve = node_json("note", "approve", "", "  Looks right. ")
        self.assertEqual(approve["note"], "Looks right.")

        reject = node_json("note", "reject", "ignored", "")
        self.assertEqual(reject["note"], "")

    def test_saved_time_is_london_local(self):
        winter = node_json("time", "2026-11-23T22:05:00Z")
        self.assertEqual(winter["time"], "22:05 Mon 23 Nov")
        summer = node_json("time", "2026-07-15T21:05:00Z")
        self.assertEqual(summer["time"], "22:05 Wed 15 Jul")


def node_json(mode, *args):
    script = r"""
import { buildDecisionRecord, decisionFileText, decisionPath, formatDecisionTime, noteForDecision } from "./decision.js";
const mode = process.argv[1];
if (mode === "record") {
  const [id, decision, note, decidedAt] = process.argv.slice(2);
  const record = buildDecisionRecord({ id, decision, note, decidedAt });
  process.stdout.write(JSON.stringify({
    record,
    path: decisionPath(id),
    file: decisionFileText(record),
  }));
} else if (mode === "note") {
  const [decision, changeNotes, optionalNote] = process.argv.slice(2);
  try {
    process.stdout.write(JSON.stringify({
      ok: true,
      note: noteForDecision(decision, changeNotes, optionalNote),
    }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: error.message }));
  }
} else if (mode === "time") {
  process.stdout.write(JSON.stringify({ time: formatDecisionTime(process.argv[2]) }));
} else {
  throw new Error("unknown mode");
}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script, mode, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


if __name__ == "__main__":
    unittest.main()
