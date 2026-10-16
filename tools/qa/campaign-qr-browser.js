async (page) => {
  const image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6T0MAAAAASUVORK5CYII=";
  const campaign = { id: 1, title: "QA campaign", slug: "qa", emoji: "🎯", segment: "buyers",
    message: "Original saved message", status: "draft", has_photo: true, photo_version: "qa", include_reps: 0 };
  const trace = [];
  await page.unroute("http://127.0.0.1:5183/api/**");
  await page.route("http://127.0.0.1:5183/api/**", async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    trace.push({ path, method: request.method() });
    if (path.endsWith("/photo")) return route.fulfill({ contentType: "image/png", body: Buffer.from(image, "base64") });
    if (path === "/api/campaigns/custom" && request.method() === "POST") {
      const body = request.postDataJSON();
      Object.assign(campaign, body, { has_photo: Boolean(body.photo ?? campaign.has_photo) });
      trace[trace.length - 1].saved = { message: body.message, hasPhoto: Boolean(body.photo) };
      return route.fulfill({ json: { success: true, id: 1 } });
    }
    if (path.endsWith("/send")) {
      trace[trace.length - 1].sent = { message: campaign.message, hasPhoto: campaign.has_photo };
      return route.fulfill({ json: { success: true, sent: 1, failed: 0, skipped: 0 } });
    }
    if (path === "/api/campaigns") return route.fulfill({ json: {
      custom: [{ ...campaign }], settings: {}, codes: [], kpi: {}, overview: [],
      segments: [{ key: "buyers", label: "خریداران" }], segment_counts: { buyers: 1 }
    } });
    return route.fulfill({ json: {} });
  });
  await page.addInitScript(() => { window.confirm = () => true; });
  await page.goto("http://127.0.0.1:5183/#/campaigns");
  await page.getByText("QA campaign", { exact: false }).waitFor();
  await page.getByText("QA campaign", { exact: false }).click();
  const savedImage = page.getByAltText("عکس کمپین");
  await savedImage.waitFor();
  await savedImage.evaluate((img) => img.complete ? undefined : new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; }));
  if (!(await savedImage.evaluate((img) => img.naturalWidth > 0))) throw new Error("Saved campaign image not displayed");
  await page.locator("textarea").first().fill("Edited current message");
  await page.getByRole("button", { name: "🖼 انتخاب عکس" }).locator("..").locator('input[type="file"]').setInputFiles({ name: "qa-photo.png", mimeType: "image/png",
    buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6T0MAAAAASUVORK5CYII=", "base64") });
  await page.waitForFunction(() => document.querySelector('img[alt="عکس کمپین"]')?.src.startsWith("data:"));
  await page.evaluate("window.confirm = () => true");
  await page.getByRole("button", { name: "▶️ ذخیره و ارسال کمپین" }).click();
  await page.getByText("ارسال: 1", { exact: false }).waitFor();
  const writes = trace.filter((item) => item.method === "POST");
  if (writes.length !== 2 || !writes[0].path.endsWith("/custom") || !writes[1].path.endsWith("/send")) throw new Error("Send did not persist edits first");
  if (writes[0].saved.message !== "Edited current message" || !writes[0].saved.hasPhoto || !writes[1].sent.hasPhoto) throw new Error("Latest edited text/photo lost: " + JSON.stringify(writes));
  await page.getByRole("button", { name: "+ کمپین جدید" }).click();
  if (!(await page.locator("textarea").first().isVisible())) throw new Error("New campaign editor did not open");
  return { savedImageVisible: true, saveBeforeSend: true, latestPhotoAndMessageUsed: true, newCampaignEditorWorks: true, productionMessages: 0 };
}
