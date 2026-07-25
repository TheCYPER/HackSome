// Fast browser gate for independent review. The exhaustive multi-device audit
// remains available as `npm run test:e2e:full`.
const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const STORAGE_KEY = "relay-rehearsal-demo-v1";
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

async function ask(page, question) {
  await page.getByRole("button", { name: "语音提出问题" }).click();
  await page.locator("#question-input").evaluate((input, value) => { input.value = value; input.dispatchEvent(new Event("input", { bubbles: true })); }, question);
  await page.getByRole("button", { name: "查找已确认指导" }).click();
}

(async () => {
  const baseURL = await listenOnIsolatedPort();
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    const context = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    const page = await context.newPage();
    page.setDefaultTimeout(7000);
    const browserErrors = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(message.text());
    });

    await page.goto(baseURL, { waitUntil: "networkidle" });
    assert(await page.getByRole("heading", { name: "先选一条适合现在的路" }).isVisible(), "fresh launch offers an explicit mode choice");
    let state = await stored(page);
    assert(state.mode === null && state.guides.length === 0, "fresh launch contains no demo family claims");

    await page.getByRole("button", { name: /体验演示家庭/ }).click();
    await page.getByText("休息有没有发生").waitFor();
    assert(await page.getByRole("button", { name: /全部 5 条/ }).isVisible(), "demo family exposes its five source-bound guides");

    await page.locator("[data-action='start-rehearsal']").first().click();
    const setup = page.locator("#rehearsal-setup-form");
    const checks = setup.locator("input[type='checkbox']");
    assert(await checks.count() === 3, "each rehearsal requires three current confirmations");
    assert(await setup.getByRole("button", { name: /三方现在确认，开始/ }).isDisabled(), "rehearsal cannot start before confirmation");
    for (let index = 0; index < 3; index += 1) await checks.nth(index).check();
    await setup.getByRole("button", { name: /三方现在确认，开始/ }).click();
    await page.getByText("真实彩排进行中").waitFor();

    const question = "她一直盯着窗外，反复整理袖口";
    await ask(page, question);
    await page.getByRole("heading", { name: "没有找到已确认指导" }).waitFor();
    await page.getByText(/已记录为待确认情境 · 第 1 次/).waitFor();
    await page.getByRole("button", { name: "关闭" }).click();

    await ask(page, ` ${question}。 `);
    await page.getByText(/已记录为待确认情境 · 第 2 次/).waitFor();
    state = await stored(page);
    assert(state.gaps.filter((gap) => gap.status === "pending").length === 1, "normalized repeats update one durable pending gap");

    await page.getByRole("button", { name: "查看已记录缺口" }).click();
    await page.locator("#gap-form").evaluate((form) => {
      form.elements.answer.value = "先询问是否需要安静坐一会儿，并在结束后告诉主要照护者。";
      form.elements.answer.dispatchEvent(new Event("input", { bubbles: true }));
      form.elements.sourceId.value = "caregiver";
      form.elements.sourceId.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const gapFormValidity = await page.locator("#gap-form").evaluate((form) => ({
      valid: form.checkValidity(),
      invalid: [...form.elements].filter((field) => typeof field.checkValidity === "function" && !field.checkValidity()).map((field) => ({ id: field.id, value: field.value, message: field.validationMessage })),
    }));
    assert(gapFormValidity.valid, `ordinary gap form is valid before confirmation (${JSON.stringify(gapFormValidity.invalid)})`);
    await page.locator("#gap-form").evaluate((form) => form.requestSubmit());
    await page.waitForTimeout(100);
    if (await page.locator("#gap-form").count()) {
      const snapshot = await stored(page);
      const toastText = await page.locator("#toast-root").innerText();
      throw new Error(`Gap confirmation stayed open: ${browserErrors.join(" | ") || "no page error"}; ${toastText || "no toast"}; ${JSON.stringify(snapshot.gaps)}`);
    }
    state = await stored(page);
    const matchingGaps = state.gaps.filter((gap) => gap.normalizedQuery.includes("整理袖口"));
    assert(matchingGaps.length === 1 && matchingGaps[0].status === "resolved", "gap resolution is monotonic and leaves one auditable record");
    assert(state.guides.some((guide) => guide.fromGap === matchingGaps[0].id && guide.provenance.actorId === "caregiver"), "resolved gap becomes guidance only with explicit provenance");

    await page.locator(".top-avatar").click();
    await page.getByRole("button", { name: "撤回本人内容与参与" }).click();
    await page.getByRole("button", { name: "确认撤回" }).click();
    await page.locator("#modal-root").waitFor({ state: "hidden" });
    state = await stored(page);
    assert(state.recipientConsent.status === "withdrawn", "withdrawal persists immediately");
    assert(state.guides.every((guide) => guide.provenance.actorId !== "recipient"), "withdrawal removes recipient-owned guidance");
    assert(!(await page.locator("#app").innerText()).includes("她说不饿时"), "visible guidance fails closed before remote cleanup");

    await page.reload({ waitUntil: "networkidle" });
    assert(!(await page.locator("#app").innerText()).includes("她说不饿时"), "withdrawn guidance stays hidden after reload");
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), "current flow has no phone-width overflow");
    assert(browserErrors.length === 0, browserErrors.join("\n"));

    await context.close();
    console.log("E2E smoke passed: empty launch, explicit confirmation, strict matching, monotonic gap resolution, provenance, immediate withdrawal, reload, and mobile fit");
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
