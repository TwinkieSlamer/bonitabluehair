// Optional: list the attachment points of the character model (bone and position for each). fix-attach.mjs needs
// them to put the pieces wow.export leaves loose at the origin (helm, shoulders, weapons) on their bones.
// 921844 is the Night Elf female HD model. The game data must already be loaded (run step-import.js first).
const M2Loader = require_M2Loader(), SKELLoader = require_SKELLoader();
const m2 = new M2Loader(await core.view.casc.getFile(921844));
await m2.load();
const out = { m2Keys: Object.keys(m2).filter((k) => !/^(data|vertices|normals|uv|boneWeights|boneIndices|textures|triangles)/.test(k)).slice(0, 60) };
const list = (xs) => (xs || []).map((a) => ({ id: a.id, bone: a.bone, position: a.position }));
out.m2Attachments = list(m2.attachments);
out.m2BoneCount = (m2.bones || []).length;
out.skelId = m2.skeletonFileID || m2.skelFileID || null;
if (out.skelId) {
  const skel = new SKELLoader(await core.view.casc.getFile(out.skelId));
  await skel.load();
  out.skelKeys = Object.keys(skel).slice(0, 40);
  out.skelAttachments = list(skel.attachments);
  out.skelBoneCount = (skel.bones || []).length;
  out.parentSkel = skel.parent_skel_file_id || null;
}
return out;
