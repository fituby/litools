'use strict';

function setCookie(name, value, days = 3650) {
  const expires = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toUTCString();
  document.cookie = `${name}=${value ?? ""}; expires=${expires}; path=/; samesite=strict`;
}

function getCookie(name) {
  for (const cookie of document.cookie.split(';')) {
    const c = cookie.trimStart();
    if (c.startsWith(name + "="))
      return c.substring(name.length + 1);
  }
  return null;
}

// Booleans used to be stored as "true" / "" so both "" and "false" mean false.
function getBoolCookie(name, default_value) {
  const value = getCookie(name);
  return value === null ? default_value : value === "true";
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, c =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
}

function sleeping(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Shows/hides an element that uses Bootstrap display classes (d-none vs d-block/d-flex).
function setVisible(selector, visible, display_class = "d-block") {
  $(selector).toggleClass("d-none", !visible).toggleClass(display_class, visible);
}

function scrollToSelected(selector) {
  const element = $(selector)[0];
  if (element) {
    element.scrollIntoView({block: "center"});
    window.scrollTo(0, 0);
  }
}

function copyTextToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).catch(err => console.error("Unable to copy", err));
    return;
  }
  const textArea = document.createElement("textarea");
  textArea.style.cssText = "position:fixed;top:0;left:0;width:2em;height:2em;padding:0;border:none;outline:none;box-shadow:none;background:transparent;";
  textArea.value = text;
  document.body.appendChild(textArea);
  textArea.select();
  try {
    document.execCommand('copy');
  } catch (err) {
    console.error("Unable to copy", err);
  }
  document.body.removeChild(textArea);
}

function userlink(username, {cls = "", suffix = ""} = {}) {
  if (!username)
    return "";
  const name = escapeHtml(username);
  const class_attr = cls ? ` class="${cls}"` : "";
  return `<a${class_attr} href="https://lichess.org/@/${name.toLowerCase()}${suffix}" target="_blank">${name}</a>`;
}

// Extracts the last path segment from a lichess URL, e.g. "https://lichess.org/@/name?mod" -> "name".
function lichessIdFromUrl(text, prefixes = ["https://lichess.org/@/"]) {
  text = text.trim();
  if (!prefixes.some(prefix => text.startsWith(prefix)))
    return null;
  const path = text.split(/[?#]/)[0];
  return path.substring(path.lastIndexOf('/') + 1).trim() || null;
}

function insertAtCursor(input, text) {
  input.setRangeText(text, input.selectionStart, input.selectionEnd, "end");
}

function onEnter(selector, callback) {
  $(selector).on('keydown', e => {
    if (e.key === 'Enter')
      callback(e);
  });
}

// Polls an endpoint until the response no longer contains "not ready".
// `request` is a function returning $.ajax settings, so form values are read on every attempt.
// Returns a handle; call handle.cancel() to stop (e.g. when the user starts a new search).
function pollUntilReady(request, on_ready, {interval = 1000, max_errors = 10, on_error = null} = {}) {
  const handle = {cancelled: false, timer: 0, cancel() { this.cancelled = true; clearTimeout(this.timer); }};
  let num_errors = 0;
  const tick = () => {
    if (handle.cancelled)
      return;
    $.ajax(request())
      .done(data => {
        if (handle.cancelled)
          return;
        num_errors = 0;
        if (data && typeof data === 'object' && "not ready" in data)
          handle.timer = setTimeout(tick, interval);
        else
          on_ready(data);
      })
      .fail(xhr => {
        if (handle.cancelled)
          return;
        if (++num_errors >= max_errors) {
          if (on_error)
            on_error(xhr);
        }
        else
          handle.timer = setTimeout(tick, interval * 2);
      });
  };
  tick();
  return handle;
}

// Theme mode: 0 = Auto, 1 = Dark, 2 = Light; -1/-2 = Auto resolved to Dark/Light.
function prefersDarkMode() {
  return !window.matchMedia || window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function update_mode(val, to_request = true) {
  if (val == 0)
    val = prefersDarkMode() ? -1 : -2;
  for (let i = 0; i < 3; i++)
    $(`#mode_${i}`).toggleClass("active", val == i || (val < 0 && i == 0));
  if (to_request && val != document.body.dataset.mode) {
    setCookie('theme_mode', val);
    const reload = (typeof reload_page === 'function') ? reload_page : () => location.reload();
    $.post(`/set_mode/${val}`).always(reload);
  }
}

// Reloads the page via POST so that the server renders it with the given form values.
function postAndReload(action, values) {
  const form = $('<form method="post">').attr('action', action);
  for (const [name, value] of Object.entries(values))
    $('<input type="hidden">').attr('name', name).val(value ?? "").appendTo(form);
  form.appendTo('body').trigger('submit');
}

$(function() {
  if ($('#mode_0').length) {
    update_mode(Number(document.body.dataset.mode), false);
    if (window.matchMedia)
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', event => {
        if ($('#mode_0').hasClass('active'))
          update_mode(event.matches ? -1 : -2);
      });
  }
  $("#loadOverlay").hide();
  $("#mainOverlay").show();
});
