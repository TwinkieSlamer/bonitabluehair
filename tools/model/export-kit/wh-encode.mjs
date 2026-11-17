// Builds a Wowhead dressing-room link (format v15) for wow.export's "Import from Wowhead", which is how his gear
// gets onto the character in wow.export's Characters tab.
//   node wh-encode.mjs '{"2":279879,"3":9822,...}' 40 [path to wow.export's src/app.js]
// The first argument maps dressing-room slot numbers to item ids:
//   1 head, 2 shoulder, 3 back, 4 chest, 5 shirt, 6 tabard, 7 wrist, 8 hands, 9 waist, 10 legs, 11 feet,
//   12 main hand, 13 off hand   (necklaces, rings, trinkets and relics have no slot: they aren't drawn)
// The second is his level. With the third, the link is also decoded with wow.export's own parser to prove it
// round-trips, and the decoded form is printed.
import fs from "node:fs";
import vm from "node:vm";

const charset = "0zMcmVokRsaqbdrfwihuGINALpTjnyxtgevElBCDFHJKOPQSUWXYZ123456";
function encode(n) {
  if (!n) return "0";
  let s = "";
  while (n > 0) { s = charset[n % 58] + s; n = Math.floor(n / 58); }
  return s;
}
const items = JSON.parse(process.argv[2]);
const race = 4, gender = 1, clazz = 11, spec = 0, level = Number(process.argv[3] || 40);   // Night Elf, female, Druid
const segs = [encode(race), charset[gender] + charset[clazz] + charset[spec] + encode(level), "00", "0", "0", "0"];
for (const [slot, id] of Object.entries(items).sort((a, b) => a[0] - b[0])) segs.push("7" + charset[Number(slot) - 1] + encode(id));
const url = "https://www.wowhead.com/dressing-room#" + charset[15] + segs.join("8");
console.log(url);

if (process.argv[4]) {
  const js = fs.readFileSync(process.argv[4], "utf8");
  const start = js.indexOf('var charset = "' + charset + '"');
  const end = js.indexOf("module2.exports = { wowhead_parse }", start);
  if (start < 0 || end < 0) { console.log("(could not find wow.export's parser in that file; link not checked)"); process.exit(0); }
  const sandbox = { result: null };
  vm.runInNewContext(js.slice(start, end) + ";result = wowhead_parse(" + JSON.stringify(url) + ");", sandbox);
  console.log(JSON.stringify(sandbox.result));
}
