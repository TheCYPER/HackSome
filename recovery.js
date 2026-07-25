(function initRecovery(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.RelayRecovery = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function recoveryFactory() {
  "use strict";

  const FORMAT = "relay-rehearsal-encrypted-backup";
  const ENVELOPE_VERSION = 2;
  const PAYLOAD_VERSION = 2;
  const KDF_ITERATIONS = 310_000;
  const MAX_ENVELOPE_BYTES = 2_000_000;
  const MAX_PAYLOAD_BYTES = 1_500_000;
  const MIN_PASSPHRASE_LENGTH = 12;
  const MAX_PASSPHRASE_LENGTH = 256;
  const MAX_TREE_DEPTH = 24;
  const MAX_TREE_NODES = 50_000;
  const MAX_STRING_LENGTH = 20_000;
  const MAX_ARRAY_LENGTH = 5_000;
  const DANGEROUS_KEYS = new Set(["__proto__", "prototype", "constructor"]);
  const TRANSIENT_CAPABILITY_KEYS = new Set([
    "authorization", "auth", "bearer", "capability", "caregivertoken",
    "credential", "invite", "invitation", "invitecode", "invitetoken",
    "joincode", "pairingcode", "participantid", "roomid", "roomkey",
    "secret", "substitutetoken",
  ]);
  const STATE_KEYS = Object.freeze([
    "schemaVersion", "mode", "meta", "onboarding", "guideFilter",
    "stageOneCompleted", "rehearsalCompleted", "quietInbox",
    "activeRest", "activeRehearsal", "sessions", "recommendationOverride",
    "demoJourney", "appliedRemoteSessionIds", "debriefs", "gaps",
    "revokedGuideIds", "confirmations", "recipientConsent", "family",
    "activity", "guides",
  ]);
  const ARRAY_STATE_KEYS = Object.freeze([
    "sessions", "appliedRemoteSessionIds", "debriefs", "gaps",
    "revokedGuideIds", "confirmations", "activity", "guides",
  ]);

  class RecoveryError extends Error {
    constructor(code, message) {
      super(message);
      this.name = "RecoveryError";
      this.code = code;
    }
  }

  function fail(code, message) {
    throw new RecoveryError(code, message);
  }

  function isPlainObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function assertExactKeys(value, allowed, required, label) {
    if (!isPlainObject(value)) fail("invalid_structure", `${label}必须是对象`);
    const allowedSet = new Set(allowed);
    for (const key of Object.keys(value)) {
      if (DANGEROUS_KEYS.has(key) || !allowedSet.has(key)) fail("unexpected_field", `${label}包含不支持的字段`);
    }
    for (const key of required) if (!Object.prototype.hasOwnProperty.call(value, key)) fail("missing_field", `${label}缺少必要字段`);
  }

  function normalizedFieldName(value) {
    return String(value || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  }

  function isTransientCapabilityKey(key) {
    const normalized = normalizedFieldName(key);
    return TRANSIENT_CAPABILITY_KEYS.has(normalized)
      || normalized.endsWith("token")
      || normalized.endsWith("secret")
      || normalized.endsWith("credential")
      || normalized.endsWith("capability");
  }

  function stripTransientCapabilities(value) {
    if (Array.isArray(value)) return value.map(stripTransientCapabilities);
    if (!isPlainObject(value)) return structuredClone(value);
    const stripped = {};
    for (const [key, item] of Object.entries(value)) {
      if (isTransientCapabilityKey(key)) continue;
      stripped[key] = stripTransientCapabilities(item);
    }
    return stripped;
  }

  function validateValueTree(value, { rejectCapabilities = false } = {}) {
    let nodes = 0;
    const walk = (current, depth) => {
      nodes += 1;
      if (nodes > MAX_TREE_NODES) fail("payload_too_complex", "备份内容过于复杂");
      if (depth > MAX_TREE_DEPTH) fail("payload_too_deep", "备份内容嵌套过深");
      if (current == null || typeof current === "boolean") return;
      if (typeof current === "number") {
        if (!Number.isFinite(current)) fail("invalid_number", "备份包含无效数字");
        return;
      }
      if (typeof current === "string") {
        if (current.length > MAX_STRING_LENGTH) fail("string_too_long", "备份包含超长文字");
        return;
      }
      if (Array.isArray(current)) {
        if (current.length > MAX_ARRAY_LENGTH) fail("array_too_long", "备份包含过多记录");
        current.forEach((item) => walk(item, depth + 1));
        return;
      }
      if (!isPlainObject(current)) fail("invalid_value", "备份包含不支持的数据类型");
      for (const [key, item] of Object.entries(current)) {
        if (DANGEROUS_KEYS.has(key)) fail("dangerous_key", "备份包含危险字段");
        if (rejectCapabilities && isTransientCapabilityKey(key)) fail("transient_capability_present", "备份包含远端邀请或凭证字段");
        walk(item, depth + 1);
      }
    };
    walk(value, 0);
  }

  function utf8Bytes(value) {
    return new TextEncoder().encode(String(value));
  }

  function byteLength(value) {
    return utf8Bytes(value).byteLength;
  }

  function toBase64(bytes) {
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  function fromBase64(value, maxBytes, label) {
    if (typeof value !== "string" || !value || value.length % 4 !== 0 || !/^[A-Za-z0-9+/]+={0,2}$/.test(value)) {
      fail("invalid_base64", `${label}编码无效`);
    }
    const estimated = Math.floor(value.length * 3 / 4);
    if (estimated > maxBytes + 2) fail("oversized_field", `${label}超过大小限制`);
    let binary;
    try {
      binary = atob(value);
    } catch {
      fail("invalid_base64", `${label}编码无效`);
    }
    if (binary.length > maxBytes) fail("oversized_field", `${label}超过大小限制`);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return bytes;
  }

  function validTimestamp(value) {
    if (typeof value !== "string" || value.length > 40) return false;
    const timestamp = new Date(value);
    return !Number.isNaN(timestamp.getTime());
  }

  function normalizePassphrase(value) {
    if (typeof value !== "string") fail("passphrase_required", "请输入备份密码");
    const normalized = value.normalize("NFC");
    const length = [...normalized].length;
    if (length < MIN_PASSPHRASE_LENGTH) fail("passphrase_too_short", `备份密码至少需要 ${MIN_PASSPHRASE_LENGTH} 个字符`);
    if (length > MAX_PASSPHRASE_LENGTH) fail("passphrase_too_long", "备份密码过长");
    return normalized;
  }

  function cryptoApi(options = {}) {
    const provider = options.crypto || (typeof crypto !== "undefined" ? crypto : null);
    if (!provider?.subtle || typeof provider.getRandomValues !== "function") {
      fail("crypto_unavailable", "当前浏览器不支持本地加密备份");
    }
    return provider;
  }

  function envelopeAad(envelope) {
    return utf8Bytes(JSON.stringify([
      envelope.format,
      envelope.version,
      envelope.createdAt,
      envelope.kdf.name,
      envelope.kdf.hash,
      envelope.kdf.iterations,
      envelope.kdf.salt,
      envelope.cipher.name,
      envelope.cipher.iv,
    ]));
  }

  async function deriveEncryptionKey(passphrase, salt, usage, options = {}) {
    const provider = cryptoApi(options);
    const baseKey = await provider.subtle.importKey(
      "raw",
      utf8Bytes(normalizePassphrase(passphrase)),
      "PBKDF2",
      false,
      ["deriveKey"],
    );
    return provider.subtle.deriveKey(
      { name: "PBKDF2", hash: "SHA-256", salt, iterations: KDF_ITERATIONS },
      baseKey,
      { name: "AES-GCM", length: 256 },
      false,
      [usage],
    );
  }

  function sanitizeBackupState(sourceState) {
    validateValueTree(sourceState);
    if (!isPlainObject(sourceState) || sourceState.mode !== "real") {
      fail("real_household_required", "只能备份真实家庭，演示家庭不会进入备份");
    }
    const clean = {};
    for (const key of STATE_KEYS) {
      if (Object.prototype.hasOwnProperty.call(sourceState, key)) clean[key] = stripTransientCapabilities(sourceState[key]);
    }
    clean.mode = "real";
    clean.activeRest = null;
    clean.activeRehearsal = null;
    clean.appliedRemoteSessionIds = [];
    clean.demoJourney = null;
    clean.sessions = (Array.isArray(clean.sessions) ? clean.sessions : []).map((record) => {
      if (!isPlainObject(record) || record.status !== "active") return record;
      return { ...record, status: "interrupted", facts: null };
    });
    clean.meta = isPlainObject(clean.meta) ? clean.meta : {};
    delete clean.meta.updatedAt;
    delete clean.meta.lastBackupAt;
    delete clean.meta.backupReminderSnoozedUntil;
    delete clean.meta.lastRecovery;
    validateRecoveryState(clean);
    return clean;
  }

  function normalizeAuthority(source) {
    assertExactKeys(
      source,
      ["schemaVersion", "status", "revision", "changedAt", "grantedAt", "withdrawnAt"],
      ["status", "revision"],
      "授权记录",
    );
    if (!["granted", "withdrawn"].includes(source.status)) fail("invalid_authority", "授权状态无效");
    const revision = Number(source.revision);
    if (!Number.isInteger(revision) || revision < 1 || revision > Number.MAX_SAFE_INTEGER) fail("invalid_authority", "授权版本无效");
    for (const field of ["changedAt", "grantedAt", "withdrawnAt"]) {
      if (source[field] != null && !validTimestamp(source[field])) fail("invalid_authority", "授权时间无效");
    }
    if (source.changedAt == null && source.grantedAt == null && source.withdrawnAt == null) fail("invalid_authority", "授权记录缺少变更时间");
    return {
      schemaVersion: 1,
      status: source.status,
      revision,
      changedAt: source.changedAt || source.withdrawnAt || source.grantedAt || null,
      grantedAt: source.grantedAt || null,
      withdrawnAt: source.withdrawnAt || null,
    };
  }

  function validateRecoveryState(candidate) {
    assertExactKeys(candidate, STATE_KEYS, ["schemaVersion", "mode", "family", "recipientConsent"], "家庭状态");
    validateValueTree(candidate, { rejectCapabilities: true });
    if (candidate.mode !== "real") fail("demo_backup_rejected", "演示家庭不能作为恢复来源");
    if (!Number.isInteger(Number(candidate.schemaVersion)) || Number(candidate.schemaVersion) < 1 || Number(candidate.schemaVersion) > 100) {
      fail("unsupported_state_version", "家庭数据版本不受支持");
    }
    if (!isPlainObject(candidate.family) || !isPlainObject(candidate.recipientConsent)) fail("invalid_state", "家庭或授权数据无效");
    for (const key of ARRAY_STATE_KEYS) {
      if (Object.prototype.hasOwnProperty.call(candidate, key) && !Array.isArray(candidate[key])) fail("invalid_state", `${key} 必须是列表`);
    }
    if (candidate.activeRest != null || candidate.activeRehearsal != null) fail("transient_state_present", "备份包含不能恢复的活动会话");
    if ((candidate.sessions || []).some((record) => record?.status === "active")) fail("transient_state_present", "备份包含进行中的记录");
    return candidate;
  }

  function validatePayload(candidate) {
    assertExactKeys(
      candidate,
      ["payloadVersion", "exportedAt", "state", "authority"],
      ["payloadVersion", "exportedAt", "state", "authority"],
      "恢复内容",
    );
    if (candidate.payloadVersion !== PAYLOAD_VERSION) fail("unsupported_payload_version", "恢复内容版本不受支持");
    if (!validTimestamp(candidate.exportedAt)) fail("invalid_timestamp", "恢复内容时间无效");
    validateRecoveryState(candidate.state);
    const authority = normalizeAuthority(candidate.authority);
    const consent = candidate.state.recipientConsent;
    assertExactKeys(consent, ["status", "revision", "grantedAt", "withdrawnAt"], ["status", "revision"], "家庭授权状态");
    for (const field of ["grantedAt", "withdrawnAt"]) {
      if (consent[field] != null && !validTimestamp(consent[field])) fail("invalid_authority", "家庭授权时间无效");
    }
    if (!["granted", "withdrawn"].includes(consent.status) || Number(consent.revision) !== authority.revision || consent.status !== authority.status) {
      fail("authority_mismatch", "家庭状态与授权记录不一致");
    }
    return { ...candidate, authority };
  }

  function validateEnvelope(candidate) {
    if (isPlainObject(candidate) && (candidate.reportType || candidate.metrics || candidate.recommendation) && candidate.format !== FORMAT) {
      fail("review_export_rejected", "这是家庭复盘，不是加密恢复备份");
    }
    assertExactKeys(
      candidate,
      ["format", "version", "createdAt", "kdf", "cipher", "ciphertext"],
      ["format", "version", "createdAt", "kdf", "cipher", "ciphertext"],
      "备份信封",
    );
    if (candidate.format !== FORMAT) fail("not_recovery_backup", "文件不是接班彩排加密恢复备份");
    if (candidate.version !== ENVELOPE_VERSION) fail("unsupported_envelope_version", "备份格式版本不受支持");
    if (!validTimestamp(candidate.createdAt)) fail("invalid_timestamp", "备份创建时间无效");
    assertExactKeys(candidate.kdf, ["name", "hash", "iterations", "salt"], ["name", "hash", "iterations", "salt"], "密钥参数");
    if (candidate.kdf.name !== "PBKDF2" || candidate.kdf.hash !== "SHA-256" || candidate.kdf.iterations !== KDF_ITERATIONS) {
      fail("unsupported_kdf", "备份密钥算法不受支持");
    }
    assertExactKeys(candidate.cipher, ["name", "iv"], ["name", "iv"], "加密参数");
    if (candidate.cipher.name !== "AES-GCM") fail("unsupported_cipher", "备份加密算法不受支持");
    const salt = fromBase64(candidate.kdf.salt, 16, "盐值");
    const iv = fromBase64(candidate.cipher.iv, 12, "随机向量");
    if (salt.length !== 16 || iv.length !== 12) fail("invalid_crypto_parameters", "备份加密参数长度无效");
    fromBase64(candidate.ciphertext, MAX_PAYLOAD_BYTES + 32, "密文");
    return candidate;
  }

  function parseEnvelopeText(text) {
    if (typeof text !== "string") fail("invalid_file", "备份文件必须是文字格式");
    if (byteLength(text) > MAX_ENVELOPE_BYTES) fail("file_too_large", "备份文件超过 2 MB 限制");
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      fail("invalid_json", "备份文件不是有效 JSON");
    }
    return validateEnvelope(parsed);
  }

  async function createEncryptedBackup({ state, authority, passphrase, now = new Date().toISOString() }, options = {}) {
    if (!validTimestamp(now)) fail("invalid_timestamp", "备份创建时间无效");
    const provider = cryptoApi(options);
    const cleanState = sanitizeBackupState(state);
    const cleanAuthority = normalizeAuthority(authority);
    if (cleanState.recipientConsent.status !== cleanAuthority.status || Number(cleanState.recipientConsent.revision) !== cleanAuthority.revision) {
      fail("authority_mismatch", "备份前的授权状态不一致");
    }
    const payload = validatePayload({
      payloadVersion: PAYLOAD_VERSION,
      exportedAt: now,
      state: cleanState,
      authority: cleanAuthority,
    });
    const plaintext = utf8Bytes(JSON.stringify(payload));
    if (plaintext.byteLength > MAX_PAYLOAD_BYTES) fail("payload_too_large", "家庭数据超过可备份大小");
    const salt = provider.getRandomValues(new Uint8Array(16));
    const iv = provider.getRandomValues(new Uint8Array(12));
    const envelope = {
      format: FORMAT,
      version: ENVELOPE_VERSION,
      createdAt: now,
      kdf: { name: "PBKDF2", hash: "SHA-256", iterations: KDF_ITERATIONS, salt: toBase64(salt) },
      cipher: { name: "AES-GCM", iv: toBase64(iv) },
      ciphertext: "",
    };
    const key = await deriveEncryptionKey(passphrase, salt, "encrypt", options);
    const encrypted = await provider.subtle.encrypt(
      { name: "AES-GCM", iv, additionalData: envelopeAad(envelope), tagLength: 128 },
      key,
      plaintext,
    );
    envelope.ciphertext = toBase64(new Uint8Array(encrypted));
    return JSON.stringify(envelope, null, 2);
  }

  async function decryptEncryptedBackup(text, passphrase, options = {}) {
    const provider = cryptoApi(options);
    const envelope = parseEnvelopeText(text);
    const salt = fromBase64(envelope.kdf.salt, 16, "盐值");
    const iv = fromBase64(envelope.cipher.iv, 12, "随机向量");
    const ciphertext = fromBase64(envelope.ciphertext, MAX_PAYLOAD_BYTES + 32, "密文");
    const key = await deriveEncryptionKey(passphrase, salt, "decrypt", options);
    let decrypted;
    try {
      decrypted = await provider.subtle.decrypt(
        { name: "AES-GCM", iv, additionalData: envelopeAad(envelope), tagLength: 128 },
        key,
        ciphertext,
      );
    } catch {
      fail("authentication_failed", "密码错误，或备份已被篡改");
    }
    if (decrypted.byteLength > MAX_PAYLOAD_BYTES) fail("payload_too_large", "恢复内容超过大小限制");
    let payload;
    try {
      payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decrypted));
    } catch {
      fail("invalid_payload", "解密后的恢复内容无效");
    }
    return {
      payload: validatePayload(payload),
      envelope: {
        format: envelope.format,
        version: envelope.version,
        createdAt: envelope.createdAt,
      },
    };
  }

  return Object.freeze({
    FORMAT,
    ENVELOPE_VERSION,
    PAYLOAD_VERSION,
    KDF_ITERATIONS,
    MAX_ENVELOPE_BYTES,
    MAX_PAYLOAD_BYTES,
    MIN_PASSPHRASE_LENGTH,
    RecoveryError,
    isTransientCapabilityKey,
    stripTransientCapabilities,
    sanitizeBackupState,
    validateRecoveryState,
    parseEnvelopeText,
    createEncryptedBackup,
    decryptEncryptedBackup,
  });
});
