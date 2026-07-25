// Pitch and first-use browser regression. This intentionally drives the public
// UI rather than importing app internals so mode labels, semantics, and narrow
// layouts are reviewed together with the evidence state they produce.
const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const STORAGE_KEY = "relay-rehearsal-demo-v1";
const AUTHORITY_KEY = "relay-rehearsal-recipient-authority-v1";
const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";

function assert(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

async function listenOnIsolatedPort() {
  await new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve();
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(0, "127.0.0.1");
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function stored(page) {
  return page.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
}

async function noHorizontalOverflow(page, label) {
  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }));
  assert(dimensions.document <= 0 && dimensions.body <= 0, `${label} has no horizontal overflow (${JSON.stringify(dimensions)})`);
}

(async () => {
  const baseURL = await listenOnIsolatedPort();
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    // A real household must remain honestly empty even though demo mode is one click.
    const realContext = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    const realPage = await realContext.newPage();
    await realPage.goto(baseURL, { waitUntil: "networkidle" });
    let real = await stored(realPage);
    assert(real.mode === null && real.guides.length === 0 && real.sessions.length === 0, "fresh launch has no fabricated household evidence");
    await realPage.getByRole("button", { name: /建立我的接班彩排/ }).click();
    real = await stored(realPage);
    assert(real.mode === "real" && real.guides.length === 0 && real.sessions.length === 0 && !real.family.caregiverName, "real mode starts with empty members, guidance, and outcomes");
    const realText = await realPage.locator("#app").innerText();
    assert(realText.includes("第 1 / 6 步") && !realText.includes("周岚") && !realText.includes("现场完成"), "real onboarding describes setup without demo names or success claims");
    await realContext.close();

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const browserErrors = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
    await page.goto(baseURL, { waitUntil: "networkidle" });
    await page.evaluate(([stateKey, authorityKey]) => {
      localStorage.removeItem(stateKey);
      localStorage.removeItem(authorityKey);
    }, [STORAGE_KEY, AUTHORITY_KEY]);
    await page.reload({ waitUntil: "networkidle" });

    await page.getByRole("button", { name: /体验演示家庭/ }).click();
    const judge = page.locator(".judge-demo");
    await judge.waitFor();
    assert((await judge.innerText()).includes("演示模式 · 脚本化样本 · 非真实家庭"), "one click enters an unmistakably labeled scripted demo");
    assert(await judge.getByRole("button", { name: /周岚.*主要照护者/ }).getAttribute("aria-pressed") === "true", "current role is exposed programmatically");
    assert(await judge.locator("[aria-current='step']").innerText().then((text) => text.includes("在旁观察")), "stage visualization exposes the current step");
    assert(await judge.getByRole("link").count() === 0, "intro does not imply a contact was opened");

    // Role switching must update a polite status message and remain keyboard operable.
    const substituteRole = judge.getByRole("button", { name: /林珊.*替班者/ });
    await substituteRole.focus();
    await page.keyboard.press("Enter");
    assert(await substituteRole.getAttribute("aria-pressed") === "true", "role switch works from the keyboard");
    assert((await judge.getByRole("status").innerText()).includes("不知道就留缺口"), "role switch explains the substitute boundary");
    await judge.getByRole("button", { name: /开始：先在旁看一次/ }).focus();
    await page.keyboard.press("Enter");
    assert(await page.getByRole("heading", { name: /已知低风险问题/ }).evaluate((element) => element === document.activeElement), "guided step change moves focus to the new heading");

    await judge.getByRole("button", { name: "演示这次安全匹配" }).click();
    assert((await judge.innerText()).includes("来源：周琴本人") && (await judge.innerText()).includes("现场可处理"), "known low-risk question exposes provenance and authorized use");
    await judge.getByRole("button", { name: /继续：照护者短时离开/ }).click();
    assert((await judge.locator("[aria-current='step']").innerText()).includes("短时离开"), "story visibly moves to short leave");

    await judge.getByRole("button", { name: "记录这个普通未知" }).click();
    let demo = await stored(page);
    const ordinary = demo.gaps.find((gap) => gap.id === demo.demoJourney.ordinaryGapId);
    assert(ordinary?.risk === "ordinary" && ordinary.status === "pending" && demo.guides.length === 5, "ordinary unknown remains a separate pending gap and does not become guidance");
    await judge.getByRole("button", { name: /继续：看红线怎么升级/ }).click();
    await judge.getByRole("button", { name: "查看保守升级结果" }).click();
    demo = await stored(page);
    const medical = demo.gaps.find((gap) => gap.id === demo.demoJourney.medicalGapId);
    assert(medical?.risk === "medical" && medical.status === "pending", "medical wording remains a medical pending gap");
    const caregiverCall = judge.getByRole("link", { name: /拨给周岚/ });
    const emergencyCall = judge.getByRole("link", { name: /紧急危险 · 120/ });
    assert((await caregiverCall.getAttribute("href")) === "tel:13800138000" && (await emergencyCall.getAttribute("href")) === "tel:120", "red-line screen uses real tel affordances");
    assert((await judge.innerText()).includes("不代表通话已经接通"), "contact affordance does not fabricate a connected call");

    await judge.getByRole("button", { name: /继续：看另一条无红线样本/ }).click();
    await judge.getByRole("button", { name: "载入已署名的演示回看" }).click();
    demo = await stored(page);
    const sample = demo.sessions.find((record) => record.id === demo.demoJourney.sampleSessionId);
    assert(sample?.demo === true && sample.status === "completed", "guided check-in creates only an explicitly marked demo outcome");
    assert(sample.checkIns.caregiver?.choice === "extend" && sample.checkIns.substitute?.choice === "extend" && sample.checkIns.careRecipient?.response === "answered", "check-ins remain separately attributed to all three roles");
    assert(sample.facts.urgentAlertsRaised === 0 && sample.facts.pendingGaps.length === 0, "the successful sample does not silently absorb the separate red-line demonstration");
    await judge.getByRole("button", { name: "让规则给出下一档" }).click();
    assert((await page.getByRole("heading", { name: "建议：安静接班" }).innerText()) === "建议：安静接班", "evidence produces the next-stage recommendation");
    const recommendationText = await judge.locator(".judge-recommendation").innerText();
    assert(recommendationText.includes("照护者与替班者") && recommendationText.includes("未记录未解决的紧急/医疗事件"), "recommendation visibly explains its conservative evidence");
    await judge.getByRole("button", { name: /看看安静离班保护什么/ }).click();
    assert((await judge.locator("[aria-current='step']").innerText()).includes("安静离班"), "story visibly reaches quiet off-duty time");
    assert((await judge.innerText()).includes("尚未真实开始") && (await judge.innerText()).includes("不能保证提醒"), "quiet preview avoids claiming a real or guaranteed outcome");

    const bodyText = await page.locator("body").innerText();
    assert(!/(100%安全|绝对安全|保证放心|保证不会打断|通话已接通|已经康复)/.test(bodyText), "visible demo contains no unsupported success or safety claim");
    await noHorizontalOverflow(page, "desktop judge story");
    await page.setViewportSize({ width: 390, height: 844 });
    await noHorizontalOverflow(page, "390px judge story");
    await page.setViewportSize({ width: 320, height: 720 });
    await noHorizontalOverflow(page, "320px judge story");

    // Long Chinese labels and a bottom sheet stay usable at the smallest target.
    await page.evaluate((key) => {
      const value = JSON.parse(localStorage.getItem(key));
      value.family.caregiverName = "周岚（需要在非常疲惫的时候仍能一眼确认身份的主要照护者）";
      value.family.relayName = "林珊（今天负责低风险陪伴与记录的替班者）";
      value.family.recipientName = "周琴（可随时撤回参与并自行选择是否回答的被照护者）";
      value.family.restGoal.title = "去楼下沿着河边安静散步并在长椅上坐一会儿，不处理普通家庭消息";
      localStorage.setItem(key, JSON.stringify(value));
    }, STORAGE_KEY);
    await page.reload({ waitUntil: "networkidle" });
    await noHorizontalOverflow(page, "320px long Chinese copy");
    await page.locator("[data-action='start-rehearsal']").first().click();
    const dialog = page.locator("[role='dialog']");
    assert(await dialog.getAttribute("aria-labelledby") === "modal-title", "mobile sheet has a programmatic accessible name");
    assert(await dialog.getByRole("button", { name: "关闭" }).isVisible(), "mobile sheet keeps a visible stop/close action");
    await page.keyboard.press("Shift+Tab");
    assert(await page.evaluate(() => Boolean(document.activeElement?.closest("[role='dialog']"))), "modal keyboard focus remains inside the sheet");
    await noHorizontalOverflow(page, "320px long-copy mobile sheet");
    await dialog.getByRole("button", { name: "关闭" }).click();

    // Restart is one click, removes only scripted journey mutations, and returns focus.
    await page.locator(".mode-control").click();
    demo = await stored(page);
    assert(demo.mode === "demo" && demo.demoJourney.step === 0 && demo.gaps.length === 0, "persistent demo control restarts the scripted gaps");
    assert(!demo.sessions.some((record) => record.id === "judge-demo-short-leave-20260725") && demo.sessions.length === 4, "restart restores the original demo records");
    assert(await page.getByRole("heading", { name: /2–3 分钟看懂/ }).evaluate((element) => element === document.activeElement), "restart returns keyboard focus to the guided start");
    assert(browserErrors.length === 0, browserErrors.join("\n"));

    await context.close();
    console.log("Judge E2E passed: honest real launch, guided demo story, role/consent semantics, evidence recommendation, reset, long copy, and 320/390/desktop layouts");
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  try { server.closeAllConnections?.(); } catch { /* best-effort cleanup */ }
  try { server.close(); } catch { /* server may not have started */ }
  console.error(error.stack || error);
  process.exit(1);
});
