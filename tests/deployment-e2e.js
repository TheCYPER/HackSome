"use strict";

const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";
const BUILD = "2026.07.25-production-v6";
const PRODUCTION_URL = "https://thecyper.github.io/HackSome/?deployment=static-review";
const PRODUCTION_PREVIEW = "https://thecyper.github.io/HackSome/assets/social-preview.jpg";
const STORAGE_KEY = "relay-rehearsal-demo-v1";
const suppliedReviewURL = String(process.env.BASE_URL || "").trim();

function assert(condition, message) {
  if (!condition) throw new Error(`Deployment E2E assertion failed: ${message}`);
}

async function listen() {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  return `http://127.0.0.1:${server.address().port}`;
}

async function navigateWithRetries(page, url) {
  const attempts = suppliedReviewURL ? 5 : 1;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await page.goto(url, { waitUntil: "networkidle" });
      await page.waitForFunction(() => document.documentElement.dataset.deploymentMode === "hosted-static-review", null, { timeout: 4_000 });
      return true;
    } catch {
      if (attempt < attempts) await page.waitForTimeout(attempt * 700);
    }
  }
  return false;
}

(async () => {
  const localServer = !suppliedReviewURL;
  const localOrigin = localServer ? await listen() : "";
  const reviewURL = suppliedReviewURL || `${localOrigin}/index.html?deployment=static-review`;
  const localPreviewURL = new URL("./assets/social-preview.jpg", reviewURL).href;
  const joinURL = new URL("./join.html?room=fake&deployment=static-review", reviewURL).href;
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }, { width: 320, height: 760 }]) {
      const realContext = await browser.newContext({ viewport });
      const realPage = await realContext.newPage();
      realPage.setDefaultTimeout(10_000);
      let realApiRequests = 0;
      await realPage.route("**/api/**", (route) => {
        realApiRequests += 1;
        route.abort();
      });
      assert(await navigateWithRetries(realPage, reviewURL), `clean ${viewport.width}px public real-household page initializes`);
      const cleanState = await realPage.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
      assert(cleanState?.mode === null, `clean ${viewport.width}px storage begins at mode choice`);
      await realPage.getByRole("button", { name: /在电脑上建立我的接班彩排/ }).click();
      await realPage.locator(".page-kicker").filter({ hasText: "第 1 / 6 步" }).waitFor();
      await realPage.waitForFunction(() => window.scrollY === 0);
      const realState = await realPage.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY);
      assert(realState?.mode === "real" && realState?.onboarding?.step === 1 && realState?.guides?.length === 0 && realState?.sessions?.length === 0, `public ${viewport.width}px entry persists honest real mode at onboarding 1/6`);
      assert(await realPage.getByRole("heading", { name: "先把需要联系的人放进来" }).isVisible(), `public ${viewport.width}px shows actionable real-household onboarding`);
      assert(await realPage.evaluate(() => window.scrollY === 0), `public ${viewport.width}px onboarding starts at its visible heading`);
      assert(await realPage.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `real onboarding has no ${viewport.width}px horizontal overflow`);
      await realPage.reload({ waitUntil: "domcontentloaded" });
      await realPage.locator(".page-kicker").filter({ hasText: "第 1 / 6 步" }).waitFor();
      assert((await realPage.evaluate((key) => JSON.parse(localStorage.getItem(key)), STORAGE_KEY))?.mode === "real", `public ${viewport.width}px onboarding resumes from browser storage`);
      if (viewport.width === 320) {
        const people = {
          "#setup-caregiver": "林安",
          "#setup-caregiver-phone": "13800138000",
          "#setup-recipient": "林禾",
          "#setup-relay": "周宁",
          "#setup-emergency-name": "陈平",
          "#setup-emergency-phone": "13900139000",
          "#setup-emergency-service": "999",
        };
        for (const [selector, value] of Object.entries(people)) await realPage.locator(selector).fill(value);
        await realPage.locator("#onboarding-people button[type='submit']").click();
        await realPage.locator(".page-kicker").filter({ hasText: "第 2 / 6 步" }).waitFor();
        await realPage.waitForFunction(() => window.scrollY === 0);
        assert(await realPage.getByRole("heading", { name: "只定一个能实现的小休息" }).isVisible(), "320px forward transition reveals the next onboarding heading");
        assert(await realPage.evaluate(() => document.activeElement?.matches(".setup-header h1")), "320px forward transition moves assistive focus to the new step heading");
        await realPage.getByRole("button", { name: "上一步" }).click();
        await realPage.locator(".page-kicker").filter({ hasText: "第 1 / 6 步" }).waitFor();
        await realPage.waitForFunction(() => window.scrollY === 0);
        assert(await realPage.getByRole("heading", { name: "先把需要联系的人放进来" }).isVisible(), "320px back transition reveals the previous onboarding heading");
      }
      assert(realApiRequests === 0, `public ${viewport.width}px real onboarding makes no room API requests (saw ${realApiRequests})`);
      await realContext.close();
    }

    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    let apiRequests = 0;
    const failedRequests = [];
    page.on("requestfailed", (request) => failedRequests.push(`${request.resourceType()} ${request.url()} — ${request.failure()?.errorText || "failed"}`));
    await page.route("**/api/**", (route) => {
      apiRequests += 1;
      route.abort();
    });
    const initialized = await navigateWithRetries(page, reviewURL);
    assert(initialized, `public scripts initialize after bounded TLS retries (${failedRequests.slice(-8).join(" | ") || "no failed request detail"})`);
    assert(await page.locator("html").getAttribute("data-deployment-mode") === "hosted-static-review", "forced hosted build advertises its deployment mode");
    assert(await page.locator('meta[name="relay-build"]').getAttribute("content") === BUILD, "document exposes the exact review build");
    assert(await page.locator('link[rel="canonical"]').getAttribute("href") === PRODUCTION_URL, "canonical metadata names the immutable public review URL");
    assert(await page.locator('meta[property="og:url"]').getAttribute("content") === PRODUCTION_URL, "social URL names the immutable public review URL");
    const socialPreview = await page.locator('meta[property="og:image"]').getAttribute("content");
    assert(socialPreview === PRODUCTION_PREVIEW, "social preview metadata points to the immutable public asset");
    const preview = await page.request.get(localPreviewURL);
    assert(preview.ok() && (await preview.body()).length > 100_000, "social preview asset is publicly served");
    assert(await page.locator('meta[name="referrer"]').getAttribute("content") === "no-referrer", "initial public document enforces no-referrer in document policy");
    const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content");
    assert(csp.includes("default-src 'self'") && csp.includes("object-src 'none'") && csp.includes("connect-src 'self'"), "initial public document has a restrictive same-origin CSP");
    assert(await page.locator('meta[http-equiv="X-Content-Type-Options"]').getAttribute("content") === "nosniff", "public source declares its no-sniff deployment policy");
    if (localServer) {
      const localHeaders = (await page.request.get(reviewURL)).headers();
      assert(localHeaders["content-security-policy"]?.includes("frame-ancestors 'none'"), "local production server returns CSP");
      assert(localHeaders["referrer-policy"] === "no-referrer" && localHeaders["x-content-type-options"] === "nosniff", "local production server returns referrer and no-sniff headers");
    }

    await page.getByRole("button", { name: /体验演示家庭/ }).click();
    await page.getByRole("button", { name: "打开评审说明" }).click();
    const reviewBrief = await page.locator("#modal-root").innerText();
    assert(reviewBrief.includes("问题") && reviewBrief.includes("目标用户") && reviewBrief.includes("核心机制"), "compact review brief states problem, target user, and core mechanism");
    assert(reviewBrief.includes("产品观察") && reviewBrief.includes("参与者自述") && reviewBrief.includes("打开拨号”不等于电话接通"), "review brief distinguishes observed actions from participant self-report");
    assert(reviewBrief.includes("真实家庭公开路径") && reviewBrief.includes("建议 2–3 分钟演示路径") && reviewBrief.includes(BUILD) && reviewBrief.includes("当前页面不会请求 /api/rooms"), "review brief exposes both paths, exact build, and hosted boundary");
    await page.getByRole("button", { name: "开始查看" }).click();
    await page.getByRole("button", { name: "演示模式：从头重播三分钟评审导览" }).click();
    assert(await page.locator(".judge-demo-top").isVisible(), "clean-storage demo onboarding can be replayed from the public header");
    await page.locator(".desktop-nav [data-nav='rehearsal']").click();
    assert(await page.getByRole("heading", { name: "公开评审版不创建双机房间" }).isVisible(), "pairing card is replaced by the hosted boundary");
    assert(await page.locator("[data-action='show-local-full-experience']").count() >= 2, "hosted pairing CTAs all point to local full experience");
    await page.locator("#companion-card [data-action='show-local-full-experience']").click();
    assert(await page.getByText("不要把本地房间服务直接暴露到公网").isVisible(), "pairing CTA explains the public exposure boundary");
    assert(apiRequests === 0, `hosted app makes no room API requests (saw ${apiRequests})`);

    await page.getByRole("button", { name: "知道了" }).click();
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `hosted review has no ${width}px horizontal overflow`);
      assert(await page.getByRole("button", { name: "打开评审说明" }).isVisible(), `review brief remains reachable at ${width}px`);
    }

    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) {
        await new Promise((resolve) => navigator.serviceWorker.addEventListener("controllerchange", resolve, { once: true }));
      }
    });
    await page.reload({ waitUntil: "networkidle" });
    assert(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), "public shell is service-worker controlled before offline validation");
    const controlledSecurityHeaders = await page.evaluate(async () => {
      const response = await fetch(location.href.split("#")[0], { cache: "no-store" });
      return Object.fromEntries(response.headers.entries());
    });
    assert(controlledSecurityHeaders["content-security-policy"]?.includes("frame-ancestors 'none'"), "controlled production response returns CSP");
    assert(controlledSecurityHeaders["referrer-policy"] === "no-referrer" && controlledSecurityHeaders["x-content-type-options"] === "nosniff", "controlled production response returns referrer and no-sniff headers");
    const controlledHeaders = (await page.request.get(reviewURL)).headers();
    if (localServer) {
      assert(controlledHeaders["content-security-policy"] && controlledHeaders["referrer-policy"] === "no-referrer" && controlledHeaders["x-content-type-options"] === "nosniff", "direct local response preserves all three security headers");
    }
    const cachedPublicRequests = await page.evaluate(async () => {
      const keys = await caches.keys();
      const requests = await Promise.all(keys.map(async (key) => (await caches.open(key)).keys()));
      return requests.flat().map((request) => request.url);
    });
    const controlledURL = page.url().split("#")[0];
    assert(cachedPublicRequests.some((url) => url === controlledURL) || cachedPublicRequests.some((url) => url.includes("?deployment=static-review")), `online public navigation enters the shell cache (${cachedPublicRequests.join(", ")})`);
    const failNetwork = (route) => route.abort("internetdisconnected");
    await context.route("**/*", failNetwork);
    try {
      await page.reload({ waitUntil: "domcontentloaded" });
    } catch (error) {
      // Firefox can surface a transport error even after a controlling worker
      // has fulfilled the navigation. The rendered shell below remains the
      // acceptance boundary; all other navigation errors still fail.
      if (!/NS_ERROR_(?:OFFLINE|NET_RESET|NET_INTERRUPT)/.test(String(error?.message || error))) throw error;
      await page.waitForTimeout(250);
    }
    assert(await page.getByRole("button", { name: "打开评审说明" }).isVisible(), "cached public shell reloads offline");
    assert(await page.locator("html").getAttribute("data-deployment-mode") === "hosted-static-review", "offline shell preserves the public pairing boundary");
    await context.unroute("**/*", failNetwork);

    const joinPage = await context.newPage();
    let joinApiRequests = 0;
    await joinPage.route("**/api/**", (route) => {
      joinApiRequests += 1;
      route.abort();
    });
    await joinPage.goto(joinURL, { waitUntil: "networkidle" });
    assert(await joinPage.getByRole("heading", { name: "公开评审版不连接临时双机房间" }).isVisible(), "direct substitute URL also fails closed to the hosted boundary");
    assert(joinApiRequests === 0, `hosted substitute page makes no room API requests (saw ${joinApiRequests})`);
    await context.close();
    console.log("Deployment E2E passed: exact canonical build, clean-storage real onboarding and 320px step transitions, expanded review brief, document/security policy, social preview, demo replay, static no-API boundary, offline shell, and honest local/LAN pairing handoff");
  } finally {
    await browser.close();
    if (localServer) await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  if (!suppliedReviewURL) {
    try { server.closeAllConnections?.(); } catch { /* best effort */ }
    try { server.close(); } catch { /* may already be closed */ }
  }
  console.error(error.stack || error);
  process.exit(1);
});
