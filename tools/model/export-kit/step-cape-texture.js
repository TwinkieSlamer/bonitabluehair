// Optional, when his cape changes: look up the cape's own texture and save it as a PNG for fix-attach.mjs.
// wow.export 0.2.21 doesn't load cape textures for this client, so the exported cloak wears the body's texture.
// The item id is read from <BBH_IO>/cape-item.txt; each texture found is saved as <BBH_IO>/cape-<file id>.png.
// The chain is item -> ItemModifiedAppearance -> ItemAppearance -> ItemDisplayInfo -> its material resources ->
// texture files; the one to use is under item/objectcomponents/cape/. Run step-import.js first (game data loaded).
const v = core.view;
const path = require("path"), fs = require("fs");
const DIR = process.env.BBH_IO;
const ITEM = Number(fs.readFileSync(path.join(DIR, "cape-item.txt"), "utf8").trim());
const out = { item: ITEM };
const db2 = require_db2(), TFD = require_DBTextureFileData(), MatRes = require_DBItemDisplayInfoModelMatRes(), listfile = require_listfile(), BLPFile = require_blp();
const apps = [];
for (const [id, row] of await db2.ItemModifiedAppearance.getAllRows()) if (row.ItemID === ITEM) apps.push(row);
out.modifiedAppearances = apps.map((r) => ({ ItemAppearanceID: r.ItemAppearanceID, mod: r.ItemAppearanceModifierID }));
const app = apps.length ? await db2.ItemAppearance.getRow(apps[0].ItemAppearanceID) : null;
out.appearance = app && { ItemDisplayInfoID: app.ItemDisplayInfoID };
const disp = app ? await db2.ItemDisplayInfo.getRow(app.ItemDisplayInfoID) : null;
if (!disp) return out;
if (TFD.initializeTextureFileData) await TFD.initializeTextureFileData();
if (TFD.ensureInitialized) await TFD.ensureInitialized();
await MatRes.ensureInitialized();
const fdids = new Set(MatRes.getItemDisplayIdTextureFileIds(app.ItemDisplayInfoID) || []);
const mats = (disp.ModelMaterialResourcesID || []).filter((x) => x > 0);
out.materialResources = mats;
for (const m of mats) for (const fn of ["getTextureFDIDsByMatID", "getTextureFileDataIDs", "getFileDataIDs"]) {
  if (!TFD[fn]) continue;
  const got = TFD[fn](m);   // a number, an array or a Set, depending on the lookup
  for (const f of (got && typeof got === "object" ? [...got] : [got])) if (typeof f === "number") fdids.add(f);
}
if (!fdids.size) for (const [id, row] of await db2.TextureFileData.getAllRows()) if (mats.includes(row.MaterialResourcesID)) fdids.add(id);
out.textures = [];
for (const f of fdids) {
  const entry = { fileDataID: f, name: (listfile.getByID && listfile.getByID(f)) || String(f) };
  try {
    const blp = new BLPFile(await v.casc.getFile(f));
    entry.size = blp.width + "x" + blp.height;
    const file = path.join(DIR, "cape-" + f + ".png");
    await blp.saveToPNG(file, 15);
    entry.png = file;
    entry.bytes = fs.statSync(file).size;
  } catch (e) { entry.error = String((e && e.message) || e); }
  out.textures.push(entry);
}
return out;
