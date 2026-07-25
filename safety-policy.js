"use strict";

// Relay Safety Policy 2026-07-25.1
//
// This is the only medical/high-risk text classifier in the product. It is a
// deliberately conservative prototype guard, not clinical triage. Both browser
// surfaces and the room service load this exact module and send VERSION on every
// room API request so a stale client cannot keep using a changed policy.
(function exposeSafetyPolicy(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.RelaySafetyPolicy = api;
})(typeof globalThis === "object" ? globalThis : this, () => {
  const VERSION = "2026-07-25.1";
  const ASSET_VERSION = "20260725-policy-v1";
  const HEADER = "x-relay-safety-policy";
  const PROFESSIONAL_SOURCE_ID = "professional-community-nurse";
  const IMMEDIATE_LEVEL = "now";
  const IMMEDIATE_RULE = "立即联系";
  const PROFESSIONAL_REFERENCES = Object.freeze({
    "demo-fall-immediate-v1": Object.freeze({
      professionalReferenceId: "demo-fall-immediate-v1",
      id: "fall",
      version: 1,
      title: "发生跌倒",
      summary: "立即联系主要照护者；有紧急危险时使用本房间显示的当地紧急服务号码。",
      actorId: PROFESSIONAL_SOURCE_ID,
      level: IMMEDIATE_LEVEL,
      rule: IMMEDIATE_RULE,
    }),
  });

  // NFKC closes full-width compatibility variants. Removing all Unicode
  // whitespace, punctuation, symbols, and formatting marks closes separators
  // inserted inside a phrase (including zero-width formatting characters).
  function canonicalizeText(value) {
    return String(value ?? "")
      .normalize("NFKC")
      .toLocaleLowerCase("zh-CN")
      .replace(/[\p{White_Space}\p{Punctuation}\p{Symbol}\p{Cf}]+/gu, "");
  }

  const RULES = Object.freeze([
    ["chest", /胸痛|胸疼|胸部疼|胸闷|胸口不适|胸部不适|心前区不适|胸口不舒服|胸部不舒服|chest(?:pain|ache|tightness|pressure|discomfort)|paininthechest/],
    ["chest-composite", /(?:胸(?:口|部|前|腔)?|心口|心前区).{0,6}(?:发紧|发沉|紧缩|紧绷|痛|疼|闷|压迫|不适|不舒服|不对劲|难受|堵|憋|沉重|烧灼)|(?:发紧|发沉|紧缩|紧绷|痛|疼|闷|压迫|不适|难受).{0,4}(?:胸(?:口|部|前|腔)?|心口|心前区)|chest.{0,14}(?:pain|ache|tight|pressure|heavy|discomfort|squeez|constrict|feels?off|notright)|(?:pain|tight|tightness|pressure|heaviness).{0,8}(?:inthe)?chest/],
    ["breathing", /呼吸困难|呼吸急促|呼吸微弱|呼吸异常|呼吸变慢|呼吸变快|喘不上气|喘不过气|喘得厉害|无法呼吸|不能呼吸|憋气|气短|shortnessofbreath|shortofbreath|cannotbreathe|cantbreathe|difficultybreathing|troublebreathing|breathing(?:slow|fast|weak|changed|abnormal)/],
    ["breathing-composite", /(?:呼吸|气息).{0,7}(?:不畅|不顺|不利|不正常|不对劲|费力|吃力|困难|急促|急|变快|加快|变慢|放慢|缓慢|微弱|很弱|浅|受阻|异常|暂停|停止|有问题)|喘气.{0,4}(?:费劲|费力|吃力|困难|不畅|不顺)|(?:喘|透).{0,5}(?:不过气|不上气|不动|不畅|厉害)|气.{0,4}(?:不够|不顺|上不来|吸不进|接不上|喘不过来)|breath(?:ing)?.{0,14}(?:labored|shallow|weak|slow|fast|rapid|difficult|obstructed|abnormal|stopped|uneven|notright|feelsoff|hard)|(?:cannot|cant|unableto).{0,8}(?:catch)?(?:her|his|their|the)?breath|breathless/],
    ["circulation", /脉搏(?:很慢|过慢|偏慢|很快|过快|偏快|异常|变慢|变快|微弱|不规则|[<>]?\d+)|心率(?:很慢|过慢|偏慢|很快|过快|偏快|异常|变慢|变快|不齐|不规则|[<>]?\d+)|心跳(?:很慢|过慢|偏慢|很快|过快|偏快|异常|变慢|变快|微弱|不齐|不规则)|pulse(?:is)?(?:very)?(?:slow|fast|weak|irregular|abnormal|changed|[<>]?\d+)|heartrate(?:is)?(?:very)?(?:slow|fast|low|high|irregular|abnormal|changed|[<>]?\d+)|slowpulse|fastpulse|slowheartrate|fastheartrate|bradycardia|tachycardia/],
    ["circulation-composite", /(?:脉搏|心率|心跳).{0,8}(?:缓慢|迟缓|缓|慢|快|急促|加速|加快|过速|弱|低|高|偏低|偏高|微弱|摸不到|不稳|紊乱|乱|不齐|不规则|异常|变化|改变|骤升|骤降|停止|[<>]?\d+)|(?:缓慢|迟缓|微弱|快速|过快|异常).{0,4}(?:脉搏|心率|心跳)|pulse.{0,14}(?:slow|sluggish|fast|rapid|racing|weak|faint|low|high|irregular|abnormal|chang|drop|fell|rise|rose)|heartrate.{0,14}(?:slow|sluggish|fast|rapid|racing|weak|low|high|irregular|abnormal|chang|drop|fell|rise|rose|elevat)|heart(?:beat|is).{0,10}(?:slow|fast|rapid|racing|weak|irregular|abnormal)|(?:slow|sluggish|fast|rapid|racing|weak|irregular|abnormal).{0,8}(?:pulse|heartbeat|heartrate)/],
    ["measurements", /血压|血糖|血氧|氧饱和度|体温(?:升高|降低|异常|变化|[<>]?\d+)|bloodpressure|bloodsugar|bloodglucose|bloodoxygen|oxygensaturation|oxygenlevel|spo2|temperature(?:is)?(?:high|low|abnormal|changed|[<>]?\d+)|vitalsigns?|vitalreading/],
    ["appearance", /脸色发白|面色苍白|脸色苍白|嘴唇发紫|口唇发紫|皮肤发紫|发绀|pale|pallor|cyanosis|bluishlips|bluelips/],
    ["consciousness", /失去意识|意识不清|意识模糊|意识改变|神志不清|昏迷|无法唤醒|不能唤醒|叫不醒|反应迟钝|晕倒|晕厥|昏厥|faint(?:ed|ing)?|passedout|unconscious|alteredconsciousness|confusedanddrowsy|cannotwake|cantwake|unresponsive/],
    ["seizure", /抽搐|惊厥|癫痫发作|seizure|convulsion|convulsing/],
    ["injury", /跌倒|摔倒|滑倒|坠落|跌落|外伤|受伤|碰伤|割伤|烫伤|骨折|扭伤|创伤|伤口|出血|流血不止|fall(?:down|en|ing)|fell(?:down)?|tookafall|injur(?:y|ed)|wound|fracture|sprain|trauma|bleeding|bloodloss/],
    ["acute-symptom", /高烧|低烧|发烧|发热|过敏|呕吐|剧烈头痛|头晕|眩晕|偏瘫|口齿不清|突然无力|一侧无力|麻木|腹痛|疼痛|恶心|严重腹泻|持续咳嗽|咳嗽不止|吞咽困难|肿胀|水肿|fever|highfever|lowfever|allergy|allergic|anaphylaxis|vomit(?:ing|ed)?|severeheadache|dizz(?:y|iness)|vertigo|suddenweakness|numbness|abdominalpain|severepain|haspain|inpain|painin|painful|nausea|diarrhea|swelling|persistentcough|coughing/],
    ["medication", /药|剂量|漏服|补服|加倍|双倍|两倍|翻倍|打针|注射|medication|medicine|dosage|dose(?:change|increase|decrease|adjustment|doubled?|missed|extra)|double(?:the)?dose|skip(?:the)?dose|stoptaking|pill|injection|insulin/],
    ["urgent-care", /急救|急诊|送医|紧急送医|呼叫救护车|叫救护车|拨打120|拨打911|自行搬动|搬运患者|扶(?:她|他|患者|病人)起来|urgentcare|emergencyroom|emergencyservices|call(?:an)?ambulance|call(?:120|911)|cpr|firstaid|lift(?:her|him|thepatient|theperson)|move(?:her|him|thepatient|theperson)/],
    ["medical-local-downgrade", /(?:胸|心口|心前区|呼吸|喘气|气息|脉搏|心率|心跳|血压|血糖|血氧|意识|药).{0,90}(?:不需要联系|不用联系|无需联系|现场可处理|在家处理|坐下观察|继续观察|先观察|先等等)|(?:不需要联系|不用联系|无需联系|现场可处理|在家处理|坐下观察|继续观察|先观察|先等等).{0,90}(?:胸|心口|心前区|呼吸|喘气|气息|脉搏|心率|心跳|血压|血糖|血氧|意识|药)|(?:chest|breath|breathing|pulse|heartrate|heartbeat|bloodpressure|bloodglucose|oxygen).{0,120}(?:noneedtocall|donotcall|dontcall|handlelocally|waitandwatch|observeathome)/],
    ["missing-person", /走失|找不到人|失踪|wandering|missingperson/],
  ].map(([id, expression]) => Object.freeze({ id, expression })));

  function classifyText(value) {
    const canonical = canonicalizeText(value);
    const ruleIds = RULES.filter((rule) => rule.expression.test(canonical)).map((rule) => rule.id);
    return Object.freeze({
      policyVersion: VERSION,
      highRisk: ruleIds.length > 0,
      risk: ruleIds.length ? "medical" : "ordinary",
      ruleIds: Object.freeze(ruleIds),
      canonical,
    });
  }

  // Concatenating canonicalized fields without a separator is intentional: a
  // phrase split as title="胸部" and instruction="不适" must still be caught.
  function classifyFields(fields) {
    const values = Array.isArray(fields) ? fields : Object.values(fields || {});
    return classifyText(values.map(canonicalizeText).join(""));
  }

  function isMedicalOrHighRisk(value) {
    return classifyText(value).highRisk;
  }

  function isRecognizedActorId(value) {
    return ["caregiver", "recipient", "relay", PROFESSIONAL_SOURCE_ID].includes(String(value || ""));
  }

  function isProfessionalSourceId(value) {
    return value === PROFESSIONAL_SOURCE_ID;
  }

  function canonicalSourceLabel(actorId, family = {}) {
    if (actorId === "caregiver") return String(family.caregiverName || "主要照护者");
    if (actorId === "recipient") return `${String(family.recipientName || "被照护者")}本人`;
    if (actorId === "relay") return String(family.relayName || "替班者");
    if (actorId === PROFESSIONAL_SOURCE_ID) return "已有专业人员指示";
    return "来源待复核";
  }

  function getProfessionalReference(referenceId) {
    return PROFESSIONAL_REFERENCES[String(referenceId || "")] || null;
  }

  function matchesProfessionalReference(value) {
    if (!value || typeof value !== "object") return false;
    const reference = getProfessionalReference(value.professionalReferenceId);
    if (!reference) return false;
    const actorId = value.actorId ?? value.provenance?.actorId;
    return (
      String(value.id || "") === reference.id
      && Number(value.version) === reference.version
      && String(value.title || "") === reference.title
      && String(value.summary || "") === reference.summary
      && actorId === reference.actorId
      && value.level === reference.level
      && value.rule === reference.rule
    );
  }

  function isImmediateReference(value) {
    if (!matchesProfessionalReference(value)) return false;
    const classification = classifyFields([value.title, value.summary, value.instruction]);
    return classification.highRisk && value.level === IMMEDIATE_LEVEL && value.rule === IMMEDIATE_RULE;
  }

  return Object.freeze({
    VERSION,
    ASSET_VERSION,
    HEADER,
    PROFESSIONAL_SOURCE_ID,
    IMMEDIATE_LEVEL,
    IMMEDIATE_RULE,
    canonicalizeText,
    classifyText,
    classifyFields,
    isMedicalOrHighRisk,
    isRecognizedActorId,
    isProfessionalSourceId,
    canonicalSourceLabel,
    getProfessionalReference,
    matchesProfessionalReference,
    isImmediateReference,
  });
});
