// Automation helper for an unpacked copy of wow.export. It is not part of wow.export: copy this file into the app's
// src/ folder and add <script src="bbh-auto.js"></script> before </body> in src/index.html.
//
// When the app is started with the BBH_IO environment variable set to a folder, it runs each command written to
// <BBH_IO>/cmd.js inside the app (as the body of an async function) and writes the result to <BBH_IO>/out.json, so
// an export can be driven without clicking: see wx.ps1. Without BBH_IO it does nothing and the app is as normal.
// Window screenshots from a command: await __bbhShot("name.png") saves into <BBH_IO>.
(function () {
  const fs = require("fs"), path = require("path");
  const DIR = process.env.BBH_IO;
  if (!DIR) return;
  try { fs.mkdirSync(DIR, { recursive: true }); } catch (e) {}
  // Only commands written after this start are run. A command left over from an earlier run is ignored: on
  // Nov 12, 2026 a leftover "quit" closed the app three seconds after it opened.
  let last = Date.now();
  function safe() {
    const seen = new WeakSet();
    return (k, v) => {
      if (typeof v === "bigint") return Number(v);
      if (typeof v === "object" && v !== null) { if (seen.has(v)) return "[circular]"; seen.add(v); }
      if (typeof v === "function") return "[function]";
      if (typeof Element !== "undefined" && v instanceof Element) return "<" + v.tagName.toLowerCase() + (v.id ? "#" + v.id : "") + ">";
      return v;
    };
  }
  window.__bbhShot = (name) => new Promise((resolve) => {
    nw.Window.get().capturePage((buf) => { fs.writeFileSync(path.join(DIR, name || "shot.png"), buf); resolve(name || "shot.png"); }, { format: "png", datatype: "buffer" });
  });
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  async function tick() {
    try {
      const f = path.join(DIR, "cmd.js");
      if (fs.existsSync(f)) {
        const st = fs.statSync(f);
        if (st.mtimeMs > last) {
          last = st.mtimeMs;
          const code = fs.readFileSync(f, "utf8");
          const id = (/^\/\/ id:(\S+)/.exec(code) || [])[1] || null;
          let res;
          try { res = { ok: true, value: await new AsyncFunction(code)() }; }
          catch (e) { res = { ok: false, error: String((e && e.stack) || e) }; }
          res.at = new Date().toISOString();
          res.cmd = id;
          fs.writeFileSync(path.join(DIR, "out.json"), JSON.stringify(res, safe(), 2));
        }
      }
    } catch (e) {
      try { fs.writeFileSync(path.join(DIR, "helper-error.txt"), String((e && e.stack) || e)); } catch (e2) {}
    }
    setTimeout(tick, 300);
  }
  fs.writeFileSync(path.join(DIR, "ready.txt"), new Date().toISOString());
  setTimeout(tick, 300);
})();
