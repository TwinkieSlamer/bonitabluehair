// Step 2: set his appearance in the Characters tab, matched by eye to his Armory picture (Blizzard's API doesn't
// give it), then hide the three accessories that come switched on and aren't in his picture.
// Screenshot: <BBH_IO>/look.png. Returns which choices took and which geosets are on.
const v = core.view, wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function setChoice(optionId, choiceId) {
  v.chrCustOptionSelection = [v.chrCustOptions.find((o) => o.id === optionId)];
  await wait(350);
  const ch = v.chrCustChoices.find((c) => c.id === choiceId);
  if (!ch) return false;
  v.chrCustChoiceSelection = [ch];
  await wait(1400);
  return v.chrCustActiveChoices.some((a) => a.optionID === optionId && a.choiceID === choiceId);
}
// Skin Color 806, Face 825, Hair Style 844 "Loose Tail", Hair Color 863 (teal), Markings 873 "Crane", Markings Color 8177.
const set = { skin: await setChoice(49, 806), face: await setChoice(50, 825), hair: await setChoice(51, 844), color: await setChoice(52, 863),
  marks: await setChoice(53, 873), markColor: await setChoice(745, 8177) };
await wait(800);
// Geosets 3701 Headdress (a circlet), 1601 FacialJewelry and 3601 Necklace.
const HIDE = [3701, 1601, 3601];
for (const g of v.chrCustGeosets) if (HIDE.includes(g.id)) g.checked = false;
await wait(2500);
await __bbhShot("look.png");
const geo = v.chrCustGeosets.filter((g) => g.checked).map((g) => g.id + ":" + g.label);
return { set, hidden: v.chrCustGeosets.filter((g) => HIDE.includes(g.id)).map((g) => g.id + ":" + g.label + "=" + g.checked), checkedGeosets: geo };
