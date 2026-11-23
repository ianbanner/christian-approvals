import { decryptPayload } from "./crypto.js";
import { buildDecisionRecord, decisionFileText, decisionPath, formatDecisionTime, noteForDecision } from "./decision.js";

const STORAGE_KEY = "christianApprovals.passcode";
const SECTIONS = [
  {
    id: "long_form",
    title: "Long-form writing",
    blurb: "Essays, articles, and other long drafts.",
  },
  {
    id: "short_form",
    title: "Short form",
    blurb: "Substack Notes, Facebook, LinkedIn.",
  },
  {
    id: "audiences",
    title: "Building audiences",
    blurb: "DMs, replies, comments.",
  },
];

const app = document.querySelector("#app");
const topActions = document.querySelector("#top-actions");
let session = null;
let lastError = "";

async function boot() {
  try {
    const saved = readSavedPasscode();
    if (!saved) {
      showGate("");
      return;
    }
    showBusy("Unlocking with the passcode saved on this device.");
    const ok = await unlock(saved);
    if (!ok) {
      writeSavedPasscode("");
      showGate("The saved passcode did not decrypt the data. Enter it again.");
    }
  } catch (error) {
    showGate("The dashboard could not be opened.");
  }
}

function showGate(message) {
  session = null;
  topActions.replaceChildren();
  const saved = readSavedPasscode();
  const form = el("form", { class: "gate", id: "gate" });
  form.append(
    el("h2", {}, ["Unlock"]),
    el("p", { class: "lede" }, ["Enter the passcode to decrypt the queue on this device."])
  );
  if (saved) {
    form.append(el("p", { class: "hint" }, ["A passcode is saved on this device. Leave the box blank to use it."]));
  }
  const password = el("input", {
    id: "passcode",
    type: "password",
    autocomplete: "off",
    autocapitalize: "off",
    autocorrect: "off",
    spellcheck: "false",
    required: saved ? null : true,
  });
  const remember = el("input", { id: "remember", type: "checkbox" });
  remember.checked = Boolean(saved);
  const error = el("p", { class: "error", role: "alert", hidden: message ? null : true }, [message || ""]);
  const button = el("button", { class: "primary", type: "submit" }, ["Unlock"]);
  const forget = el("button", { class: "ghost", type: "button" }, ["Forget saved passcode"]);
  forget.hidden = !saved;
  form.append(
    el("label", { for: "passcode" }, ["Passcode"]),
    password,
    el("label", { class: "remember", for: "remember" }, [remember, "Remember on this device"]),
    button,
    forget,
    error
  );
  forget.addEventListener("click", () => {
    writeSavedPasscode("");
    showGate("Saved passcode removed from this device.");
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const typed = password.value;
    const passcode = typed || readSavedPasscode();
    if (!passcode) {
      showError(error, "Enter the passcode.");
      return;
    }
    button.disabled = true;
    button.textContent = "Unlocking...";
    await waitForPaint();
    const ok = await unlock(passcode);
    if (!ok) {
      button.disabled = false;
      button.textContent = "Unlock";
      showError(error, sessionError());
      return;
    }
    if (remember.checked) {
      if (!writeSavedPasscode(passcode)) {
        appendNote(app, "This browser did not store the passcode. It will be asked for next time.");
      }
    } else {
      writeSavedPasscode("");
    }
  });
  app.replaceChildren(form);
  password.focus();
}

function sessionError() {
  return lastError || "The dashboard could not be unlocked.";
}

async function unlock(passcode) {
  lastError = "";
  try {
    const response = await fetch(new URL("data.enc.json", import.meta.url), {
      cache: "no-store",
      signal: requestSignal(),
    });
    if (!response.ok) {
      throw new Error("The encrypted data file could not be loaded.");
    }
    const encrypted = await response.json();
    const payload = assertPayload(await decryptPayload(encrypted, passcode));
    const decisions = await loadDecisions(payload.ticks_token, payload.ticks_repo);
    session = { payload, decisions };
    renderDashboard();
    return true;
  } catch (error) {
    lastError = safeMessage(error, passcode);
    session = null;
    return false;
  }
}

function renderDashboard() {
  const { payload, decisions } = session;
  const lock = el("button", { class: "lock", type: "button" }, ["Lock"]);
  lock.addEventListener("click", () => showGate(""));
  topActions.replaceChildren(lock);

  const now = Date.now();
  const items = Array.isArray(payload.items) ? payload.items.filter((item) => item && typeof item === "object") : [];
  const activeCount = items.filter((item) => !isExpired(item, now)).length;
  const prepared = payload.generated_at ? `Prepared ${payload.generated_at}. ` : "";
  const root = el("div", { class: "dashboard" });
  root.append(el("p", { class: "prepared" }, [`${prepared}${activeCount} waiting.`]));
  if (decisions.warning) {
    root.append(el("p", { class: "banner", role: "alert" }, [decisions.warning]));
  }

  const known = new Set(SECTIONS.map((section) => section.id));
  for (const section of SECTIONS) {
    root.append(renderSection(section, items.filter((item) => item.section === section.id), now));
  }
  const other = items.filter((item) => !known.has(item.section));
  if (other.length) {
    root.append(renderSection({
      id: "other",
      title: "Other",
      blurb: "Items whose section was not recognised.",
    }, other, now));
  }
  root.append(el("p", { class: "footnote" }, [
    "Decisions are written to the private ticks repo. Nothing is posted to Substack, Facebook, LinkedIn, or anywhere else.",
  ]));
  app.replaceChildren(root);
}

function renderSection(section, items, now) {
  const active = items.filter((item) => !isExpired(item, now)).sort(compareDeadline);
  const expired = items.filter((item) => isExpired(item, now)).sort(compareDeadline);
  const block = el("section", { class: "section", id: `section-${section.id}` });
  block.append(
    el("header", { class: "section-head" }, [
      el("h2", {}, [section.title]),
      el("p", {}, [section.blurb]),
    ])
  );
  if (!active.length && !expired.length) {
    block.append(el("p", { class: "empty" }, ["Nothing waiting in this section."]));
    return block;
  }
  const list = el("div", { class: "cards" });
  for (const item of active) list.append(renderCard(item));
  block.append(list);
  if (expired.length) {
    const details = el("details", { class: "expired" });
    details.append(el("summary", {}, [`Expired (${expired.length})`]));
    const expiredList = el("div", { class: "cards" });
    for (const item of expired) expiredList.append(renderCard(item));
    details.append(expiredList);
    block.append(details);
  }
  return block;
}

function safeImageSrc(value) {
  if (typeof value !== "string") return "";
  if (value.length > 1800000) return "";
  if (!/^data:image\/(jpeg|jpg|png|webp);base64,[A-Za-z0-9+/=\s]+$/.test(value)) return "";
  return value;
}

function renderFigure(image, role) {
  const src = safeImageSrc(image && image.src);
  if (!src) return null;
  const caption = text(image && image.caption);
  const figure = el("figure", { class: `draft-figure ${role || "inline"}` });
  figure.append(
    el("img", {
      src,
      alt: caption || "Article illustration",
      loading: "lazy",
    })
  );
  if (caption) figure.append(el("figcaption", {}, [caption]));
  return figure;
}

function renderDraft(item) {
  const wrap = el("div", { class: "draft" });
  const images = Array.isArray(item.images) ? item.images.filter((image) => image && typeof image === "object") : [];
  const header = images.find((image) => image.role === "header");
  const inlines = images.filter((image) => image.role !== "header");
  const headerNode = header ? renderFigure(header, "header") : null;
  if (headerNode) wrap.append(headerNode);

  const draft = text(item.draft);
  if (!draft && !inlines.length) {
    wrap.append(el("div", { class: "draft-text" }, ["No draft text."]));
    return wrap;
  }
  if (!draft || !inlines.length) {
    if (draft) wrap.append(el("div", { class: "draft-text" }, [draft]));
    for (const image of inlines) {
      const node = renderFigure(image, "inline");
      if (node) wrap.append(node);
    }
    return wrap;
  }

  const placements = inlines.map((image, index) => {
    const after = text(image.after);
    const found = after ? draft.indexOf(after) : -1;
    const end = found === -1 ? Number.POSITIVE_INFINITY : found + after.length;
    return { image, index, end };
  });
  placements.sort((left, right) => left.end - right.end || left.index - right.index);

  let cursor = 0;
  const placed = new Set();
  for (const place of placements) {
    if (!Number.isFinite(place.end)) continue;
    let insertAt = place.end;
    const newline = draft.indexOf("\n", insertAt);
    const paragraph = draft.indexOf("\n\n", insertAt);
    if (paragraph !== -1) insertAt = paragraph;
    else if (newline !== -1) insertAt = newline;
    if (insertAt > cursor) {
      wrap.append(el("div", { class: "draft-text" }, [draft.slice(cursor, insertAt).replace(/^\n+/, "").replace(/\n+$/, "")]));
    } else if (insertAt === cursor && cursor === 0) {
      // Image sits at the very start of a following section; no preceding text.
    }
    const node = renderFigure(place.image, "inline");
    if (node) wrap.append(node);
    placed.add(place.index);
    cursor = insertAt;
    while (draft[cursor] === "\n") cursor += 1;
  }
  if (cursor < draft.length) {
    const rest = draft.slice(cursor).replace(/^\n+/, "");
    if (rest) wrap.append(el("div", { class: "draft-text" }, [rest]));
  }
  for (const place of placements) {
    if (placed.has(place.index)) continue;
    const node = renderFigure(place.image, "inline");
    if (node) wrap.append(node);
  }
  return wrap;
}

function renderLinks(item) {
  const row = el("p", { class: "original" });
  const visuals = safeUrl(item.visuals_url);
  const doc = safeUrl(item.doc_url);
  const original = safeUrl(item.url);
  const links = [];
  if (doc || visuals) {
    const docHref = doc || original;
    if (docHref) links.push(el("a", { href: docHref, target: "_blank", rel: "noopener noreferrer" }, ["Open the Google Doc"]));
    if (visuals) links.push(el("a", { href: visuals, target: "_blank", rel: "noopener noreferrer" }, ["Open the Drive visuals"]));
  } else if (original) {
    links.push(el("a", { href: original, target: "_blank", rel: "noopener noreferrer" }, ["Open original"]));
  }
  if (!links.length) {
    row.append("No original link.");
    return row;
  }
  links.forEach((link, index) => {
    if (index) row.append(" ");
    row.append(link);
  });
  return row;
}

function renderCard(item) {
  const saved = session.decisions.byId.get(item.id) || null;
  const card = el("article", { class: "card" });
  if (saved) card.dataset.decision = saved.decision;
  if (item.id) card.id = `item-${cssId(item.id)}`;

  const deadline = el("p", { class: "deadline" }, [item.deadline_label ? String(item.deadline_label) : "No deadline"]);
  const heading = el("div", { class: "card-top" }, [
    el("p", { class: "meta" }, [
      el("span", { class: "platform" }, [text(item.platform) || "Platform"]),
      el("span", { class: "kind" }, [text(item.kind) || "Item"]),
    ]),
    deadline,
  ]);

  const confirmed = item.read_in_full === true;
  const flags = el("ul", { class: "flags" });
  const flagList = Array.isArray(item.flags) ? item.flags.filter((flag) => typeof flag === "string" && flag) : [];
  if (!flagList.length) {
    flags.append(el("li", { class: "flag quiet" }, ["No flags"]));
  } else {
    for (const flag of flagList) flags.append(el("li", { class: "flag" }, [flag]));
  }

  const noteId = `note-${cssId(item.id || "item")}`;
  const changeId = `change-${cssId(item.id || "item")}`;
  const noteBox = el("textarea", { id: noteId, name: "note" });
  const changeBox = el("textarea", { id: changeId, name: "change" });
  const changePanel = el("div", { class: "change-panel", hidden: true });
  const saveChange = el("button", { class: "primary", type: "button" }, ["Save change"]);
  changePanel.append(
    el("label", { for: changeId }, ["Change notes"]),
    el("p", { class: "hint" }, ["Describe the change. This is saved with the decision and is not published."]),
    changeBox,
    saveChange
  );

  const status = el("div", { class: "save-status", role: "status", "aria-live": "polite", hidden: saved ? null : true });
  if (saved) fillSaved(status, saved);

  let idOk = true;
  try {
    decisionPath(String(item.id || ""));
  } catch (error) {
    idOk = false;
  }

  const approve = el("button", { class: "approve", type: "button" }, ["Approve"]);
  const reject = el("button", { class: "reject", type: "button" }, ["Reject"]);
  const change = el("button", { class: "change", type: "button" }, ["Change"]);
  const buttons = [approve, reject, change, saveChange];
  if (!idOk || !session.payload.ticks_token) {
    for (const button of buttons) button.disabled = true;
  }

  approve.addEventListener("click", () => submitCard(item, "approve", noteBox, changeBox, status, card, buttons));
  reject.addEventListener("click", () => submitCard(item, "reject", noteBox, changeBox, status, card, buttons));
  change.addEventListener("click", () => {
    changePanel.hidden = !changePanel.hidden;
    if (!changePanel.hidden) changeBox.focus();
  });
  saveChange.addEventListener("click", () => submitCard(item, "change", noteBox, changeBox, status, card, buttons));

  const titleNodes = [];
  if (text(item.title)) titleNodes.push(el("h2", { class: "item-title" }, [text(item.title)]));
  if (text(item.subtitle)) titleNodes.push(el("p", { class: "item-subtitle" }, [text(item.subtitle)]));

  card.append(
    heading,
    el("p", { class: "author" }, [text(item.author) || "Unknown author"]),
    ...titleNodes,
    el("p", { class: "meta-line" }, [metaLine(item)]),
    el("p", { class: "item-id" }, [`Id: ${text(item.id) || "missing"}`]),
    el("h3", {}, ["Summary"]),
    el("p", { class: "summary" }, [text(item.summary) || "No summary."]),
    el("p", { class: confirmed ? "confirm yes" : "confirm no" }, [
      confirmed ? "Read in full: confirmed" : "Read in full: not confirmed",
    ]),
    el("h3", {}, ["Flags"]),
    flags,
    el("h3", {}, ["Draft"]),
    renderDraft(item),
    renderLinks(item),
    el("div", { class: "field" }, [
      el("label", { for: noteId }, ["Optional note"]),
      noteBox,
    ]),
    el("div", { class: "actions" }, [approve, reject, change]),
    changePanel,
    status
  );
  if (!idOk) {
    status.hidden = false;
    status.className = "save-status error";
    status.replaceChildren(el("p", { class: "label" }, ["This item id cannot be saved as a decision file."]));
  } else if (!session.payload.ticks_token) {
    status.hidden = false;
    status.className = "save-status error";
    status.replaceChildren(el("p", { class: "label" }, ["No ticks token is available in this data file, so decisions cannot be saved."]));
  }
  return card;
}

async function submitCard(item, decision, noteBox, changeBox, status, card, buttons) {
  let note = "";
  try {
    note = noteForDecision(decision, changeBox.value, noteBox.value);
  } catch (error) {
    showStatusError(status, safeMessage(error, session.payload.ticks_token));
    return;
  }
  const decidedAt = new Date().toISOString();
  let record;
  try {
    record = buildDecisionRecord({
      id: String(item.id),
      decision,
      note,
      decidedAt,
    });
  } catch (error) {
    showStatusError(status, safeMessage(error, session.payload.ticks_token));
    return;
  }

  for (const button of buttons) button.disabled = true;
  status.hidden = false;
  status.className = "save-status";
  status.replaceChildren(el("p", { class: "label" }, ["Saving..."]));
  try {
    const result = await putDecision(session.payload.ticks_token, session.payload.ticks_repo, record);
    record.sha = result && result.content && result.content.sha ? result.content.sha : "";
    session.decisions.byId.set(record.id, record);
    card.dataset.decision = record.decision;
    fillSaved(status, record);
  } catch (error) {
    showStatusError(status, `Could not save this decision. ${safeMessage(error, session.payload.ticks_token)}`);
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

function fillSaved(status, record) {
  status.hidden = false;
  status.className = `save-status ${record.decision}`;
  const label = decisionLabel(record.decision);
  const when = formatDecisionTime(record.decided_at);
  const line = el("p", {});
  line.append(el("span", { class: "label" }, [`Saved: ${label}`]));
  if (when) line.append(`, ${when}`);
  const children = [line];
  if (record.note) children.push(el("p", {}, [record.note]));
  status.replaceChildren(...children);
}

function showStatusError(status, message) {
  status.hidden = false;
  status.className = "save-status error";
  status.replaceChildren(el("p", { class: "label" }, [message]));
}

async function loadDecisions(token, ticksRepo) {
  const empty = new Map();
  if (!token) {
    return { byId: empty, warning: "No ticks token is available in this data file, so saved decisions were not loaded." };
  }
  try {
    await github(token, repoPath(ticksRepo), { method: "GET" });
  } catch (error) {
    return { byId: empty, warning: `Could not load saved decisions. ${safeMessage(error, token)}` };
  }
  let listing;
  try {
    listing = await github(token, contentsPath(ticksRepo, "decisions"), { method: "GET" });
  } catch (error) {
    if (error.status === 404) return { byId: empty, warning: "" };
    return { byId: empty, warning: `Could not load saved decisions. ${safeMessage(error, token)}` };
  }
  if (!Array.isArray(listing)) {
    return { byId: empty, warning: "Could not load saved decisions. decisions/ is not a directory." };
  }
  const files = listing.filter((entry) => entry && entry.type === "file" && String(entry.name || "").endsWith(".json"));
  const byId = new Map();
  let skipped = 0;
  await mapPool(files, 6, async (entry) => {
    try {
      const path = entry.path || `decisions/${entry.name}`;
      const document = await github(token, contentsPath(ticksRepo, path), { method: "GET" });
      const parsed = JSON.parse(base64ToUtf8(document.content || ""));
      const record = buildDecisionRecord({
        id: parsed.id,
        decision: parsed.decision,
        note: parsed.note,
        decidedAt: parsed.decided_at,
      });
      record.sha = document.sha || "";
      byId.set(record.id, record);
    } catch (error) {
      skipped += 1;
    }
  });
  const warning = skipped ? `Some saved decisions could not be read (${skipped}).` : "";
  return { byId, warning };
}

const SHA_MISMATCH_RETRIES = 3;

async function putDecision(token, ticksRepo, record) {
  const path = contentsPath(ticksRepo, decisionPath(record.id));
  const content = utf8ToBase64(decisionFileText(record));
  let lastError = null;
  for (let attempt = 0; attempt <= SHA_MISMATCH_RETRIES; attempt += 1) {
    const sha = await currentDecisionSha(token, path);
    const body = {
      message: `Record decision ${record.id}`,
      content,
    };
    if (sha) body.sha = sha;
    try {
      return await github(token, path, { method: "PUT", body });
    } catch (error) {
      lastError = error;
      const mismatch = error.status === 409 || error.status === 422;
      if (!mismatch || attempt === SHA_MISMATCH_RETRIES) throw error;
    }
  }
  throw lastError;
}

async function currentDecisionSha(token, path) {
  try {
    const current = await github(token, path, { method: "GET" });
    return current && typeof current.sha === "string" ? current.sha : "";
  } catch (error) {
    if (error.status === 404) return "";
    throw error;
  }
}

async function github(token, path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`https://api.github.com${path}`, {
      method,
      cache: "no-store",
      signal: requestSignal(),
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    const failure = new Error("The browser could not reach GitHub.");
    failure.status = 0;
    throw failure;
  }
  const text = await response.text();
  let parsed = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      parsed = null;
    }
  }
  if (!response.ok) {
    const message = parsed && typeof parsed.message === "string" ? parsed.message : `HTTP ${response.status}`;
    const failure = new Error(`GitHub returned ${response.status}: ${message}`);
    failure.status = response.status;
    throw failure;
  }
  return parsed;
}

function assertPayload(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("Decrypted data was not an object.");
  }
  if (typeof payload.ticks_repo !== "string" || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(payload.ticks_repo)) {
    throw new Error("Decrypted data is missing ticks_repo.");
  }
  if (typeof payload.ticks_token !== "string") {
    throw new Error("Decrypted data is missing ticks_token.");
  }
  if (!Array.isArray(payload.items)) {
    throw new Error("Decrypted data is missing items.");
  }
  return payload;
}

function repoPath(ticksRepo) {
  const { owner, repo } = repoParts(ticksRepo);
  return `/repos/${owner}/${repo}`;
}

function contentsPath(ticksRepo, filePath) {
  const { owner, repo } = repoParts(ticksRepo);
  const encoded = String(filePath).split("/").map((part) => encodeURIComponent(part)).join("/");
  return `/repos/${owner}/${repo}/contents/${encoded}`;
}

function repoParts(ticksRepo) {
  const match = /^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/.exec(ticksRepo);
  if (!match) throw new Error("ticks_repo is not an owner and name.");
  return { owner: match[1], repo: match[2] };
}

function compareDeadline(a, b) {
  const left = deadlineTime(a);
  const right = deadlineTime(b);
  if (left !== right) return left - right;
  return String(a.id || "").localeCompare(String(b.id || ""));
}

function deadlineTime(item) {
  if (!item.deadline_iso) return Number.POSITIVE_INFINITY;
  const time = Date.parse(item.deadline_iso);
  return Number.isNaN(time) ? Number.POSITIVE_INFINITY : time;
}

function isExpired(item, now) {
  if (!item.deadline_iso) return false;
  const time = Date.parse(item.deadline_iso);
  return !Number.isNaN(time) && time < now;
}

function metaLine(item) {
  const parts = [];
  if (item.status) parts.push(String(item.status));
  if (item.source_bot) parts.push(`Source: ${item.source_bot}`);
  return parts.join(", ") || "No status";
}

function decisionLabel(decision) {
  if (decision === "approve") return "Approve";
  if (decision === "reject") return "Reject";
  if (decision === "change") return "Change";
  return decision;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value));
    if (url.protocol === "https:" || url.protocol === "http:") return url.href;
  } catch (error) {
    return "";
  }
  return "";
}

function text(value) {
  return typeof value === "string" ? value : "";
}

function cssId(value) {
  return String(value).replace(/[^A-Za-z0-9_-]/g, "-");
}

function safeMessage(error, secret) {
  let message = error && error.message ? String(error.message) : "Something went wrong.";
  if (secret && message.includes(secret)) message = message.split(secret).join("[redacted]");
  return message;
}

function readSavedPasscode() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "";
  } catch (error) {
    return "";
  }
}

function writeSavedPasscode(value) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, value);
    else localStorage.removeItem(STORAGE_KEY);
    return true;
  } catch (error) {
    return false;
  }
}

function showBusy(message) {
  topActions.replaceChildren();
  app.replaceChildren(el("p", { class: "prepared" }, [message]));
}

function showError(node, message) {
  node.hidden = !message;
  node.textContent = message || "";
}

function appendNote(parent, message) {
  parent.append(el("p", { class: "hint" }, [message]));
}

function utf8ToBase64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

function base64ToUtf8(value) {
  const binary = atob(String(value).replace(/\s/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new TextDecoder().decode(bytes);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "hidden" && value === true) node.hidden = true;
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function mapPool(items, limit, task) {
  if (!items.length) return;
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      await task(items[index], index);
    }
  });
  await Promise.all(workers);
}

function requestSignal() {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(20000);
  }
  return undefined;
}

function waitForPaint() {
  return new Promise((resolve) => {
    setTimeout(resolve, 30);
  });
}

boot();
