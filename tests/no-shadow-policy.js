"use strict";

const fs = require("node:fs");
const path = require("node:path");
const SafetyPolicy = require("../safety-policy.js");

const root = path.resolve(__dirname, "..");
const policyConsumers = ["app.js", "join.js", "server.js"];
const forbiddenNames = /\b(?:HIGH_RISK|MEDICAL_PATTERN|RISK_PATTERN|medicalRegex|riskRegex|inferLegacyProfessionalSource)\b|function\s+isMedicalOrHighRisk\b/;
const forbiddenRiskRegex = /(?:=|\(|,|return)\s*\/[^/\n]*(?:胸|呼吸|脉搏|血压|血糖|血氧|意识|抽搐|跌倒|摔倒|药物|剂量|chest|pulse|seizure|medication)[^/\n]*\/[dgimsuvy]*/i;

function assert(condition, message) {
  if (!condition) throw new Error(`Policy ownership check failed: ${message}`);
}

assert(!fs.existsSync(path.join(root, "risk.js")), "legacy risk.js must not exist");
const productionFiles = fs.readdirSync(root, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".js") && !["safety-policy.js"].includes(entry.name))
  .map((entry) => entry.name);
for (const filename of productionFiles) {
  const source = fs.readFileSync(path.join(root, filename), "utf8");
  assert(!forbiddenNames.test(source), `${filename} defines a shadow classifier`);
  assert(!forbiddenRiskRegex.test(source), `${filename} contains a shadow medical-risk regex`);
}
for (const filename of policyConsumers) {
  const source = fs.readFileSync(path.join(root, filename), "utf8");
  assert(source.includes("SafetyPolicy"), `${filename} must use the shared policy contract`);
}

const serverSource = fs.readFileSync(path.join(root, "server.js"), "utf8");
assert(serverSource.includes('require("./safety-policy.js")'), "server must import the shared policy module");
assert(serverSource.indexOf("requirePolicyVersion(request)") < serverSource.indexOf('if (url.pathname === "/api/rooms")'), "the API policy handshake must guard current and future room routes");
assert(serverSource.includes("SafetyPolicy.getProfessionalReference") && serverSource.includes("SafetyPolicy.matchesProfessionalReference"), "server professional provenance must be resolved from the policy-owned registry");

const appSource = fs.readFileSync(path.join(root, "app.js"), "utf8");
assert(appSource.includes("SafetyPolicy.matchesProfessionalReference") && appSource.includes("SafetyPolicy.isImmediateReference"), "browser migration and matching must verify immutable policy-owned references");
assert(!appSource.includes("nurse: SOURCE_IDS.PROFESSIONAL") && !appSource.includes("professional: SOURCE_IDS.PROFESSIONAL"), "legacy actor aliases must not infer professional provenance");

const registeredReference = SafetyPolicy.getProfessionalReference("demo-fall-immediate-v1");
assert(registeredReference && SafetyPolicy.matchesProfessionalReference(registeredReference) && SafetyPolicy.isImmediateReference(registeredReference), "the versioned bundled reference must be internally valid");
assert(!SafetyPolicy.matchesProfessionalReference({ ...registeredReference, summary: "altered" }), "registered professional content must be immutable");

const expectedPolicyAsset = `./safety-policy.js?v=${SafetyPolicy.ASSET_VERSION}`;
for (const filename of ["index.html", "join.html", "sw.js"]) {
  const source = fs.readFileSync(path.join(root, filename), "utf8");
  assert(source.includes(expectedPolicyAsset), `${filename} must reference/cache the matching policy asset`);
  assert(!source.includes("risk.js"), `${filename} still references the retired classifier`);
}

console.log(`✓ single policy owner and cache/version contract (${SafetyPolicy.VERSION})`);
