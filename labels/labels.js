(() => {
  "use strict";
  const targets = globalThis.DSH_MENU_TARGETS || {};
  const target = targets[location.port];
  if (!target || !["localhost", "127.0.0.1"].includes(location.hostname)) return;

  const prefix = `[DSH · ${target.label}] `;
  function labelTitle() {
    if (!document.title.startsWith(prefix)) {
      document.title = prefix + document.title.replace(/^\[DSH · [^\]]*\] /, "");
    }
  }

  function mount() {
    if (!document.body || !document.head) return;
    if (!document.getElementById("dsh-environment-style")) {
      const style = document.createElement("style");
      style.id = "dsh-environment-style";
      // Reserve real layout space, so the header never covers DSH controls.
      style.textContent = "body { padding-top: 32px !important; box-sizing: border-box !important; }";
      document.head.append(style);
    }
    if (document.getElementById("dsh-environment-header")) return;
    const header = document.createElement("div");
    header.id = "dsh-environment-header";
    header.style.cssText = "all:initial;position:fixed;inset:0 0 auto 0;height:32px;z-index:2147483647;display:block;color-scheme:dark;";
    const shadow = header.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host { font: 12px/1.2 system-ui, sans-serif; }
      header { font:12px/1.2 system-ui, -apple-system, "Segoe UI", sans-serif;
        box-sizing:border-box; height:32px; display:flex; align-items:center;
        gap:10px; padding:0 14px; background:${target.background}; color:#edf2fa;
        border-bottom:1px solid ${target.color}66; user-select:none; }
      .dot { width:7px; height:7px; border-radius:50%; background:${target.color}; }
      strong { color:${target.color}; font-size:12px; letter-spacing:.02em; }
      .detail { margin-left:auto; opacity:.7; font-size:11px; }
    `;
    const bar = document.createElement("header");
    bar.setAttribute("aria-label", `DeepSeek Harness — ${target.label}`);
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");
    const name = document.createElement("span");
    name.textContent = "DeepSeek Harness";
    const label = document.createElement("strong");
    label.textContent = target.label;
    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = target.detail;
    bar.append(dot, name, label, detail);
    shadow.append(style, bar);
    document.body.append(header);
  }

  function ready() {
    mount();
    labelTitle();
    new MutationObserver(labelTitle).observe(document.head, { subtree: true, childList: true, characterData: true });
    new MutationObserver(mount).observe(document.body, { childList: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready, { once: true });
  else ready();
})();
