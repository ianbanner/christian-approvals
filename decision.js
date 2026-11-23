/**
 * Decision records saved to decisions/<id>.json in the ticks repo.
 * The object has exactly: id, decision, note, decided_at.
 * tools/decision_format.py checks the same shape.
 */

export const DECISIONS = ["approve", "reject", "change"];

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

export function buildDecisionRecord({ id, decision, note, decidedAt }) {
  if (typeof id !== "string" || !ID_RE.test(id)) {
    throw new Error("id must be a safe file name token.");
  }
  if (!DECISIONS.includes(decision)) {
    throw new Error("decision must be approve, reject, or change.");
  }
  if (typeof note !== "string") {
    throw new Error("note must be a string.");
  }
  if (typeof decidedAt !== "string" || !ISO_RE.test(decidedAt)) {
    throw new Error("decided_at must be a UTC ISO-8601 timestamp.");
  }
  return {
    id,
    decision,
    note,
    decided_at: decidedAt,
  };
}

export function decisionPath(id) {
  const record = buildDecisionRecord({
    id,
    decision: "approve",
    note: "",
    decidedAt: "2020-01-01T00:00:00Z",
  });
  return `decisions/${record.id}.json`;
}

export function noteForDecision(decision, changeNotes, optionalNote) {
  const change = typeof changeNotes === "string" ? changeNotes.trim() : "";
  const extra = typeof optionalNote === "string" ? optionalNote.trim() : "";
  if (decision === "change") {
    if (!change) {
      throw new Error("Add change notes before saving.");
    }
    return extra ? `${change}\n\n${extra}` : change;
  }
  if (decision === "approve" || decision === "reject") {
    return extra;
  }
  throw new Error("decision must be approve, reject, or change.");
}

export function decisionFileText(record) {
  return `${JSON.stringify(record, null, 2)}\n`;
}

export function formatDecisionTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    hour12: false,
    weekday: "short",
    day: "numeric",
    month: "short",
  }).formatToParts(date);
  const value = (type) => {
    const found = parts.find((part) => part.type === type);
    return found ? found.value : "";
  };
  return `${value("hour")}:${value("minute")} ${value("weekday")} ${value("day")} ${value("month")}`;
}
