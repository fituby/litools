'use strict';
// Builds the chat page HTML from the data sent by the server (see Message.to_data() in chat_message.py).

const MsgFlag = {Removed: 1, Disabled: 2, Reset: 4, TimedOut: 8, Official: 16, Deleted: 32};
const BTN_BAN = 1, BTN_DISMISS = 2;
const REASON_SPAM = 3;
const REASON_TAGS = ["NO", "Shaming", "Insult", "Spam", "Other"];
const REASON_ITEMS = [null, "Public Shaming", "Offensive Language", "Spamming", "Inappropriate Behaviour"];
const WORD_BREAK = "word-break:break-word;";
const PANEL_BG = "background-color:rgba(128,128,128,0.2);";
const HR_DOTTED = '<hr class="my-0" style="border-top:dotted 2px;"/>';

// Usernames of rendered messages by message id (without the section letter).
const msg_users = new Map();

function safeUrl(url) {
  return /^https?:\/\//i.test(url || "") ? url : "#";
}

function commUrl(username) {
  return `https://lichess.org/mod/${encodeURIComponent(username)}/communication`;
}

function abbr(cls, title, inner) {
  return `<abbr class="${escapeHtml(cls)}" title="${escapeHtml(title)}" style="${WORD_BREAK}text-decoration:none;">${inner}</abbr>`;
}

// Segments: plain text, or {t: text, c: class, i: tooltip, h: link}.
function renderSegments(segments) {
  return (segments || []).map(s => {
    if (typeof s == "string")
      return escapeHtml(s);
    const text = escapeHtml(s.t), cls = escapeHtml(s.c);
    if (s.h) {
      const style = ('i' in s && !s.i) ? ` style="${WORD_BREAK}"` : "";
      const link = `<a class="${cls}" href="${escapeHtml(safeUrl(s.h))}" target="_blank"${style}>${text}</a>`;
      return s.i ? abbr(s.c, s.i, link) : link;
    }
    return s.i ? abbr(s.c, s.i, text) : `<span class="${cls}" style="${WORD_BREAK}">${text}</span>`;
  }).join("");
}

function segmentsText(segments) {
  return (segments || []).map(s => typeof s == "string" ? s : s.t).join("");
}

function flairText(flair) {
  const i = flair.indexOf('.');
  if (i <= 0)
    return flair;
  const name = flair.substring(i + 1).replace(/-/g, ' ');
  return name ? name[0].toUpperCase() + name.substring(1) : name;
}

function flairElement(flair, size) {
  return `<abbr class="user-flair text-info pr-1" title="${escapeHtml(flairText(flair))}" style="text-decoration:none;">` +
         `<img src="https://lichess1.org/assets/______0/flair/img/${escapeHtml(flair)}.webp" style="max-width:${size}px;"></abbr>`;
}

function highlightStyle(opacity, is_diff) {
  return is_diff ? `background-color:rgba(160,119,0,${opacity});` : `background-color:rgba(0,160,119,${opacity});`;
}

function utcTime(ms) {
  return new Date(ms).toISOString().substring(11, 19);
}

// Rounds half to even, like Python's round().
function roundEven(x) {
  const r = Math.round(x);
  return (Math.abs(x % 1) == 0.5 && r % 2) ? r - 1 : r;
}

// Time of a message relative to the selected one, e.g. "+12s", "−3m05s".
function relativeTime(m, base_ms) {
  const ds = Math.trunc((m.tm - base_ms) / 1000);
  const a = Math.abs(ds);
  const dt = a < 60 ? `${a}s` : a < 300 ? `${Math.floor(a / 60)}m${String(a % 60).padStart(2, "0")}s` : `${roundEven(a / 60)}m`;
  const text = ds < 0 ? `&minus;${dt} ` : ds > 0 ? `+${dt} ` : "== ";
  const title = m.d == null ? `${utcTime(m.tm)} or before` : `${utcTime(m.tm - m.d * 1000)}…${utcTime(m.tm)}`;
  let html = `<abbr title="${title}" class="user-select-none" style="text-decoration:none;">${text}</abbr>`;
  if (m.fl)
    html += flairElement(m.fl, 17);
  return html;
}

// The "Ban" dropdown and, for likely violations, a one-click timeout button with the suggested reason.
function banButtons(m, id, {add_reason = null, fn = "timeout", idle_class = "btn-secondary", pass_reason = false} = {}) {
  const score = m.s || 0, best_ban = m.rb || 0;
  let best = best_ban || m.rs || 0;
  if (!best && add_reason !== null)
    best = add_reason;
  const item = i => {
    const text = REASON_ITEMS[i];
    const label = (!((m.rm || 0) & (1 << i)) && i !== add_reason) ? text
      : i === best ? `<b class="text-warning">${text}</b>` : `<b>${text}</b>`;
    return `<button class="dropdown-item btn-primary" onclick="${fn}('${id}', ${i});">${label}</button>`;
  };
  let html = `<button class="btn ${score >= 50 ? "btn-warning" : idle_class} nav-item dropdown-toggle align-baseline mr-1 px-1 py-0" ` +
             `data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" style="cursor:pointer;">Ban</button>` +
             `<span class="dropdown-menu" style="">${[1, 2, 3, 4].map(item).join("")}</span>`;
  if (best_ban || (best && score >= 50))
    html = `<button class="btn btn-danger align-baseline flex-grow-0 py-0 px-1" ` +
           `onclick="${fn}('${id}'${pass_reason ? `, ${best}` : ""});">${REASON_TAGS[best]}</button>${html}`;
  return html;
}

function messageText(m) {
  const f = m.f || 0;
  const text = renderSegments(m.t);
  const cls = (f & (MsgFlag.Deleted | MsgFlag.Reset | MsgFlag.Disabled | MsgFlag.TimedOut | MsgFlag.Official)) ? "text-muted"
    : (f & MsgFlag.Removed) ? "text-secondary" : "";
  const html = (f & MsgFlag.Removed) ? `<s style="text-decoration-style:double;">${text}</s>`
    : (f & MsgFlag.TimedOut) ? `<s style="text-decoration-style:dotted;"><u style="text-decoration-style:wavy;">${text}</u></s>`
    : (f & MsgFlag.Disabled) ? `<s>${text}</s>`
    : (f & MsgFlag.Reset) ? `<small>${text}</small>`
    : (f & MsgFlag.Official) ? `<small><i>${text}</i></small>`
    : text;
  return `<span class="${cls}" style="${WORD_BREAK}">${html}</span>`;
}

// Options:
//   tag: section letter of the element id; base: time of the selected message (shows relative times, hides buttons);
//   show_hidden: also show processed/zero-score messages; buttons: BTN_BAN | BTN_DISMISS;
//   dismiss_name: label of the dismiss button; add_user: show the username; mscore: add score/language data for filters;
//   add_reason: reason to suggest if none was detected; highlight: true or the username to highlight; diff: highlight colour;
//   selected: not clickable; centered: the selected message; selection: text for the notes.
function renderMessage(m, o) {
  const id = `${o.tag}${Number(m.id)}`;
  const f = m.f || 0, score = m.s || 0;
  const has_base = o.base !== undefined;
  msg_users.set(String(m.id), m.u);
  let buttons = 0;
  if (!(f & (MsgFlag.Official | MsgFlag.Disabled | MsgFlag.Removed | MsgFlag.TimedOut))) {
    buttons = o.buttons ?? (has_base ? 0 : BTN_BAN | BTN_DISMISS);
    if ((!score && !o.dismiss_name) || (f & MsgFlag.Reset))
      buttons &= ~BTN_DISMISS;
  }
  const is_hidden = f & (MsgFlag.Removed | MsgFlag.Disabled | MsgFlag.Reset | MsgFlag.TimedOut | MsgFlag.Official);
  if (!(o.show_hidden ?? has_base) && (is_hidden || !score))
    return "";
  const time = has_base ? relativeTime(m, o.base) : "";
  const score_theme = score > 50 ? " text-danger" : score > 10 ? " text-warning" : "";
  const score_html = score > 0 ? `<span class="user-select-none${score_theme}">${score}</span>` : "";
  const name = escapeHtml(m.u);
  const username = (o.highlight === true || o.highlight === m.u) ? `<b><u>${name}</u></b>` : name;
  const user = (o.add_user ?? true)
    ? `<a class="text-info user-select-none" href="${commUrl(m.u)}" target="_blank" onclick="prevent_click(event)">${username}</a>` : "";
  const dismiss = (buttons & BTN_DISMISS)
    ? `<button class="btn ${o.dismiss_name ? "btn-secondary" : "btn-primary"} text-nowrap align-baseline flex-grow-0 py-0 px-1 ml-1" ` +
      `onclick="set_ok('${id}');">${o.dismiss_name || "Dismiss"}</button> ` : "";
  const ban = (buttons & BTN_BAN) ? banButtons(m, id, {add_reason: o.add_reason ?? null}) : "";
  const text = messageText(m);
  let attrs = o.mscore ? ` data-mscore="${score}" data-langs="${m.l || 0}"` : "";
  if (o.selection)
    attrs += ` data-selection="${escapeHtml(`${m.u}: "${segmentsText(m.t)}"`)}"`;
  const onclick = o.selected ? "" : ` onclick="select_message(event,'${id}')"`;
  const cls = `align-items-baseline ${o.centered ? "selectee selectee-center" : "selectee"} px-1`;
  let div;
  if (!buttons)
    div = `<div id="msg${id}"${attrs} class="${cls}" style="${WORD_BREAK}"${onclick}>${time}${user} <b>${score_html}</b> ${text}</div>`;
  else if (buttons & BTN_BAN)
    div = `<div id="msg${id}"${attrs} class="${cls}" style="${WORD_BREAK}"${onclick}><div class="d-flex justify-content-between">` +
          `<span>${ban}${time}${user} ${text}</span> <span class="text-nowrap"><b class="pl-2">${score_html}</b>${dismiss}</span></div></div>`;
  else
    div = `<div id="msg${id}"${attrs} class="${cls}"${onclick}><div class="d-flex justify-content-between">` +
          `<span class="d-flex flex-row">${ban}${time}${user}</span><span class="d-flex flex-row">${score_html}${dismiss}</span></div>` +
          `<div class="align-items-baseline" style="${WORD_BREAK}">${text}</div></div>`;
  const highlight = o.highlight && o.highlight === m.u ? highlightStyle(0.2, o.diff) : "";
  return highlight ? `<div style="${highlight}">${div}</div>` : div;
}

function renderTournamentLink(t) {
  return `<a href="${escapeHtml(safeUrl(t.url))}" target="_blank">${escapeHtml(t.name)}</a>`;
}

function renderStatus(status) {
  return `<abbr title="${escapeHtml(status.i)}" class="${escapeHtml(status.c)}">${escapeHtml(status.text)}</abbr>`;
}

function renderErrorTexts(errors) {
  return errors.map(e => escapeHtml(e).replace(/\n/g, "<br>"));
}

function renderGlobalErrors(errors) {
  if (!errors || !errors.length)
    return "";
  return `<div class="text-warning text-break">${errors.length > 1 ? "<b>Errors</b>: " : ""}` +
         `<div>${renderErrorTexts(errors).join("</div><div>")}</div>` +
         `<div><button class="btn btn-info align-baseline flex-grow-1 py-0 px-1" onclick="clear_errors('global');">Clear errors</button></div>` +
         `<div class="text-danger">ABORTED</div></div>`;
}

// A tournament block of the "Dubious messages" section.
function renderReport(r) {
  const errors = r.errors.length
    ? `<div class="d-flex text-warning justify-content-between px-1"><div>${renderErrorTexts(r.errors).join("<br>")}</div>` +
      `<div><button class="btn btn-info text-nowrap align-baseline flex-grow-1 py-0 px-1" data-tourn="${escapeHtml(r.tourn.id)}" ` +
      `onclick="clear_errors(this.dataset.tourn);">Clear errors</button></div></div>` : "";
  const header = `<div class="d-flex user-select-none justify-content-between px-1 mb-1" style="${PANEL_BG}">` +
                 `${renderTournamentLink(r.tourn)}${renderStatus(r.tourn.status)}</div>`;
  const msgs = r.msgs.map(m => renderMessage(m, {tag: 'A', mscore: true})).join("");
  return `<div class="col rounded m-1 px-0" style="${PANEL_BG}min-width:350px">${header}${errors}${msgs}</div>`;
}

// A user block of the "Multi-line messages" section.
function renderMultiReport(r) {
  const id = `B${Number(r.id)}`, m = r.msg;
  const score_cls = r.score > 50 ? ' class="text-danger"' : r.score > 10 ? ' class="text-warning"' : "";
  const [base, extra] = r.score_parts;
  let score = base ? `<abbr title="${escapeHtml(base.i)}">${base.v}</abbr>` : "";
  if (extra)
    score += "+" + (extra.i ? `<abbr title="${escapeHtml(extra.i)}">${extra.v}</abbr>` : extra.v);
  const user = `<a class="text-info" href="${commUrl(m.u)}" target="_blank">${escapeHtml(m.u)}</a>`;
  const dismiss = `<button class="btn btn-primary align-baseline flex-grow-0 px-1 py-0" onclick="set_multi_ok('${id}')">Dismiss</button>`;
  const ban = banButtons(m, id, {add_reason: REASON_SPAM, fn: "timeout_multi", idle_class: "btn-success", pass_reason: true});
  const header = `<div class="user-select-none px-1" style="${PANEL_BG}">` +
                 `<div class="d-flex justify-content-between">${renderTournamentLink(r.tourn)}<span class="ml-1">${renderStatus(r.tourn.status)}</span></div>` +
                 `<div class="d-flex justify-content-between mb-1"><span>${ban}${user}</span>` +
                 `<span class="align-items-baseline ml-1"><span${score_cls}>${score}</span> ${dismiss}</span></div></div>`;
  const msgs = r.msgs.map(x => x === null ? HR_DOTTED : renderMessage(x, {tag: 'B', show_hidden: true, add_user: false,
                                                                         dismiss_name: "Exclude", add_reason: REASON_SPAM})).join("");
  return `<div id="mmsg${id}" data-mscore="${Number(r.score)}" class="col rounded m-1 px-0 pb-1" style="${PANEL_BG}min-width:350px;">${header}${msgs}</div>`;
}

function loadMoreButton(tourn_id, index) {
  return `<div class="d-flex"><button id="btn-load-more-${index}" class="btn btn-success flex-grow-1 py-0 px-1" ` +
         `data-tourn="${escapeHtml(tourn_id)}" onclick="load_more(this.dataset.tourn);"><i class="fas fa-long-arrow-alt-up"></i>` +
         `<span class="mx-2">Load more</span><i class="fas fa-long-arrow-alt-up"></i></button></div>`;
}

function makeSelected(html, is_diff) {
  const style = is_diff ? `${highlightStyle(0.3, true)}border-width:3px !important;` : highlightStyle(0.3);
  return `<div class="border border-success rounded" style="${style}">${html}</div>`;
}

// Returns [chat around the selected message, the selected user's messages].
function renderSelection(sel) {
  if (!sel || !sel.msgs) {
    const notice = sel?.warning ? `<p class="text-warning">${escapeHtml(sel.warning)}</p>`
      : sel?.error ? `<p class="text-danger">${escapeHtml(sel.error)}</p>` : "";
    return [notice, notice];
  }
  const selected = sel.msgs.find(m => m.id == sel.id);
  const opts = {base: selected.tm, highlight: selected.u, diff: sel.diff};
  const centered = {show_hidden: true, highlight: true, diff: sel.diff, centered: true};
  const msg_c = makeSelected(renderMessage(selected, {...centered, tag: 'C', selected: true}), sel.diff);
  const msg_f = makeSelected(renderMessage(selected, {...centered, tag: 'F', selection: true}), sel.diff);
  const chat = sel.msgs.map(m => m.id == sel.id ? ` ${msg_c} ` : renderMessage(m, {...opts, tag: 'C'})).join("");
  const user_msgs = sel.msgs.filter(m => m.u == selected.u)
    .map(m => m.id == sel.id ? msg_f : renderMessage(m, {...opts, tag: 'F', selection: true})).join("");
  const list_start = sel.more ? "" : '<hr class="text-primary my-1" style="border:1px solid;">';
  const list_end = '<hr class="text-primary mt-1 mb-0" style="border:1px solid;">';
  return [`${sel.more ? loadMoreButton(sel.tourn.id, 1) : ""}${list_start}${chat}${list_end}`,
          `${sel.more ? loadMoreButton(sel.tourn.id, 2) : ""}${user_msgs}`];
}
