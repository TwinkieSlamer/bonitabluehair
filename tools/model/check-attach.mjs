// Checks where the attached pieces of a processed model sit, without drawing it: prints each attached item's box in
// model space at the bind pose next to the box of the head and of the whole body, so a helm that isn't on the head
// (or a piece left at his feet) shows up as numbers. Use it when the page can't be looked at.
//   node check-attach.mjs fixed.glb
import { NodeIO } from "@gltf-transform/core";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions";
import { MeshoptDecoder } from "meshoptimizer";

await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ "meshopt.decoder": MeshoptDecoder });
const doc = await io.read(process.argv[2]);
const root = doc.getRoot(), skin = root.listSkins()[0], joints = skin.listJoints(), ibm = skin.getInverseBindMatrices();

function mul(a, b) { // column-major 4x4
  const o = new Array(16).fill(0);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
  return o;
}
function invert(m) { // general 4x4 inverse
  const inv = new Array(16), [a00, a01, a02, a03, a10, a11, a12, a13, a20, a21, a22, a23, a30, a31, a32, a33] = m;
  const b00 = a00 * a11 - a01 * a10, b01 = a00 * a12 - a02 * a10, b02 = a00 * a13 - a03 * a10, b03 = a01 * a12 - a02 * a11;
  const b04 = a01 * a13 - a03 * a11, b05 = a02 * a13 - a03 * a12, b06 = a20 * a31 - a21 * a30, b07 = a20 * a32 - a22 * a30;
  const b08 = a20 * a33 - a23 * a30, b09 = a21 * a32 - a22 * a31, b10 = a21 * a33 - a23 * a31, b11 = a22 * a33 - a23 * a32;
  const det = 1 / (b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06);
  inv[0] = (a11 * b11 - a12 * b10 + a13 * b09) * det; inv[1] = (a02 * b10 - a01 * b11 - a03 * b09) * det;
  inv[2] = (a31 * b05 - a32 * b04 + a33 * b03) * det; inv[3] = (a22 * b04 - a21 * b05 - a23 * b03) * det;
  inv[4] = (a12 * b08 - a10 * b11 - a13 * b07) * det; inv[5] = (a00 * b11 - a02 * b08 + a03 * b07) * det;
  inv[6] = (a32 * b02 - a30 * b05 - a33 * b01) * det; inv[7] = (a20 * b05 - a22 * b02 + a23 * b01) * det;
  inv[8] = (a10 * b10 - a11 * b08 + a13 * b06) * det; inv[9] = (a01 * b08 - a00 * b10 - a03 * b06) * det;
  inv[10] = (a30 * b04 - a31 * b02 + a33 * b00) * det; inv[11] = (a21 * b02 - a20 * b04 - a23 * b00) * det;
  inv[12] = (a11 * b07 - a10 * b09 - a12 * b06) * det; inv[13] = (a00 * b09 - a01 * b07 + a02 * b06) * det;
  inv[14] = (a31 * b01 - a30 * b03 - a32 * b00) * det; inv[15] = (a20 * b03 - a21 * b01 + a22 * b00) * det;
  return inv;
}
function box(node, matrix) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const prim of node.getMesh().listPrimitives()) {
    const pos = prim.getAttribute("POSITION"), v = [0, 0, 0];
    for (let i = 0; i < pos.getCount(); i++) {
      pos.getElement(i, v);
      const w = matrix ? [0, 1, 2].map((r) => matrix[r] * v[0] + matrix[4 + r] * v[1] + matrix[8 + r] * v[2] + matrix[12 + r]) : v;
      for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], w[k]); hi[k] = Math.max(hi[k], w[k]); }
    }
  }
  return { lo, hi };
}
const f = (b) => `x ${b.lo[0].toFixed(2)}..${b.hi[0].toFixed(2)}  y ${b.lo[1].toFixed(2)}..${b.hi[1].toFixed(2)}  z ${b.lo[2].toFixed(2)}..${b.hi[2].toFixed(2)}`;

// Skinned meshes are stored in model space at the bind pose, so their boxes need no transform.
let body = null;
for (const n of root.listNodes()) {
  if (!n.getSkin() || !n.getMesh()) continue;
  const b = box(n);
  body = body ? { lo: body.lo.map((x, k) => Math.min(x, b.lo[k])), hi: body.hi.map((x, k) => Math.max(x, b.hi[k])) } : b;
  if (/HeadSwap|Ears/.test(n.getName())) console.log(`${n.getName().padEnd(30)} ${f(b)}`);
}
console.log(`${"whole body".padEnd(30)} ${f(body)}   (y is up)`);
// An attached piece: bind-pose world matrix of its joint (the inverse of the joint's inverse bind matrix) x its own.
for (const j of joints) {
  for (const child of j.listChildren()) {
    if (!child.getMesh() || child.getSkin()) continue;
    const world = mul(invert(ibm.getElement(joints.indexOf(j), new Array(16))), child.getMatrix());
    console.log(`${child.getName().padEnd(30)} ${f(box(child, world))}   on ${j.getName()}`);
  }
}
