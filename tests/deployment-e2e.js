"use strict";

const { firefox } = require("/usr/local/lib/python3.12/dist-packages/playwright/driver/package");
const { server } = require("../server");

const FIREFOX_PATH = "/home/kasm-user/.cache/ms-playwright/firefox-1509/firefox/firefox";
const BUILD = "2026.07.25-production-v3";
const PRODUCTION_URL = "https://thecyper.github.io/HackSome/?deployment=static-review";
const PRODUCTION_PREVIEW = "https://thecyper.github.io/HackSome/assets/social-preview.jpg";
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

(async () => {
  const localServer = !suppliedReviewURL;
  const localOrigin = localServer ? await listen() : "";
  const reviewURL = suppliedReviewURL || `${localOrigin}/index.html?deployment=static-review`;
  const localPreviewURL = new URL("./assets/social-preview.jpg", reviewURL).href;
  const joinURL = new URL("./join.html?room=fake&deployment=static-review", reviewURL).href;
  const browser = await firefox.launch({ headless: true, executablePath: FIREFOX_PATH });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    let apiRequests = 0;
    const failedRequests = [];
    page.on("requestfailed", (request) => failedRequests.push(`${request.resourceType()} ${request.url()} — ${request.failure()?.errorText || "failed"}`));
    await page.route("**/api/**", (route) => {
      apiRequests += 1;
      route.abort();
    });
    let initialized = false;
    for (let attempt = 1; attempt <= (suppliedReviewURL ? 5 : 1); attempt += 1) {
      try {
        await page.goto(reviewURL, { waitUntil: "networkidle" });
        await page.waitForFunction(() => document.documentElement.dataset.deploymentMode === "hosted-static-review", null, { timeout: 4_000 });
        initialized = true;
        break;
      } catch {
        if (attempt < (suppliedReviewURL ? 5 : 1)) await page.waitForTimeout(attempt * 700);
      }
    }
    assert(initialized, `public scripts initialize after bounded TLS retries (${failedRequests.slice(-8).join(" | ") || "no failed request detail"})`);
    assert(await page.locator("html").getAttribute("data-deployment-mode") === "hosted-static-review", "forced hosted build advertises its deployment mode");
    assert(await page.locator('meta[name="relay-build"]').getAttribute("content") === BUILD, "document exposes the exact review build");
    assert(await page.locator('link[rel="canonical"]').getAttribute("href") === PRODUCTION_URL, "canonical metadata names the immutable public review URL");
    assert(await page.locator('meta[property="og:url"]').getAttribute("content") === PRODUCTION_URL, "social URL names the immutable public review URL");
    const socialPreview = await page.locator('meta[property="og:image"]').getAttribute("content");
    assert(socialPreview === PRODUCTION_PREVIEW, "social preview metadata points to the immutable public asset");
    const preview = await page.request.get(localPreviewURL);
    assert(preview.ok() && (await preview.body()).length > 100_000, "social preview asset is publicly served");

    await page.getByRole("button", { name: /在电脑上建立我的接班彩排/ }).click();
    assert(await page.getByRole("heading", { name: /本地完整体验/ }).isVisible(), "public real-family entry hands off to local full experience");
    const localInstructions = await page.locator("#modal-root").innerText();
    assert(localInstructions.includes("npm start") && localInstructions.includes("局域网IP:4173") && localInstructions.includes("不会假装提供远端配对"), "in-product handoff includes exact start, LAN, and honesty boundaries");
    await page.getByRole("button", { name: "知道了" }).click();

    await page.getByRole("button", { name: /体验演示家庭/ }).click();
    await page.getByRole("button", { name: "打开评审说明" }).click();
    const reviewBrief = await page.locator("#modal-root").innerText();
    assert(reviewBrief.includes("建议 2–3 分钟路径") && reviewBrief.includes(BUILD) && reviewBrief.includes("当前页面不会请求 /api/rooms"), "compact review brief exposes path, build, and hosted boundary");
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
    console.log("Deployment E2E passed: exact canonical build, social preview, replay/onboarding, review brief, static no-API boundary, offline shell, local/LAN handoff, and desktop/390/320 layouts");
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
