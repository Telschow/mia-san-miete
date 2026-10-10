"use strict";
// Settings editor and first-run setup. Uses h(), api(), post(), toast(), $ from the page.
// Everything here edits local files through the dashboard's own API; nothing leaves the machine.

const clone = x => JSON.parse(JSON.stringify(x ?? null));
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
function setPath(o, p, v) {
  const ks = p.split(".");
  let a = o;
  for (let i = 0; i < ks.length - 1; i++) a = (a[ks[i]] ??= {});
  a[ks[ks.length - 1]] = v;
}
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

// ---------- one input: returns {el, get()}; get() gives the value, undefined to leave it out
function makeInput(spec, value) {
  let el, get;
  const optional = !!spec.optional;
  if (spec.type === "bool") {
    el = h("input", { type: "checkbox" }); el.checked = !!value;
    get = () => el.checked;
  } else if (spec.type === "select") {
    el = h("select", {}, spec.opts.map(o => h("option", { value: o }, o))); el.value = value ?? spec.opts[0];
    get = () => el.value;
  } else if (spec.type === "tags") {
    el = h("input", { type: "text", placeholder: spec.placeholder || "comma separated" });
    el.value = (value || []).join(", ");
    get = () => el.value.split(",").map(x => x.trim()).filter(Boolean);
  } else if (spec.type === "number") {
    el = h("input", { type: "number", min: spec.min ?? 0, step: spec.step ?? 1 });
    el.value = value ?? "";
    get = () => (el.value === "" ? (optional ? null : undefined) : Number(el.value));
  } else if (spec.type === "list") {
    return makeList(spec, value || []);
  } else {
    el = h("input", { type: spec.type === "date" ? "date" : "text", placeholder: spec.placeholder || "", autocomplete: "off" });
    el.value = value ?? "";
    get = () => (el.value === "" ? (optional ? null : undefined) : el.value);
  }
  return { el, get };
}

function makeList(spec, items) {
  const box = h("div", { class: "list" });
  const rows = [];
  const addRow = item => {
    const inputs = spec.item.map(f => ({ f, ...makeInput(f, item?.[f.p]) }));
    const row = h("div", { class: "lrow" },
      h("div", { class: "lgrid" }, inputs.map(i => h("label", { class: "lf" + (i.f.type === "bool" ? " chk" : "") }, h("span", {}, i.f.label), i.el))),
      h("button", { class: "btn small", type: "button", "aria-label": "Remove", onclick: () => { rows.splice(rows.indexOf(entry), 1); row.remove(); } }, "Remove"));
    const entry = { inputs };
    rows.push(entry);
    box.append(row);
  };
  items.forEach(addRow);
  const add = h("button", { class: "btn small", type: "button", onclick: () => addRow({}) }, "+ " + (spec.addLabel || "Add"));
  const el = h("div", {}, box, add);
  const get = () => rows.map(r => {
    const o = {};
    for (const { f, get: g } of r.inputs) { const v = g(); if (v !== undefined && v !== null && v !== "") o[f.p] = v; }
    return o;
  });
  return { el, get };
}

// ---------- a field row with label, help and an error slot
function fieldRow(spec, data) {
  const value = getPath(data[spec.scope || "config"], spec.p);
  const inp = makeInput(spec, value ?? spec.def);
  const err = h("div", { class: "ferr" });
  const wide = spec.type === "list" || spec.type === "tags" || spec.wide;
  const row = h("div", { class: "frow" + (wide ? " wide" : "") + (spec.type === "bool" ? " chk" : "") },
    h("label", {}, h("span", { class: "flabel" }, spec.label), spec.type === "list" ? null : inp.el),
    spec.type === "list" ? inp.el : null,
    spec.help ? h("div", { class: "fhelp" }, spec.help) : null, err);
  return { spec, row, get: inp.get, err, key: (spec.scope === "profile" ? "profile." : "") + spec.p };
}

// ---------- a card with Save
function card(title, desc, fields, data, opts = {}) {
  const rows = fields.map(f => fieldRow(f, data));
  const general = h("div", { class: "ferr" });
  const status = h("span", { class: "hint" });
  const save = h("button", { class: "btn primary", type: "button" }, opts.saveLabel || "Save");
  save.onclick = async () => {
    rows.forEach(r => (r.err.textContent = ""));
    general.textContent = "";
    const patch = { config: {}, profile: {} };
    for (const r of rows) {
      const v = r.get();
      if (v === undefined) continue;
      setPath(patch[r.spec.scope || "config"], r.spec.p, v);
    }
    if (opts.extraPatch) opts.extraPatch(patch);
    let confirmLive = false;
    const sp = patch.config.send_policy;
    const was = data.config.send_policy || {};
    if (sp && sp.enabled && sp.mode === "live" && !(was.enabled && was.mode === "live")) {
      if (!confirm("Switch to LIVE sending?\n\nMessages will be sent to landlords without asking, within your caps.\n\nBefore you do: shadow mode ran for a week, you read the shadow report, caps are low, quiet hours are set and the kill switch works.")) return;
      confirmLive = true;
    }
    save.disabled = true;
    try {
      await post("/api/settings", { patch, confirm_live: confirmLive });
      toast("Saved");
      status.textContent = "Saved. Applies now to this dashboard and to the next scheduled run.";
      if (opts.onSaved) await opts.onSaved();
    } catch (e) {
      let shown = false;
      for (const x of e.errors || []) {
        const r = rows.find(rr => x.path === rr.key || x.path.startsWith(rr.key + "."));
        if (r) { r.err.textContent = x.message; shown = true; }
        else general.append(h("div", {}, `${x.path}: ${x.message}`));
      }
      if (!shown && !(e.errors || []).length) general.textContent = e.message;
      toast("Not saved: fix the marked fields");
    } finally { save.disabled = false; }
  };
  return h("section", { class: "card scard" }, h("h3", {}, title), desc ? h("div", { class: "sub" }, desc) : null,
    h("div", { class: "fgrid" }, rows.map(r => r.row)), opts.extra || null, general,
    h("div", { class: "actions" }, save, status));
}

// ---------- credentials (write-only)
function secretRow(sec, refresh) {
  const input = h("input", { type: "password", autocomplete: "new-password", placeholder: sec.is_set ? "stored, hidden. Type to replace" : "not set" });
  const chip = h("span", { class: "chip" + (sec.is_set ? "" : " off") }, sec.is_set ? "✓ stored" : "not set");
  const msg = h("span", { class: "hint" });
  const saveBtn = h("button", { class: "btn small", type: "button", onclick: async () => {
    if (!input.value) { msg.textContent = "Type a value first."; return; }
    try { await post("/api/secret", { name: sec.name, value: input.value }); input.value = ""; toast("Stored locally"); await refresh(); }
    catch (e) { msg.textContent = e.message; }
  } }, "Store");
  const clearBtn = sec.is_set ? h("button", { class: "btn small", type: "button", onclick: async () => {
    if (!confirm("Remove the stored value?")) return;
    await post("/api/secret", { name: sec.name, value: "" }); await refresh();
  } }, "Remove") : null;
  return h("div", { class: "srow" }, h("label", {}, h("span", { class: "flabel" }, sec.label), h("div", { class: "sinput" }, input, saveBtn, clearBtn, chip)), msg);
}

function testButton(kind, label) {
  const out = h("span", { class: "hint" });
  const btn = h("button", { class: "btn small", type: "button", onclick: async () => {
    out.textContent = "Testing..."; btn.disabled = true;
    try { const r = await post("/api/test/" + kind, {}); out.textContent = (r.ok ? "✓ " : "✕ ") + r.message; } catch (e) { out.textContent = "✕ " + e.message; }
    btn.disabled = false;
  } }, label || "Test connection");
  return h("div", { class: "actions" }, btn, out);
}

// ---------- the settings tab
async function viewSettingsEditor(state) {
  let data;
  try { data = await api("/api/settings/full"); } catch (e) { return null; }
  const refresh = async () => { await render(); };
  const secrets = (section) => data.secrets.filter(s => s.section === section);
  const secretBox = (section) => h("div", { class: "sbox" }, secrets(section).map(s => secretRow(s, refresh)));
  const C = (p, label, type, o = {}) => ({ p, label, type: type || "text", scope: "config", ...o });
  const P = (p, label, type, o = {}) => ({ p, label, type: type || "text", scope: "profile", ...o });
  const hasInbox = k => !!data.config[k];

  const search = card("Your search", "What a flat must satisfy. Hard limits are never overridden by the score.", [
    C("city.name", "City"), C("criteria.max_warm_rent_eur", "Max warm rent (EUR)", "number", { min: 1 }),
    C("criteria.max_cold_rent_eur", "Max cold rent (EUR)", "number", { min: 1 }),
    C("criteria.min_area_m2", "Min size (m²)", "number", { min: 1 }), C("criteria.min_rooms", "Min rooms", "number", { min: 0.5, step: 0.5 }),
    C("criteria.min_lease_months", "Min lease (months)", "number"),
    C("criteria.move_in.ideal_from", "Ideal move-in", "date"), C("criteria.move_in.latest", "Latest move-in", "date"),
    C("criteria.move_in.early_flex_days", "Earlier is fine by (days)", "number"),
    C("criteria.exclude_keywords", "Words that exclude a flat", "tags", { help: "Whole words, for example WBS, Tausch." }),
  ], data, { onSaved: refresh });

  const commute = card("Places you travel to", "Each place has a weekday arrival time and a limit. Addresses stay on this computer.", [
    C("commute.targets", "Places", "list", { addLabel: "Add a place", item: [
      { p: "name", label: "Short name" }, { p: "destination", label: "Address or station" },
      { p: "arrival_time", label: "Arrive by (HH:MM)", placeholder: "09:00" },
      { p: "max_pt_minutes", label: "Max public transport (min)", type: "number", optional: true },
      { p: "max_car_minutes", label: "Max car (min)", type: "number", optional: true },
      { p: "modes", label: "If both limits", type: "select", opts: ["any", "all"] }] }),
    C("commute.combine", "Must every place pass?", "select", { opts: ["all", "any"], help: "all: every place must pass. any: one is enough." }),
    C("commute.borderline_margin_minutes", "Borderline margin (min)", "number"),
    C("commute.pt_router", "Public-transport router", "select", { opts: ["motis", "mvg"], help: "motis works for all of Germany; mvg is not built yet." }),
    C("commute.motis_base_url", "Own MOTIS server (optional)", "text", { optional: true }),
  ], data, { onSaved: refresh });

  const where_ = card("Where it may be", "Optional. Postcodes and districts need no lookup. Distance and walking time are estimates (straight line); a flat whose location cannot be found goes to review, never to reject.", [
    C("criteria.area.center", "Center (address or station)", "text", { optional: true, placeholder: "Hauptbahnhof, Ihre Stadt" }),
    C("criteria.area.max_km", "Max distance from the center (km)", "number", { optional: true, min: 0.5, step: 0.5 }),
    C("criteria.area.include_postal_codes", "Only these postcodes (prefixes)", "tags", { help: "Empty means anywhere. Example: 803, 804." }),
    C("criteria.area.exclude_postal_codes", "Never these postcodes", "tags"),
    C("criteria.area.exclude_districts", "Never these districts", "tags"),
    C("criteria.station.max_walk_minutes", "Max walk to the nearest stop (min)", "number", { optional: true, min: 1 }),
    C("criteria.station.kinds", "Stops that count", "tags", { def: ["subway", "rail", "tram"], help: "subway, rail, tram, bus" }),
    C("criteria.station.required", "A farther stop rejects the flat", "bool", { help: "Off: the walk only lifts or lowers the score (give it a weight under Score weights)." }),
  ], data, { onSaved: refresh });

  const about = card("About you", "A message can only state facts listed here. Both languages are needed.", [
    P("applicants", "Applicants", "list", { addLabel: "Add an applicant", item: [
      { p: "first_name", label: "First name" }, { p: "last_name", label: "Last name" }, { p: "age", label: "Age", type: "number", optional: true }] }),
    P("contact.phone", "Phone"), P("contact.sender_email", "Sender email (optional)", "text", { optional: true }),
    P("viewing.de", "Viewing times, German", "text", { help: "Finishes 'Besichtigungen sind bei uns ... möglich'." }),
    P("viewing.en", "Viewing times, English", "text"),
    P("move_in.earliest", "Move in from", "date"), P("move_in.latest", "Move in until", "date"),
    P("facts", "Facts a message may state", "list", { addLabel: "Add a fact", item: [
      { p: "id", label: "Id (short)" }, { p: "de", label: "German" }, { p: "en", label: "English" },
      { p: "usage", label: "Used", type: "select", opts: ["always", "if_relevant", "on_request"] },
      { p: "relevant_if", label: "Only if the listing mentions", type: "tags", optional: true }] }),
  ], data, { onSaved: refresh });

  const hasAvail = !!data.profile.availability;
  const availOn = h("input", { type: "checkbox" }); availOn.checked = hasAvail;
  const avail = card("Viewing availability", "Needed only for the optional automatic reply: it may state only times inside these windows.", [
    P("availability.windows", "Weekly windows", "list", { addLabel: "Add a window", item: [
      { p: "days", label: "Days", type: "tags", placeholder: "mon, tue, wed" }, { p: "start", label: "From (HH:MM)" }, { p: "end", label: "Until (HH:MM)" }] }),
    P("availability.viewing_minutes", "Viewing length (min)", "number", { def: 30, min: 5 }),
    P("availability.min_notice_hours", "Minimum notice (hours)", "number", { def: 12 }),
  ], data, { onSaved: refresh, extraPatch: patch => { if (!availOn.checked) patch.profile = { availability: null }; },
    extra: h("label", { class: "frow chk" }, availOn, h("span", { class: "flabel" }, "Use availability (turn off to remove it)")) });

  const inboxCard = (kind, title, desc, fields, testKind) => {
    const on = h("input", { type: "checkbox" }); on.checked = hasInbox(kind);
    return card(title, desc, fields, data, { onSaved: refresh,
      extraPatch: patch => { if (!on.checked) patch.config = { [kind]: null }; },
      extra: h("div", {}, h("label", { class: "frow chk" }, on, h("span", { class: "flabel" }, "Use this (turn off to remove it)")),
        h("h4", {}, "Credentials, stored only in your local env file"), secretBox(kind), testButton(testKind)) });
  };
  const alerts = inboxCard("alerts", "Alert inbox (listings)", "The inbox that receives your portal alert emails. Read-only: nothing is changed or deleted.", [
    C("alerts.imap_host", "IMAP host"), C("alerts.imap_port", "Port", "number", { min: 1, def: 993 }), C("alerts.folder", "Folder", "text", { def: "INBOX" }),
    C("alerts.lookback_days", "Look back (days)", "number", { min: 1, def: 3 }),
    C("alerts.sender_domains", "Only read mail from these domains", "tags", { help: "Mail from other senders is ignored." }),
  ], "alerts");
  const replies = inboxCard("replies", "Reply inbox (landlord answers)", "Optional. Where landlord replies arrive, to match them to your messages.", [
    C("replies.imap_host", "IMAP host"), C("replies.imap_port", "Port", "number", { min: 1, def: 993 }), C("replies.folder", "Folder", "text", { def: "INBOX" }),
    C("replies.lookback_days", "Look back (days)", "number", { min: 1, def: 30 }),
  ], "replies");
  const smtp = inboxCard("smtp", "Sending (SMTP)", "Optional. Needed only to send messages. 'Test connection' logs in but never sends a message.", [
    C("smtp.host", "SMTP host"), C("smtp.port", "Port", "number", { min: 1, def: 587 }), C("smtp.from_address", "Sender address"),
  ], "smtp");

  const ntfyBox = h("div", {}, h("h4", {}, "Notification topic, stored only in your local env file"), secretBox("notifications"),
    h("div", { class: "actions" }, h("button", { class: "btn small", type: "button", onclick: async () => {
      const { topic } = await post("/api/ntfy-topic", {});
      const spec = data.secrets.find(s => s.section === "notifications");
      if (confirm(`Use this new private topic?\n\n${topic}\n\nSubscribe to it in the ntfy app.`)) { await post("/api/secret", { name: spec.name, value: topic }); await refresh(); }
    } }, "Generate a private topic")), testButton("ntfy", "Send a test notification"));
  const notif = card("Notifications", "Push messages for new flats, a heartbeat and problems, through ntfy.", [
    C("notifications.heartbeat_hours", "Heartbeat every (hours)", "number", { min: 1 }),
    C("notifications.silence_alert_hours", "Warn if no listings for (hours)", "number", { min: 1, optional: true }),
  ], data, { onSaved: refresh, extra: ntfyBox });

  const policy = card("Sending policy", "Starts safe: nothing is sent while shadow mode is on or sending is disabled.", [
    C("send_policy.enabled", "Sending enabled", "bool"), C("send_policy.mode", "Mode", "select", { opts: ["shadow", "live"], help: "shadow logs what it would send; live sends." }),
    C("send_policy.min_score", "Minimum score to auto-send", "number", { min: 0 }),
    C("send_policy.loosen.step_points", "Loosen by (points)", "number", { min: 1 }), C("send_policy.loosen.every_days", "every (days)", "number", { min: 1 }),
    C("send_policy.loosen.floor", "never below", "number"),
    C("send_policy.daily_cap", "Max sends per day", "number"), C("send_policy.per_platform_daily_cap", "Max per platform per day", "number"),
    C("send_policy.platform_allow_list", "Platforms allowed to auto-send", "tags", { help: "Required for live sending." }),
    C("send_policy.quiet_hours", "Quiet hours (optional)", "text", { optional: true, placeholder: "22:00-07:00" }),
  ], data, { onSaved: refresh, saveLabel: "Save policy" });

  const auto = card("Automatic reply to viewing offers", "Optional, off by default. Start in shadow mode. See docs/adr/0004.", [
    C("auto_reply.enabled", "Enabled", "bool"), C("auto_reply.mode", "Mode", "select", { opts: ["shadow", "live"], def: "shadow" }),
    C("auto_reply.daily_cap", "Max per day", "number", { def: 5 }), C("auto_reply.max_replies_per_thread", "Max per conversation", "number", { min: 1, def: 1 }),
    C("auto_reply.horizon_days", "Ignore slots further away than (days)", "number", { min: 1, def: 21 }),
    C("reply_llm.enabled", "Read replies with a local model", "bool", { help: "Only a model on this computer or your network is accepted." }),
    C("reply_llm.base_url", "Local model URL", "text", { def: "http://localhost:11434/v1" }), C("reply_llm.model", "Model name", "text", { def: "llama3.1" }),
  ], data, { onSaved: refresh });

  const weights = Object.keys(data.config.scoring?.weights || { commute: 25, price: 20, size: 10, move_in: 15, balcony: 5, parking: 3, private_landlord: 7, freshness: 10, completeness: 5, station: 0 });
  const scoring = card("Score weights", "Relative importance of each factor. The score is always 0 to 100.",
    weights.map(k => C("scoring.weights." + k, k.replace(/_/g, " "), "number", { def: 0 })), data, { onSaved: refresh });

  const keys = h("section", { class: "card scard" }, h("h3", {}, "API keys (optional)"),
    h("div", { class: "sub" }, "Stored only in your local env file and never shown again."),
    h("div", { class: "sbox" }, data.secrets.filter(s => ["commute", "reply_llm"].includes(s.section)).map(s => secretRow(s, refresh))));

  const where = h("section", { class: "card scard" }, h("h3", {}, "Where your data lives"),
    h("div", { class: "sub" }, "Everything is stored in plain files on this computer. Each person who runs Mia has their own files; nothing is shared or sent anywhere."),
    h("dl", { class: "kv" }, Object.entries({ "Search and settings": data.paths.config, "About you": data.paths.profile, "Credentials": data.paths.env + " (mode 600)", "Flats and history": data.paths.database }).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
    h("div", { class: "hint" }, "Back these up, never commit them. Comments inside the YAML files are not kept when you save here; the previous version is kept as .bak."));

  const sections = [search, commute, where_, about, avail, alerts, replies, smtp, notif, policy, auto, scoring, keys, where];
  const titleOf = sec => sec.querySelector("h3").textContent;
  sections.forEach(sec => { sec.id = "s-" + titleOf(sec).toLowerCase().replace(/[^a-z0-9]+/g, "-"); });
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const toc = h("nav", { class: "toc", "aria-label": "Settings sections" }, sections.map(sec =>
    h("a", { href: "#" + sec.id, onclick: e => { e.preventDefault(); sec.scrollIntoView({ behavior: calm ? "auto" : "smooth" }); } }, titleOf(sec))));
  return h("div", {},
    h("p", { class: "hint", style: "max-width:70ch;margin:0 0 22px" }, "Changes are checked before they are saved, apply to this dashboard at once and to the next scheduled run. Passwords are write-only: once stored they are never shown again."),
    h("div", { class: "slayout" }, toc, h("div", { class: "scols" }, sections)));
}

// ---------- first-run setup
function viewSetup() {
  const today = new Date(); const iso = d => d.toISOString().slice(0, 10);
  const from = new Date(today.getTime() + 90 * 864e5), latest = new Date(today.getTime() + 120 * 864e5);
  const fields = [
    { k: "city", label: "City", type: "text" }, { k: "max_warm_rent", label: "Max warm rent (EUR)", type: "number", def: 1600 },
    { k: "min_area", label: "Min size (m²)", type: "number", def: 50 }, { k: "min_rooms", label: "Min rooms", type: "number", def: 2, step: 0.5 },
    { k: "move_in_from", label: "Ideal move-in", type: "date", def: iso(from) }, { k: "move_in_latest", label: "Latest move-in", type: "date", def: iso(latest) },
    { k: "t_name", label: "Place you travel to: short name", type: "text", def: "work" },
    { k: "t_dest", label: "Its address or station", type: "text" }, { k: "t_arr", label: "Arrive by (HH:MM)", type: "text", def: "09:00" },
    { k: "t_pt", label: "Max public transport (min)", type: "number", def: 30 },
    { k: "first", label: "Your first name", type: "text" }, { k: "last", label: "Your last name", type: "text" },
    { k: "phone", label: "Phone landlords can call", type: "text" },
    { k: "imap_host", label: "IMAP host of your alert inbox", type: "text" }, { k: "domains", label: "Domains the alerts come from", type: "tags", help: "Only mail from these is read." },
  ];
  const inputs = fields.map(f => ({ f, ...makeInput(f, f.def) }));
  const byKey = k => inputs.find(i => i.f.k === k);
  const citySel = h("select", {}, h("option", { value: "" }, "Other city"));
  const hhSel = h("select", {}, h("option", { value: "" }, "None"));
  let presets = null;
  api("/api/presets?lang=en").then(pr => {
    presets = pr;
    pr.cities.forEach(c => citySel.append(h("option", { value: c.key }, c.label)));
    pr.households.forEach(x => hhSel.append(h("option", { value: x.key }, `${x.label}: ${x.description}`)));
  }).catch(() => {});
  const apply = () => {
    const c = presets?.cities.find(x => x.key === citySel.value), hh = presets?.households.find(x => x.key === hhSel.value);
    if (c) byKey("city").el.value = c.name;      // the German name, which routing services find best
    if (hh) { byKey("min_rooms").el.value = hh.min_rooms; byKey("min_area").el.value = hh.min_area; }
    if (c) byKey("t_dest").el.placeholder = `For example ${c.station}`;
  };
  citySel.onchange = hhSel.onchange = apply;
  const err = h("div", { class: "ferr" });
  const go = h("button", { class: "btn primary", type: "button" }, "Create my setup");
  go.onclick = async () => {
    const v = Object.fromEntries(inputs.map(i => [i.f.k, i.get()]));
    const answers = { city: v.city, max_warm_rent: v.max_warm_rent, min_area: v.min_area, min_rooms: v.min_rooms,
      move_in_from: v.move_in_from, move_in_latest: v.move_in_latest,
      targets: [{ name: (v.t_name || "work").toLowerCase().replace(/[^a-z0-9_]+/g, "_"), destination: v.t_dest, arrival_time: v.t_arr, max_pt_minutes: v.t_pt }],
      applicants: [{ first_name: v.first, last_name: v.last }], phone: v.phone, imap_host: v.imap_host, sender_domains: v.domains };
    err.textContent = ""; go.disabled = true;
    const preset = { city: citySel.value || null, household: hhSel.value || null };
    try { await post("/api/setup", { answers, preset: (preset.city || preset.household) ? preset : null }); toast("Setup created"); await boot(); }
    catch (e) { err.textContent = e.message; go.disabled = false; }
  };
  return h("div", { class: "scols one" }, h("section", { class: "card scard" }, h("h3", {}, "Welcome. Let's set up Mia."),
    h("div", { class: "sub" }, "A minute of questions. Everything is saved in plain files on this computer, sending stays off and shadow mode stays on. You can change all of it later in Settings, including mail passwords."),
    h("div", { class: "fgrid" }, h("div", { class: "frow" }, h("label", {}, h("span", { class: "flabel" }, "Start from a city preset"), citySel)),
      h("div", { class: "frow" }, h("label", {}, h("span", { class: "flabel" }, "Household type"), hhSel), h("div", { class: "fhelp" }, "Starting values to adjust, not market data.")),
      inputs.map(i => h("div", { class: "frow" + (i.f.type === "tags" ? " wide" : "") }, h("label", {}, h("span", { class: "flabel" }, i.f.label), i.el), i.f.help ? h("div", { class: "fhelp" }, i.f.help) : null))),
    err, h("div", { class: "actions" }, go)));
}
