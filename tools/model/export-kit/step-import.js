// Step 1 (send with wx.ps1 right after the app starts): open the local WoW: Forever install, go to the Characters
// tab once the game data has loaded, and import his gear from the dressing-room link in <BBH_IO>/import-url.txt
// (written from wh-encode.mjs's output). Doing it in this order matters: importing before the install has loaded,
// or letting the app restart straight into the Characters tab, crashed it on Nov 7, 2026.
const v = core.view, vapp = document.getElementById("container").__vue_app__, app = vapp._instance.proxy;
const fs = require("fs"), path = require("path");
const DIR = process.env.BBH_IO;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn, ms = 60000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (fn()) return true; } catch (e) {} await wait(250); } return false; };
const errors = [], steps = [];
vapp.config.errorHandler = (err, inst, info) => {
  errors.push({ message: String(err && err.message), info, stack: String(err && err.stack).split("\n").slice(0, 16).join("\n") });
  fs.writeFileSync(path.join(DIR, "errors.json"), JSON.stringify(errors, null, 2));
};
const url = fs.readFileSync(path.join(DIR, "import-url.txt"), "utf8").trim();
// 1. Open the local Forever install from the "recent" list on the first screen.
if (!v.casc) {
  const link = [...document.querySelectorAll("#module-container span.link")].find((e) => /World of Warcraft \(Forever\)/.test(e.textContent));
  steps.push("recent link: " + !!link);
  if (link) link.click();
  await wait(1500);
  if (v.sourceSelectShowBuildSelect) {
    const b = [...document.querySelectorAll("#module-container input[type=button], #module-container .build-select *")].find((e) => /Forever|1\.60/.test(e.value || e.textContent || ""));
    steps.push("build button: " + (b ? (b.value || b.textContent).trim() : "none"));
    if (b) b.click();
  }
}
const loaded = await until(() => v.casc && !v.isLoading && document.querySelector("#nav"), 240000);
steps.push("casc loaded: " + loaded);
await wait(1500);
// 2. Characters tab, once the customization data is ready.
app.setActiveModule("tab_characters");
await until(() => document.querySelector(".character-wowhead-button"), 60000);
await until(() => !v.chrModelLoading, 120000);
await wait(2000);
steps.push("characters ready");
// 3. Import from the dressing-room link.
v.characterImportMode = "WHEAD";
await wait(400);
v.chrImportWowheadURL = url;
await wait(300);
const btn = [...document.querySelectorAll("#character-import-panel-floating input[type=button]")].find((b) => b.value === "Import Character");
steps.push("import button: " + !!btn);
if (btn) btn.click();
await wait(1500);
await until(() => !v.chrModelLoading, 120000);
await wait(3000);
await __bbhShot("imported.png");
const c = v.casc || {};
return { steps, errors, build: c.build && (c.build.Product + " " + (c.getBuildName ? c.getBuildName() : "")), crashed: !!document.getElementById("crash-screen") && !document.getElementById("container"),
  equipped: JSON.parse(JSON.stringify(v.chrEquippedItems || {})), toast: v.toast && v.toast.message };
