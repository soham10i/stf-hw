// DT-1 gate helper: the Khronos glTF validator on twin/out/stf2.glb -> JSON summary on stdout
import { readFileSync } from "node:fs";
import validator from "gltf-validator";

const path = process.argv[2];
const report = await validator.validateBytes(new Uint8Array(readFileSync(path)), { maxIssues: 50 });
const msgs = report.issues.messages.map((m) => ({ code: m.code, severity: m.severity, pointer: m.pointer, message: m.message }));
console.log(JSON.stringify({ errors: report.issues.numErrors, warnings: report.issues.numWarnings,
  infos: report.issues.numInfos, hints: report.issues.numHints, messages: msgs, info: report.info }));
