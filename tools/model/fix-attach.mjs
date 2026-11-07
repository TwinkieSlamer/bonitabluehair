// Puts wow.export's loose attachment models (shoulders, weapon) on their bones, and turns the model to face +Z.
// wow.export draws an attachment at boneMatrix x translate(position), with the position converted from the game's
// Z-up space as (x, z, -y). In glTF the joint's world matrix W satisfies boneMatrix = W x inverseBind, so the
// attachment becomes a child of the joint with local matrix inverseBind x translate(position).
//   node fix-attach.mjs in.glb out.glb
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { MeshoptDecoder, MeshoptEncoder } from "meshoptimizer";

// From the Night Elf female HD model (file 921844): attachment id -> bone index and position (game space).
const ATTACH = {
  "Main-hand_Item271203_0": { bone: 225, pos: [0, 0, 0] },
  "Shoulder (R)_Item5319_0": { bone: 204, pos: [-0.09428267925977707, -0.1509692221879959, 1.9462634325027466] },
  "Shoulder (L)_Item5319_0": { bone: 205, pos: [-0.09427326172590256, 0.1509847193956375, 1.94625985622406] }
};

await MeshoptDecoder.ready; await MeshoptEncoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ "meshopt.decoder": MeshoptDecoder, "meshopt.encoder": MeshoptEncoder });
const doc = await io.read(process.argv[2]);
const root = doc.getRoot(), skin = root.listSkins()[0], joints = skin.listJoints();
const ibm = skin.getInverseBindMatrices();

function mul(a, b) { // column-major 4x4
  const o = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
  return o;
}
function decompose(m) {
  const t = [m[12], m[13], m[14]];
  const sx = Math.hypot(m[0], m[1], m[2]), sy = Math.hypot(m[4], m[5], m[6]), sz = Math.hypot(m[8], m[9], m[10]);
  const r00 = m[0] / sx, r10 = m[1] / sx, r20 = m[2] / sx, r01 = m[4] / sy, r11 = m[5] / sy, r21 = m[6] / sy, r02 = m[8] / sz, r12 = m[9] / sz, r22 = m[10] / sz;
  const tr = r00 + r11 + r22; let q;
  if (tr > 0) { const s = Math.sqrt(tr + 1) * 2; q = [(r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s, s / 4]; }
  else if (r00 > r11 && r00 > r22) { const s = Math.sqrt(1 + r00 - r11 - r22) * 2; q = [s / 4, (r01 + r10) / s, (r02 + r20) / s, (r21 - r12) / s]; }
  else if (r11 > r22) { const s = Math.sqrt(1 + r11 - r00 - r22) * 2; q = [(r01 + r10) / s, s / 4, (r12 + r21) / s, (r02 - r20) / s]; }
  else { const s = Math.sqrt(1 + r22 - r00 - r11) * 2; q = [(r02 + r20) / s, (r12 + r21) / s, s / 4, (r10 - r01) / s]; }
  return { t, q, s: [sx, sy, sz] };
}

const parentOf = new Map();
for (const n of root.listNodes()) for (const c of n.listChildren()) parentOf.set(c, n);
for (const node of root.listNodes()) {
  const a = ATTACH[node.getName()];
  if (!a) continue;
  let bi = a.bone;
  // Shoulder pads go on the collarbones: on the upper-arm attachment bones they swing down with the arm and stand
  // up like shields beside it once the idle lowers the arms from the T-pose.
  if (/Shoulder/.test(node.getName())) bi = joints.findIndex((j) => j.getName() === (/\(R\)/.test(node.getName()) ? "bone_ShoulderR" : "bone_ShoulderL"));
  const joint = joints[bi];
  const inv = ibm.getElement(bi, new Array(16));
  const p = [a.pos[0], a.pos[2], -a.pos[1]];
  const local = mul(inv, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, p[0], p[1], p[2], 1]);
  const d = decompose(local);
  parentOf.get(node)?.removeChild(node);
  joint.addChild(node);
  node.setTranslation(d.t).setRotation(d.q).setScale(d.s);
  console.log(`${node.getName()} -> joint ${bi} (${joint.getName()}) t=${d.t.map((x) => x.toFixed(3))} s=${d.s.map((x) => x.toFixed(3))}`);
}
// Game models face +X; the viewer looks down -Z. Turn the whole model -90 degrees about Y so he faces the camera.
const top = root.listScenes()[0].listChildren()[0];
const h = -Math.PI / 4;
top.setRotation([0, Math.sin(h), 0, Math.cos(h)]);
console.log("root", top.getName(), "rotated to face +Z");
await io.write(process.argv[3], doc);
console.log("wrote", process.argv[3]);
