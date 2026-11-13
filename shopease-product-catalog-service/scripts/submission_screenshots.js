// Submission screenshots (Task 12, items 2, 4-15 and 17): real requests sent from Swagger UI in
// Microsoft Edge (headless), saved into DELIVERABELS/screenshots/submission/<item folder>/.
//
// Normally started by scripts/take_submission_screenshots.py. Needs playwright-core (NODE_PATH)
// and Microsoft Edge. Environment:
//   LIVE_URL             the running container (real Authentication Service)
//   LIVE_CUSTOMER_TOKEN  token of a real USER account (from POST /api/auth/login)
//   ADMIN_KIND           "live" (ADMIN token from the real Authentication Service) or "test"
//   ADMIN_URL            where the ADMIN operations are sent (LIVE_URL, or the test instance)
//   ADMIN_TOKEN          ADMIN token accepted at ADMIN_URL
//   ADMIN_URL_USER_TOKEN customer (USER) token accepted at ADMIN_URL
//   OUT_DIR              DELIVERABELS/screenshots/submission
//
// Every image has a banner naming the instance and the time, added by this script. Test-instance
// images also get "_test_instance" in the file name. Every token on the page (Swagger UI shows it in
// the generated curl command) is replaced by "<token hidden>". Nothing else is changed: the
// responses are what the service returned.

const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const env = process.env;
const LIVE = env.LIVE_URL;
const ADMIN_LIVE = env.ADMIN_KIND === "live";
const ADMIN_URL = env.ADMIN_URL;
const SUFFIX = ADMIN_LIVE ? "" : "_test_instance";
const TOKENS = [env.LIVE_CUSTOMER_TOKEN, env.ADMIN_TOKEN, env.ADMIN_URL_USER_TOKEN].filter(Boolean);
const LABEL = {
  live: `LIVE service ${LIVE}: configured database, real Authentication Service`,
  test: `TEST instance ${ADMIN_URL}: test database, STAND-IN Authentication Service (no live ADMIN account)`,
};
const taken = [];

async function banner(page, kind, who) {
  const text = `${LABEL[kind]}  |  token: ${who}  |  ${new Date().toISOString().replace("T", " ").slice(0, 19)} UTC`;
  await page.evaluate(([t, live]) => {
    let b = document.getElementById("evidence-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "evidence-banner";
      b.style.cssText = "position:sticky;top:0;z-index:9999;padding:8px 16px;font:bold 14px Arial;color:#fff;";
      document.body.prepend(b);
    }
    b.style.background = live ? "#1b5e20" : "#8a4b00";
    b.textContent = t;
  }, [text, kind === "live"]);
}

async function open(page, url, kind, who, token) {
  await page.goto(`${url}/docs`, { waitUntil: "networkidle" });
  await page.waitForSelector(".opblock", { timeout: 30000 });
  if (token) {
    await page.locator("button.authorize").first().click();
    await page.locator(".auth-container input").first().fill(token);
    await page.locator(".auth-btn-wrapper button.authorize").click();
    await page.locator(".auth-btn-wrapper button.btn-done").click();
  }
  await banner(page, kind, who);
}

async function shot(page, folder, name, locator) {
  const dir = path.join(env.OUT_DIR, folder);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name}.png`);
  await page.evaluate((tokens) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (const t of tokens) if (node.nodeValue.includes(t)) node.nodeValue = node.nodeValue.split(t).join("<token hidden>");
    }
  }, TOKENS);
  const html = await page.content();
  for (const t of TOKENS) if (html.includes(t)) throw new Error("a token is still on the page");
  if (locator) {
    await locator.evaluate((el) => {
      el.querySelector(".evidence-label")?.remove();
      const label = document.getElementById("evidence-banner").cloneNode(true);
      label.removeAttribute("id");
      label.className = "evidence-label";
      label.style.position = "static";
      el.prepend(label);
    });
    // Hide the banner (sticky) and Swagger's static list of documented responses below the real
    // server response, so the image shows the request and the actual answer.
    await locator.evaluate((el) => {
      el.querySelectorAll("table.responses-table:not(.live-responses-table)").forEach((t) => {
        t.style.display = "none";
        const h = t.closest(".responses-inner")?.querySelectorAll(":scope > div > h4, :scope > h4");
        h?.forEach((x) => { if (x.textContent.trim() === "Responses") x.style.display = "none"; });
      });
    });
    await page.evaluate(() => { document.getElementById("evidence-banner").style.visibility = "hidden"; });
    await locator.screenshot({ path: file });
    await page.evaluate(() => { document.getElementById("evidence-banner").style.visibility = "visible"; });
  } else {
    await page.screenshot({ path: file, fullPage: true });
  }
  taken.push(file);
  console.log("saved", path.relative(env.OUT_DIR, file));
}

const op = (page, tag, id) => page.locator(`#operations-${tag}-${id}`);

async function tryItOut(block) {
  if (!(await block.locator(".opblock-body").isVisible().catch(() => false))) {
    await block.locator(".opblock-summary").first().click();
  }
  const btn = block.locator("button.try-out__btn");
  if ((await btn.textContent()).trim() === "Try it out") await btn.click();
}

async function fill(block, name, value) {
  const row = block.locator(`tr[data-param-name="${name}"]`);
  const select = row.locator("select");
  if (await select.count()) await select.selectOption(String(value));
  else await row.locator("input").fill(String(value));
}

const body = (block, json) => block.locator("textarea.body-param__text").fill(JSON.stringify(json, null, 2));

async function execute(block, expected) {
  await block.locator("button.execute").click();
  const status = block.locator(".live-responses-table .response .response-col_status").first();
  await status.waitFor({ timeout: 20000 });
  const got = (await status.textContent()).trim();
  const text = await block.locator(".live-responses-table .response-col_description pre").first().textContent();
  console.log(`  ${expected} expected, got ${got}`);
  if (!got.startsWith(String(expected))) throw new Error(`expected ${expected}, got ${got}: ${text}`);
  return JSON.parse(text);
}

async function api(page, method, url, token, json) {
  return page.evaluate(async ([m, u, t, j]) => {
    const r = await fetch(u, { method: m, headers: { "Content-Type": "application/json", Authorization: `Bearer ${t}` },
                               body: j ? JSON.stringify(j) : undefined });
    return { status: r.status, body: await r.json() };
  }, [method, url, token, json]);
}

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const adminKind = ADMIN_LIVE ? "live" : "test";
  const stamp = new Date().toISOString().replace(/\D/g, "").slice(8, 14); // HHMMSS, keeps SKUs unique
  let block;
  try {
    // 2. Swagger UI, live
    await open(page, LIVE, "live", "none");
    await shot(page, "02_swagger_ui", "swagger_ui");

    // 9. JWT failures, live
    block = op(page, "Products", "create_product_api_products__post");
    await tryItOut(block);
    await body(block, { category_id: 1, name: "No token", sku: "NO-TOKEN-1", price: "10.00" });
    await execute(block, 401);
    await shot(page, "09_jwt_authorization_failure", "no_token_401", block);

    await open(page, LIVE, "live", "invalid (abc.def.ghi)", "abc.def.ghi");
    block = op(page, "Products", "create_product_api_products__post");
    await tryItOut(block);
    await body(block, { category_id: 1, name: "Invalid token", sku: "BAD-TOKEN-1", price: "10.00" });
    await execute(block, 401);
    await shot(page, "09_jwt_authorization_failure", "invalid_token_401", block);

    // 17. Health, live
    await open(page, LIVE, "live", "none");
    block = op(page, "Service", "health_health_get");
    await tryItOut(block);
    await execute(block, 200);
    await shot(page, "17_health_check", "health_200", block);
    block = op(page, "Service", "database_health_health_db_get");
    await tryItOut(block);
    await execute(block, 200);
    await shot(page, "17_health_check", "health_db_200", block);

    // 10 (customer half, live): a real USER account of the real Authentication Service
    if (env.LIVE_CUSTOMER_TOKEN) {
      await open(page, LIVE, "live", "real customer account (role USER)", env.LIVE_CUSTOMER_TOKEN);
      block = op(page, "Inventory", "stock_in_api_inventory__product_id__stock_in_post");
      await tryItOut(block);
      await fill(block, "product_id", 1);
      await body(block, { quantity: 1, remarks: "Customer attempt" });
      await execute(block, 403);
      await shot(page, "10_admin_vs_customer_access", "customer_403_live", block);
    }

    // ADMIN operations: live if a live ADMIN token exists, otherwise the test instance
    const who = ADMIN_LIVE ? "real ADMIN account" : "stand-in ADMIN token";
    await open(page, ADMIN_URL, adminKind, who, env.ADMIN_TOKEN);

    // 4. Category
    const existing = await (await page.request.get(`${ADMIN_URL}/api/categories/`)).json();
    const catName = existing.some((c) => c.name.toLowerCase() === "electronics") ? `Electronics ${stamp}` : "Electronics";
    block = op(page, "Categories", "create_category_api_categories__post");
    await tryItOut(block);
    await body(block, { name: catName, description: "Phones, laptops and accessories" });
    const category = await execute(block, 201);
    await shot(page, "04_category_creation", `category_created_201${SUFFIX}`, block);

    // 5. Product (and two more through the API, for the listing and low-stock views)
    block = op(page, "Products", "create_product_api_products__post");
    await tryItOut(block);
    await body(block, { category_id: category.id, name: "Nova X12 Smartphone", sku: `PHN-${stamp}`,
                        description: "6.5-inch display, 128 GB", price: "1999.00", discount_price: "1799.00",
                        brand: "Nova", initial_stock: 20 });
    const phone = await execute(block, 201);
    await shot(page, "05_product_creation", `product_created_201${SUFFIX}`, block);
    for (const p of [
      { name: "Aurora 14 Laptop", sku: `LAP-${stamp}`, price: "54999.00", brand: "Aurora", initial_stock: 8 },
      { name: "Pulse Wireless Earbuds", sku: `EAR-${stamp}`, price: "2499.00", brand: "Pulse", initial_stock: 3 },
    ]) {
      const r = await api(page, "POST", `${ADMIN_URL}/api/products/`, env.ADMIN_TOKEN, { category_id: category.id, ...p });
      if (r.status !== 201) throw new Error(`extra product: ${r.status} ${JSON.stringify(r.body)}`);
    }

    // 6. Listing
    await open(page, ADMIN_URL, adminKind, "none");
    block = op(page, "Products", "list_products_api_products__get");
    await tryItOut(block);
    await fill(block, "category_id", category.id);
    await execute(block, 200);
    await shot(page, "06_product_listing", `product_listing_200${SUFFIX}`, block);

    // 7. Search, filter, sort, page
    await open(page, ADMIN_URL, adminKind, "none");
    block = op(page, "Products", "list_products_api_products__get");
    await tryItOut(block);
    await fill(block, "category_id", category.id);
    await fill(block, "min_price", 2000);
    await fill(block, "max_price", 60000);
    await fill(block, "availability", "in_stock");
    await fill(block, "sort_by", "price");
    await fill(block, "sort_order", "desc");
    await fill(block, "page_size", 10);
    await execute(block, 200);
    await shot(page, "07_product_search_and_filtering", `search_filter_200${SUFFIX}`, block);

    // 8. Partial update
    await open(page, ADMIN_URL, adminKind, who, env.ADMIN_TOKEN);
    block = op(page, "Products", "update_product_api_products__product_id__patch");
    await tryItOut(block);
    await fill(block, "product_id", phone.id);
    await body(block, { price: "1899.00" });
    await execute(block, 200);
    await shot(page, "08_product_update", `product_update_200${SUFFIX}`, block);

    // 11. Stock-in (20 -> 30)
    await open(page, ADMIN_URL, adminKind, who, env.ADMIN_TOKEN);
    block = op(page, "Inventory", "stock_in_api_inventory__product_id__stock_in_post");
    await tryItOut(block);
    await fill(block, "product_id", phone.id);
    await body(block, { quantity: 10, remarks: "Supplier delivery" });
    await execute(block, 201);
    await shot(page, "11_stock_in", `stock_in_201${SUFFIX}`, block);

    // 10. The same request as ADMIN (201, 30 -> 31) and as a customer (403)
    await body(block, { quantity: 1, remarks: "Access check" });
    await execute(block, 201);
    await shot(page, "10_admin_vs_customer_access", `admin_201${SUFFIX}`, block);
    await open(page, ADMIN_URL, adminKind, ADMIN_LIVE ? "real customer account (role USER)" : "stand-in customer token (role USER)",
               env.ADMIN_URL_USER_TOKEN);
    block = op(page, "Inventory", "stock_in_api_inventory__product_id__stock_in_post");
    await tryItOut(block);
    await fill(block, "product_id", phone.id);
    await body(block, { quantity: 1, remarks: "Access check" });
    await execute(block, 403);
    await shot(page, "10_admin_vs_customer_access", `customer_403${SUFFIX}`, block);

    // 12. Stock-out (31 -> 4)
    await open(page, ADMIN_URL, adminKind, who, env.ADMIN_TOKEN);
    block = op(page, "Inventory", "stock_out_api_inventory__product_id__stock_out_post");
    await tryItOut(block);
    await fill(block, "product_id", phone.id);
    await body(block, { quantity: 27, remarks: "Order dispatch" });
    await execute(block, 201);
    await shot(page, "12_stock_out", `stock_out_201${SUFFIX}`, block);

    // 13. More than the stock (4) -> 409
    await body(block, { quantity: 50, remarks: "Too many" });
    await execute(block, 409);
    await shot(page, "13_insufficient_stock_validation", `insufficient_stock_409${SUFFIX}`, block);

    // 14. History
    await open(page, ADMIN_URL, adminKind, who, env.ADMIN_TOKEN);
    block = op(page, "Inventory", "read_history_api_inventory__product_id__history_get");
    await tryItOut(block);
    await fill(block, "product_id", phone.id);
    await execute(block, 200);
    await shot(page, "14_inventory_history", `history_200${SUFFIX}`, block);

    // 15. Low stock (the phone at 4, the earbuds at 3)
    block = op(page, "Inventory", "list_low_stock_api_inventory_low_stock_get");
    await tryItOut(block);
    await execute(block, 200);
    await shot(page, "15_low_stock_products", `low_stock_200${SUFFIX}`, block);
  } finally {
    await browser.close();
  }
  console.log(`${taken.length} screenshots`);
}

main().catch((error) => {
  console.error("FAILED:", error.message);
  process.exit(1);
});
