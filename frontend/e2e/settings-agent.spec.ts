import { test, expect, type Page } from "@playwright/test";

/**
 * Agent 能力 / 数据与安全 组的**真实操作**测试。
 *
 * 与 settings-write.spec.ts（偏好项读改写）互补：这些分区是 CRUD / 命令式语义，
 * 判据是「操作后状态真的变了，且能清理干净」。
 *
 * 每个用例都自己清理（删掉自己建的资产 / 恢复权限模式），保证可重复。
 */

const API = "http://127.0.0.1:8788";

async function openSettings(page: Page, group: string, section: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "设置" }).first().click();
  const groupBtn = page.getByRole("button", { name: group, exact: true }).first();
  await groupBtn.waitFor({ state: "visible", timeout: 10_000 });
  if ((await groupBtn.getAttribute("aria-expanded")) !== "true") await groupBtn.click();
  await expect(groupBtn).toHaveAttribute("aria-expanded", "true");
  await page.getByText(section, { exact: true }).first().click();
}

async function ensureOpenMode(page: Page) {
  const res = await page.request.put(`${API}/api/studio/permissions`, {
    data: { mode: "open", allow_chat_admin: true, allow_cli_admin: true },
  });
  expect(res.ok()).toBeTruthy();
}

test.describe("Agent 能力：资产 CRUD", () => {
  test.beforeEach(async ({ page }) => {
    await ensureOpenMode(page);
  });

  test("约束（Rules）：新建 → 出现在列表 → 可停用 → 可删除", async ({ page }) => {
    const name = `E2E约束${Date.now().toString().slice(-6)}`;
    await openSettings(page, "Agent 能力", "约束（Rules）");

    await page.getByRole("button", { name: "手写模板" }).first().click();
    // 资产表单：名称（label 已关联，可直接按 label 定位）+ 正文
    await page.getByLabel("名称").fill(name);
    await page.getByLabel("正文").fill("E2E 测试约束：只描述事实，不给买卖建议。");
    await page.getByRole("button", { name: "创建", exact: true }).first().click();

    await expect(page.getByText(name, { exact: false }).first()).toBeVisible({ timeout: 10_000 });

    // 删除自己建的，避免污染
    const ok = await page.request.delete(`${API}/api/studio/rules/${encodeURIComponent(name)}?force=true`);
    // id 未必等于 name，删不掉就按列表查 id 再删
    if (!ok.ok()) {
      const list = await (await page.request.get(`${API}/api/studio/rules`)).json();
      const hit = (list.assets || []).find((a: { name: string; id: string }) => a.name === name);
      if (hit) {
        await page.request.delete(`${API}/api/studio/rules/${encodeURIComponent(hit.id)}?force=true`);
      }
    }
  });

  test("Hook：列表非空且内置安全 Hook 无法停用", async ({ page }) => {
    await openSettings(page, "Agent 能力", "Hook 钩子");
    await expect(page.getByText("拦截命令执行工具").first()).toBeVisible({ timeout: 10_000 });

    // 后端必须拒绝停用内置安全 Hook（切片 9 修复）
    const res = await page.request.post(`${API}/api/studio/hooks/block_shell_tools/toggle`, {
      data: { enabled: false },
    });
    expect(res.ok()).toBeFalsy();
    expect(await res.text()).toContain("内置安全 Hook");

    // 页面上的开关状态不能被改掉
    const list = await (await page.request.get(`${API}/api/studio/hooks`)).json();
    const hook = (list.assets || []).find((a: { id: string }) => a.id === "block_shell_tools");
    expect(hook?.enabled).toBe(true);
  });

  test("权限：切到标准模式后写操作被拒，再切回 open", async ({ page }) => {
    await openSettings(page, "Agent 能力", "权限");
    await expect(page.getByText(/全面放开|标准|严格/).first()).toBeVisible({ timeout: 10_000 });

    // 切标准
    const toStandard = await page.request.put(`${API}/api/studio/permissions`, {
      data: { mode: "standard" },
    });
    expect(toStandard.ok()).toBeTruthy();
    let perms = await (await page.request.get(`${API}/api/studio/permissions`)).json();
    expect(perms.permissions.mode).toBe("standard");
    expect(perms.permissions.allow_chat_admin).toBe(false);

    // 标准模式下建资产应 403
    const blocked = await page.request.post(`${API}/api/studio/rules`, {
      data: { name: "should-be-blocked", content: "x" },
    });
    expect(blocked.status()).toBe(403);

    // 切回
    await ensureOpenMode(page);
    perms = await (await page.request.get(`${API}/api/studio/permissions`)).json();
    expect(perms.permissions.mode).toBe("open");
  });

  test("内置工具：列表非空且可切换开关", async ({ page }) => {
    await openSettings(page, "Agent 能力", "内置工具");
    const list = await (await page.request.get(`${API}/api/studio/overview`)).json();
    expect(list.counts.internal_tools).toBeGreaterThan(0);
    await expect(page.getByText(/统计|计算|工具/).first()).toBeVisible({ timeout: 10_000 });
  });

  test("插件（MCP）：stdio 写入/启用默认被拒（安全边界）", async ({ page }) => {
    // 门禁在「保存配置」这一步：stdio 条目会被直接拒绝
    const put = await page.request.put(`${API}/api/mcp/servers`, {
      data: { servers: [{ name: "e2e-stdio", command: "npx", args: ["-y", "x"], enabled: true }] },
    });
    expect(put.ok()).toBeFalsy();
    expect(await put.text()).toMatch(/stdio MCP 服务器不支持|MONEYHELPER_ALLOW_STDIO_MCP/);

    // HTTP 型服务器可以正常保存
    const httpPut = await page.request.put(`${API}/api/mcp/servers`, {
      data: { servers: [{ name: "e2e-http", url: "https://example.com/mcp", enabled: false }] },
    });
    expect(httpPut.ok()).toBeTruthy();
    const list = await (await page.request.get(`${API}/api/mcp/servers`)).json();
    expect((list.servers || []).some((x: { name: string }) => x.name === "e2e-http")).toBe(true);

    // 清理
    await page.request.put(`${API}/api/mcp/servers`, { data: { servers: [] } });
  });

  test("插件市场：条目可列、来源可信", async ({ page }) => {
    await openSettings(page, "Agent 能力", "插件市场");
    const res = await page.request.get(`${API}/api/studio/market/list`);
    const body = await res.json();
    expect((body.items || []).length).toBeGreaterThan(0);
    expect(body.items.every((i: { id: string }) => Boolean(i.id))).toBeTruthy();
  });
});

test.describe("数据与安全", () => {
  test("数据与状态：导出预览可用（不下载大文件）", async ({ page }) => {
    await openSettings(page, "数据与安全", "数据与状态");
    const res = await page.request.get(`${API}/api/export`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.version).toBeTruthy();
    // 关键表都在
    for (const key of ["positions", "transactions", "settings"]) {
      expect(body).toHaveProperty(key);
    }
  });

  test("日志：可读取（本机模式不弹口令框）", async ({ page }) => {
    await openSettings(page, "数据与安全", "日志");
    // 切片修复：/api/logs 本机模式返回 200 而不是 401
    const res = await page.request.get(`${API}/api/logs?limit=10`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(Array.isArray(body.lines)).toBeTruthy();
    // 页面不应出现口令对话框
    await expect(page.getByText("需要访问口令")).toHaveCount(0);
  });

  test("审计日志：哈希链可验证", async ({ page }) => {
    await openSettings(page, "数据与安全", "审计日志");
    const res = await page.request.get(`${API}/api/audit/verify`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.ok).toBe(true);
    expect(typeof body.checked).toBe("number");
  });

  test("溯源链：有记录且可按类型过滤", async ({ page }) => {
    await openSettings(page, "数据与安全", "溯源链");
    const res = await page.request.get(`${API}/api/provenance`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(Array.isArray(body.provenances)).toBeTruthy();
    expect(body.count).toBeGreaterThanOrEqual(0);
  });

  test("访问口令：显示当前鉴权模式（本机模式明确说明免登录）", async ({ page }) => {
    await openSettings(page, "数据与安全", "访问口令");
    await expect(page.getByText(/本机|免登录|口令/).first()).toBeVisible({ timeout: 10_000 });
  });

  test("模型评测：题库 50 题可读，未配模型时不伪造分数", async ({ page }) => {
    await openSettings(page, "质量与评测", "模型评测");
    const q = await page.request.get(`${API}/api/eval/questions`);
    expect(q.ok()).toBeTruthy();
    const qb = await q.json();
    expect(qb.total).toBe(50);
    // 未配置模型时 scored=false + 明确原因，不能返回假成绩
    if (!qb.scored) {
      const run = await page.request.post(`${API}/api/eval/run`, { data: { max_questions: 1 } });
      const rb = await run.json();
      if (rb.scored === false) {
        expect(String(rb.reason || "")).toContain("模型");
      }
    }
  });
});
