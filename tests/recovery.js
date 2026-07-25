"use strict";

const assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const Recovery = require("../recovery");

const passphrase = "correct horse battery staple";
const timestamp = "2026-07-25T08:00:00.000Z";

function baseState(overrides = {}) {
  return {
    schemaVersion: 7,
    mode: "real",
    meta: { updatedAt: 123, lastBackupAt: timestamp, lastRecovery: { auditId: "old" } },
    onboarding: { status: "complete", step: 6, consentDecision: "granted" },
    guideFilter: "all",
    stageOneCompleted: true,
    rehearsalCompleted: false,
    quietInbox: 0,
    activeRest: { startedAt: Date.now(), capability: "must-not-leave-device" },
    activeRehearsal: { sessionRecordId: "active-one", tasks: [true, false] },
    sessions: [{
      schemaVersion: 1,
      id: "active-one",
      status: "active",
      demo: false,
      startSnapshot: { stage: "observe", consentRevision: 4 },
      facts: { secret: "transient" },
      checkIns: { caregiver: null, substitute: null, careRecipient: null },
    }],
    recommendationOverride: null,
    demoJourney: null,
    appliedRemoteSessionIds: ["remote-room-one"],
    debriefs: [],
    gaps: [],
    revokedGuideIds: [],
    confirmations: [],
    recipientConsent: { status: "granted", revision: 4, grantedAt: timestamp, withdrawnAt: null },
    family: {
      caregiverName: "林安",
      caregiverPhone: "13800138000",
      recipientName: "林禾",
      recipientConsented: true,
      relayName: "周宁",
      emergencyContactName: "陈平",
      emergencyContactPhone: "13900139000",
      emergencyService: "999",
      redLines: ["无法唤醒"],
      restGoal: { title: "散步", date: "周六", duration: 20 },
    },
    activity: [],
    guides: [],
    ...overrides,
  };
}

function authority(overrides = {}) {
  return {
    schemaVersion: 1,
    status: "granted",
    revision: 4,
    changedAt: timestamp,
    grantedAt: timestamp,
    withdrawnAt: null,
    ...overrides,
  };
}

function bytes(value) {
  return new TextEncoder().encode(value);
}

function decode64(value) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

function encode64(value) {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function aad(envelope) {
  return bytes(JSON.stringify([
    envelope.format,
    envelope.version,
    envelope.createdAt,
    envelope.appBuild,
    envelope.kdf.name,
    envelope.kdf.hash,
    envelope.kdf.iterations,
    envelope.kdf.salt,
    envelope.cipher.name,
    envelope.cipher.iv,
  ]));
}

async function replaceEncryptedPayload(envelopeText, replacement, secret = passphrase) {
  const envelope = JSON.parse(envelopeText);
  const salt = decode64(envelope.kdf.salt);
  const iv = decode64(envelope.cipher.iv);
  const baseKey = await webcrypto.subtle.importKey("raw", bytes(secret), "PBKDF2", false, ["deriveKey"]);
  const key = await webcrypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: Recovery.KDF_ITERATIONS },
    baseKey,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"],
  );
  const encrypted = await webcrypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: aad(envelope), tagLength: 128 },
    key,
    bytes(JSON.stringify(replacement)),
  );
  envelope.ciphertext = encode64(new Uint8Array(encrypted));
  return JSON.stringify(envelope);
}

async function rejectsCode(work, code, message) {
  await assert.rejects(work, (error) => error instanceof Recovery.RecoveryError && error.code === code, message);
}

(async () => {
  const encrypted = await Recovery.createEncryptedBackup({
    state: baseState(),
    authority: authority(),
    passphrase,
    appBuild: "2026.07.25-production-v7",
    now: timestamp,
  }, { crypto: webcrypto });
  const envelope = JSON.parse(encrypted);
  assert.equal(envelope.format, Recovery.FORMAT, "backup uses the dedicated recovery format");
  assert.equal(envelope.version, 1, "backup envelope is versioned");
  assert.deepEqual(
    { name: envelope.kdf.name, hash: envelope.kdf.hash, iterations: envelope.kdf.iterations },
    { name: "PBKDF2", hash: "SHA-256", iterations: 310_000 },
    "backup pins the reviewed PBKDF2 parameters",
  );
  assert.equal(envelope.cipher.name, "AES-GCM", "backup uses authenticated AES-GCM");
  assert(!encrypted.includes("13800138000") && !encrypted.includes("林安"), "encrypted file does not expose household plaintext");

  const roundTrip = await Recovery.decryptEncryptedBackup(encrypted, passphrase, { crypto: webcrypto });
  assert.equal(roundTrip.payload.state.family.caregiverName, "林安", "correct password restores household content");
  assert.equal(roundTrip.payload.state.activeRest, null, "active rest is stripped");
  assert.equal(roundTrip.payload.state.activeRehearsal, null, "active rehearsal is stripped");
  assert.deepEqual(roundTrip.payload.state.appliedRemoteSessionIds, [], "remote room replay markers are stripped");
  assert.equal(roundTrip.payload.state.sessions[0].status, "interrupted", "active history becomes a conservative interrupted snapshot");
  assert.equal(roundTrip.payload.state.sessions[0].facts, null, "transient active facts are not invented");
  assert.equal(roundTrip.payload.state.meta.lastBackupAt, undefined, "device-local backup reminder metadata is stripped");
  assert.equal(roundTrip.payload.state.meta.lastRecovery, undefined, "prior restore audit metadata is stripped");

  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(encrypted, "this is the wrong password", { crypto: webcrypto }),
    "authentication_failed",
    "wrong password fails without exposing whether plaintext exists",
  );

  const tampered = JSON.parse(encrypted);
  tampered.createdAt = "2026-07-25T08:00:01.000Z";
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(JSON.stringify(tampered), passphrase, { crypto: webcrypto }),
    "authentication_failed",
    "authenticated envelope metadata detects tampering",
  );

  const tamperedCiphertext = JSON.parse(encrypted);
  tamperedCiphertext.ciphertext = `${tamperedCiphertext.ciphertext[0] === "A" ? "B" : "A"}${tamperedCiphertext.ciphertext.slice(1)}`;
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(JSON.stringify(tamperedCiphertext), passphrase, { crypto: webcrypto }),
    "authentication_failed",
    "AES-GCM detects ciphertext tampering",
  );

  const unsupported = JSON.parse(encrypted);
  unsupported.version = 99;
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(JSON.stringify(unsupported), passphrase, { crypto: webcrypto }),
    "unsupported_envelope_version",
    "unsupported envelope versions fail before decryption",
  );

  const unsupportedAlgorithm = JSON.parse(encrypted);
  unsupportedAlgorithm.kdf.name = "scrypt";
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(JSON.stringify(unsupportedAlgorithm), passphrase, { crypto: webcrypto }),
    "unsupported_kdf",
    "unsupported cryptographic algorithms fail before key derivation",
  );

  await rejectsCode(
    () => Recovery.decryptEncryptedBackup("x".repeat(Recovery.MAX_ENVELOPE_BYTES + 1), passphrase, { crypto: webcrypto }),
    "file_too_large",
    "oversized files fail before JSON parsing or key derivation",
  );

  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(JSON.stringify({
      schemaVersion: 1,
      reportType: "接班彩排家庭复盘（本地生成）",
      metrics: {},
      recommendation: {},
    }), passphrase, { crypto: webcrypto }),
    "review_export_rejected",
    "human-readable review exports are never accepted as recovery files",
  );

  await rejectsCode(
    () => Recovery.createEncryptedBackup({
      state: baseState({ mode: "demo" }),
      authority: authority(),
      passphrase,
      appBuild: "test",
    }, { crypto: webcrypto }),
    "real_household_required",
    "demo households cannot enter real backup files",
  );

  const dangerousPayload = structuredClone(roundTrip.payload);
  dangerousPayload.state.family = JSON.parse('{"caregiverName":"attacker","constructor":{"prototype":{"polluted":true}}}');
  const dangerousEncrypted = await replaceEncryptedPayload(encrypted, dangerousPayload);
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(dangerousEncrypted, passphrase, { crypto: webcrypto }),
    "dangerous_key",
    "dangerous nested keys are rejected after authenticated decryption",
  );
  assert.equal({}.polluted, undefined, "malicious recovery data cannot pollute object prototypes");

  const transientPayload = structuredClone(roundTrip.payload);
  transientPayload.state.companionSession = { caregiverToken: "secret" };
  const transientEncrypted = await replaceEncryptedPayload(encrypted, transientPayload);
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(transientEncrypted, passphrase, { crypto: webcrypto }),
    "unexpected_field",
    "unknown transient or capability-bearing state is rejected",
  );

  const unsupportedPayload = structuredClone(roundTrip.payload);
  unsupportedPayload.payloadVersion = 999;
  const unsupportedPayloadEncrypted = await replaceEncryptedPayload(encrypted, unsupportedPayload);
  await rejectsCode(
    () => Recovery.decryptEncryptedBackup(unsupportedPayloadEncrypted, passphrase, { crypto: webcrypto }),
    "unsupported_payload_version",
    "unsupported decrypted payload versions are rejected",
  );

  console.log("Recovery core passed: PBKDF2/AES-GCM round trip, transient stripping, wrong password, header/ciphertext tamper, algorithm/version, size, report, demo, malicious, and capability rejection");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
