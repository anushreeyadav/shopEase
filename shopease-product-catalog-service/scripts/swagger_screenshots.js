// Swagger UI screenshots (Task 11): real requests sent from Swagger UI in Microsoft Edge.
//
//   node scripts/swagger_screenshots.js        (normally started by scripts/run_postman_suite.py)
//
// Needs playwright-core (NODE_PATH) and Microsoft Edge. Environment:
//   LIVE_URL             the running container, real Authentication Service (no token available)
//   STANDIN_URL          the test instance: test database, stand-in Authentication Service
//   STANDIN_ADMIN_TOKEN  token accepted by the stand-in only
//   RUN_ID               prefix of the test run's products (PM<RUN_ID>-...)
//   OUT_DIR              where the PNG files go
//
// Every image gets a banner at the top naming the instance and the time, added by this script so
// that a reader can tell live screenshots from test-instance screenshots. The token in Swagger
// UI's generated curl command is replaced by "<token hidden>". Nothing else on the page is
// changed: the responses are what the service returned.

const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const { LIVE_URL, STANDIN_URL, STANDIN_ADMIN_TOKEN, RUN_ID, OUT_DIR } = process.env;
const LABELS = {
  live: `LIVE service ${LIVE_URL}: configured database, real Authentication Service`,
  standin: `TEST instance ${STANDIN_URL}: test database, STAND-IN Authentication Service (no live ADMIN account exists)`,
};
const taken = [];

async function banner(page, kind) {
  const text = `${LABELS[kind]}  |  ${new Date().toISOString().replace("T", " ").slice(0, 19)} UTC`;
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

async function open(page, url, kind) {
  await page.goto(`${url}/docs`, { waitUntil: "networkidle" });
  await page.waitForSelector(".opblock", { timeout: 30000 });
  await banner(page, kind);
}

async function shot(page, name, locator) {
  const file = path.join(OUT_DIR, `${name}.png`);
  // The token Swagger UI shows in the generated curl command is masked; nothing else is changed.
  await page.evaluate((token) => {
    if (!token) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeValue.includes(token)) node.nodeValue = node.nodeValue.split(token).join("<token hidden>");
    }
  }, STANDIN_ADMIN_TOKEN || "");
  if (locator) {
    // Copy the page banner into the operation block, so the label is part of the element image.
    await locator.evaluate((el) => {
      el.querySelector(".evidence-label")?.remove();
      const label = document.getElementById("evidence-banner").cloneNode(true);
      label.removeAttribute("id");
      label.className = "evidence-label";
      label.style.position = "static";
      el.prepend(label);
    });
    // The page banner is sticky; hide it while the block is captured, so it is not drawn twice.
    await page.evaluate(() => { document.getElementById("evidence-banner").style.visibility = "hidden"; });
    await locator.screenshot({ path: file });
    await page.evaluate(() => { document.getElementById("evidence-banner").style.visibility = "visible"; });
  } else {
    await page.screenshot({ path: file, fullPage: true });
  }
  taken.push(file);
  console.log("saved", file);
}

async function authorize(page) {
  // Swagger UI keeps the token only until the page is reloaded.
  await page.locator("button.authorize").first().click();
  await page.locator(".auth-container input").first().fill(STANDIN_ADMIN_TOKEN);
  await page.locator(".auth-btn-wrapper button.authorize").click();
  await page.locator(".auth-btn-wrapper button.btn-done").click();
}

function op(page, tag, operationId) {
  return page.locator(`#operations-${tag}-${operationId}`);
}

async function tryItOut(page, block) {
  if (!(await block.locator(".opblock-body").isVisible().catch(() => false))) {
    await block.locator(".opblock-summary").first().click();
  }
  await block.locator("button.try-out__btn").click();
}

async function fill(block, name, value) {
  const row = block.locator(`tr[data-param-name="${name}"]`);
  const select = row.locator("select");
  if (await select.count()) await select.selectOption(String(value));
  else await row.locator("input").fill(String(value));
}

async function body(block, json) {
  await block.locator("textarea.body-param__text").fill(JSON.stringify(json, null, 2));
}

async function execute(page, block, expectedStatus) {
  await block.locator("button.execute").click();
  const status = block.locator(".live-responses-table .response .response-col_status").first();
  await status.waitFor({ timeout: 20000 });
  const got = (await status.textContent()).trim();
  console.log(`  response status ${got} (expected ${expectedStatus})`);
  if (!got.startsWith(String(expectedStatus))) throw new Error(`expected ${expectedStatus}, got ${got}`);
  return got;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  try {
    // --- Live service ---
    await open(page, LIVE_URL, "live");
    await shot(page, "01_live_swagger_overview");

    let block = op(page, "Products", "list_products_api_products__get");
    await block.locator(".opblock-summary").first().click();
    await shot(page, "02_live_list_products_parameters", block);

    await tryItOut(page, block);
    await fill(block, "search", "mobile");
    await fill(block, "page_size", 10);
    await fill(block, "sort_by", "price");
    await fill(block, "sort_order", "asc");
    await execute(page, block, 200);
    await shot(page, "03_live_list_products_executed_200", block);

    await open(page, LIVE_URL, "live");
    block = op(page, "Products", "create_product_api_products__post");
    await tryItOut(page, block);
    await body(block, { category_id: 1, name: "No token", sku: "NO-TOKEN-1", price: "10.00" });
    await execute(page, block, 401);
    await shot(page, "04_live_create_product_without_token_401", block);

    await open(page, LIVE_URL, "live");
    block = op(page, "Products", "read_product_api_products__product_id__get");
    await tryItOut(page, block);
    await fill(block, "product_id", 999999);
    await execute(page, block, 404);
    await shot(page, "05_live_get_missing_product_404", block);

    await open(page, LIVE_URL, "live");
    block = op(page, "Service", "health_health_get");
    await tryItOut(page, block);
    await execute(page, block, 200);
    await shot(page, "06_live_health_200", block);

    // --- Test instance, stand-in Authentication Service ---
    await open(page, STANDIN_URL, "standin");
    await page.locator("button.authorize").first().click();
    await page.locator(".auth-container input").first().fill(STANDIN_ADMIN_TOKEN);
    await page.locator(".auth-btn-wrapper button.authorize").click();
    await page.locator(".auth-container").first().waitFor();
    await shot(page, "07_test_authorized_as_admin", page.locator(".modal-ux"));
    await page.locator(".auth-btn-wrapper button.btn-done").click();

    const prefix = `PM${RUN_ID}`;
    const laptops = await page.evaluate(async ([u, p]) => {
      const r = await fetch(`${u}/api/products/?search=${p}-LAP`);
      return (await r.json()).items[0];
    }, [STANDIN_URL, prefix]);

    block = op(page, "Products", "create_product_api_products__post");
    await tryItOut(page, block);
    await body(block, { category_id: laptops.category_id, name: `${prefix} Swagger Tablet`, sku: `${prefix}-SWG-1`,
                        price: "2499.00", discount_price: "2299.00", brand: "Swagger", initial_stock: 3 });
    await execute(page, block, 201);
    await shot(page, "08_test_create_product_201", block);

    await body(block, { category_id: laptops.category_id, name: "Copy", sku: `${prefix}-swg-1`, price: "1.00" });
    await execute(page, block, 409);
    await shot(page, "09_test_create_product_duplicate_sku_409", block);

    await open(page, STANDIN_URL, "standin");
    await authorize(page);
    block = op(page, "Products", "list_products_api_products__get");
    await tryItOut(page, block);
    await fill(block, "search", prefix);
    await fill(block, "min_price", 1000);
    await fill(block, "sort_by", "price");
    await fill(block, "sort_order", "desc");
    await fill(block, "page_size", 3);
    await execute(page, block, 200);
    await shot(page, "10_test_search_filter_sort_page_200", block);

    const swagger = await page.evaluate(async ([u, p]) => {
      const r = await fetch(`${u}/api/products/?search=${p}-SWG`);
      return (await r.json()).items[0];
    }, [STANDIN_URL, prefix]);

    block = op(page, "Inventory", "stock_in_api_inventory__product_id__stock_in_post");
    await tryItOut(page, block);
    await fill(block, "product_id", swagger.id);
    await body(block, { quantity: 10, remarks: "Delivery entered in Swagger UI" });
    await execute(page, block, 201);
    await shot(page, "11_test_stock_in_201", block);

    await open(page, STANDIN_URL, "standin");
    await authorize(page);
    block = op(page, "Inventory", "stock_out_api_inventory__product_id__stock_out_post");
    await tryItOut(page, block);
    await fill(block, "product_id", swagger.id);
    await body(block, { quantity: 500 });
    await execute(page, block, 409);
    await shot(page, "12_test_stock_out_insufficient_409", block);

    block = op(page, "Inventory", "read_history_api_inventory__product_id__history_get");
    await tryItOut(page, block);
    await fill(block, "product_id", swagger.id);
    await execute(page, block, 200);
    await shot(page, "13_test_inventory_history_200", block);

    block = op(page, "Inventory", "list_low_stock_api_inventory_low_stock_get");
    await tryItOut(page, block);
    await execute(page, block, 200);
    await shot(page, "14_test_low_stock_200", block);
  } finally {
    await browser.close();
  }
  console.log(`${taken.length} screenshots`);
}

main().catch((error) => {
  console.error("FAILED:", error.message);
  process.exit(1);
});
