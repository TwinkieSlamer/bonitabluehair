#!/usr/bin/env node
// Keep only the idle clip in a glTF/GLB file and rename it "Idle".
//
//   List the clips:   node keep-idle.mjs bonita-raw.glb
//   Keep one clip:    node keep-idle.mjs bonita-raw.glb bonita-idle.glb "Stand"
//
// With no clip name given, it keeps the first clip whose name contains "stand"
// (WoW's idle animation is called Stand). Everything the dropped clips used is
// pruned, so the file shrinks.

import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { prune } from '@gltf-transform/functions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';

const [, , input, output, wanted] = process.argv;

if (!input) {
  console.error('Usage: node keep-idle.mjs <input.glb|gltf> [output.glb] [clip name]');
  process.exit(1);
}

await MeshoptDecoder.ready;
await MeshoptEncoder.ready;
const io = new NodeIO()
  .registerExtensions(ALL_EXTENSIONS)
  .registerDependencies({ 'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder });
const doc = await io.read(input);
const anims = doc.getRoot().listAnimations();

const duration = (anim) => {
  let max = 0;
  for (const sampler of anim.listSamplers()) {
    const times = sampler.getInput();
    if (times) max = Math.max(max, times.getMax([0])[0]);
  }
  return max;
};

if (!output) {
  if (anims.length === 0) {
    console.log('No animation clips in this file. Re-export with animations turned on.');
  } else {
    console.log(`${anims.length} clip(s):`);
    anims.forEach((a, i) => console.log(`  ${String(i).padStart(3)}  ${a.getName() || '(unnamed)'}  ${duration(a).toFixed(2)} s`));
  }
  process.exit(0);
}

let keep = wanted
  ? anims.find((a) => a.getName() === wanted)
  : anims.find((a) => /stand/i.test(a.getName()));

if (!keep && wanted && /^\d+$/.test(wanted)) keep = anims[Number(wanted)];

if (!keep) {
  console.error(`No clip matched ${wanted ? `"${wanted}"` : '"stand"'}. Run without an output path to list the clips.`);
  process.exit(1);
}

const kept = keep.getName();
for (const a of anims) if (a !== keep) a.dispose();
keep.setName('Idle');

await doc.transform(prune());
await io.write(output, doc);
console.log(`Kept "${kept}" (${duration(keep).toFixed(2)} s) as "Idle", dropped ${anims.length - 1} other clip(s). Wrote ${output}`);
