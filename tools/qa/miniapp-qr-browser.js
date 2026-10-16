async (page) => {
  const image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6T0MAAAAASUVORK5CYII=";
  let qrRequests = 0;
  const errors = [];
  const listener = (error) => errors.push(String(error));
  page.on("pageerror", listener);
  await page.route("http://127.0.0.1:5184/app/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/bootstrap")) return route.fulfill({ json: {
      enabled: true, brand: { title: "Atlas QA", logo: "🌐" }, user: { name: "QA", balance: 0 },
      stats: { active_services: 1, total_services: 1 }, is_rep: false, support: ""
    } });
    if (path.endsWith("/services")) return route.fulfill({ json: { services: [{
      id: 9, name: "QA subscription", traffic_gb: 10, used_bytes: 0, expire_ts: 0,
      is_active: 1, sub_url: "https://example.test/sub/owned", nodes: []
    }] } });
    if (path.endsWith("/services/qr")) {
      if (route.request().postDataJSON().profile_id !== 9) throw new Error("Wrong subscription requested");
      qrRequests += 1;
      return route.fulfill({ json: { image, sub_url: "https://example.test/sub/current-" + qrRequests } });
    }
    return route.fulfill({ json: {} });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:5184/app/");
  await page.locator("nav.tabbar").getByRole("button", { name: "سرویس‌ها" }).click();
  await page.getByText("QA subscription", { exact: true }).waitFor();
  for (let i = 0; i < 2; i++) {
    await page.getByRole("button", { name: "نمایش QR", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "QR اشتراک" });
    await dialog.getByRole("img").waitFor();
    if (!(await dialog.getByRole("img").evaluate((img) => img.src.startsWith("data:image/png")))) throw new Error("QR not displayed");
    await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  }
  page.removeListener("pageerror", listener);
  if (errors.length || qrRequests !== 2) throw new Error(JSON.stringify({ errors, qrRequests }));
  return { qrShownTwice: true, authenticatedPostPerOpen: true, mobileViewport: true, pageErrors: errors.length, productionMessages: 0 };
}
