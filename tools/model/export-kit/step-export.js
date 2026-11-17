// Step 3: export the character as glTF with animations, and list the files it wrote. The output goes to
// wow.export's export folder (character/nightelf/female/nightelffemale_hd.gltf). Screenshot: <BBH_IO>/export.png.
const v = core.view, wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fs = require("fs"), path = require("path");
v.config.modelsExportAnimations = true;
v.config.exportCharacterFormat = "GLTF";
await wait(500);
const dir = v.config.exportDirectory;
const before = Date.now();
const btn = [...document.querySelectorAll("input[type=button], button, .ui-menu-button *")].find((b) => /^Export glTF$/i.test((b.value || b.textContent || "").trim()));
if (!btn) return { error: "no export button", candidates: [...document.querySelectorAll(".character-export-menu *")].map((e) => e.tagName + ":" + (e.value || e.textContent || "").trim().slice(0, 30)).slice(0, 20) };
btn.click();
// Wait for the export to finish: the app goes busy, then stops being busy.
const t0 = Date.now(); let sawBusy = false;
while (Date.now() - t0 < 300000) { if (v.isBusy) sawBusy = true; if (sawBusy && !v.isBusy) break; await wait(500); }
await wait(1500);
function newest(d, acc = []) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) newest(p, acc); else { const st = fs.statSync(p); if (st.mtimeMs >= before - 2000) acc.push({ p, size: st.size }); } } return acc; }
let files = [];
try { files = newest(dir); } catch (e) {}
await __bbhShot("export.png");
const gltf = files.filter((f) => /\.gltf$/i.test(f.p));
return { dir, sawBusy, toast: v.toast && v.toast.message, gltf, count: files.length, notAnimation: files.filter((f) => !/_anim\d+-\d+\.bin$/.test(f.p)).map((f) => path.relative(dir, f.p) + " " + f.size) };
