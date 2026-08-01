# -*- coding: utf-8 -*-
"""Транспортная прослойка CDP, встраиваемая в начало каждого пейлоада.

Определяет window.__octopus.send / __octopus_translate / __octopus_onTranslation.
"""
from __future__ import annotations

import json

BINDING_NAME = "__octopus_send"
CONSOLE_PREFIX = "__octopus__"

TRANSPORT_SHIM = r"""
// ── OctopusBridge transport shim ──
if (window.__octopus) { /* уже внедрено — повторную инъекцию игнорируем */ }
else {
window.__octopus = { pending: new Map(), nextId: 1 };
const __ob_send = (window[""" + json.dumps(BINDING_NAME) + r"""])
  ? (o) => window[""" + json.dumps(BINDING_NAME) + r"""](JSON.stringify(o))
  : (o) => console.log(""" + json.dumps(CONSOLE_PREFIX) + r""" + JSON.stringify(o));
window.__octopus.send = __ob_send;
window.__octopus_onTranslation = function (id, text) {
  const resolve = window.__octopus.pending.get(id);
  if (resolve) { window.__octopus.pending.delete(id); resolve(text); }
};
window.__octopus_translate = function (text, timeoutMs) {
  return new Promise((resolve) => {
    const id = window.__octopus.nextId++;
    window.__octopus.pending.set(id, resolve);
    window.__octopus.send({ type: "translate", id: id, text: text });
    setTimeout(() => {
      if (window.__octopus.pending.has(id)) {
        window.__octopus.pending.delete(id);
        resolve(text);
      }
    }, timeoutMs || 4000);
  });
};
}
"""
