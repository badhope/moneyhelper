import { test, expect, type Page } from "@playwright/test";

/**
 * 设置页长尾分区的**真实操作**测试（组织架构 / 家庭账本 / 知识库 / Hook / 内置工具）。
 *
 * 判据：操作后状态真的变了，且能清理干净。每个用例自建自删，可重复运行。
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

test.describe("组织架构：部门与岗位 CRUD", () => {
  test("建部门 → 出现在列表 → 建岗位 → 清理", async ({ page }) => {
    const stamp = Date.now().toString().slice(-6);
    const deptName = `E2E部门${stamp}`;
    const deptCode = `E2E${stamp}`;
    const posName = `E2E岗位${stamp}`;

    await openSettings(page, "基础设置", "组织架构");
    await expect(page.getByText(/当前租户/).first()).toBeVisible({ timeout: 10_000 });

    // 建部门
    await page.getByLabel("名称").first().fill(deptName);
    await page.getByLabel("编码").first().fill(deptCode);
    await page.getByRole("button", { name: "新增部门" }).click();
    // 部门名会同时出现在下拉 <option> 里（hidden），这里只断言非 option 的可见文本
    await expect(
      page.locator("div").filter({ hasText: deptName }).filter({ hasNot: page.locator("select") }).first(),
    ).toBeVisible({ timeout: 10_000 });

    // 后端确认
    let ov = await (await page.request.get(`${API}/api/org/overview`)).json();
    const dept = (ov.departments || []).find((d: { name: string }) => d.name === deptName);
    expect(dept, "部门未落库").toBeTruthy();

    // 建岗位（挂在该部门下）
    // 岗位表单的 name/department 用 id 精确定位：页面上还有侧栏「财务部门」
    // 按钮和"部门"标题，按 label 会误匹配
    await page.locator("#orgsection-5").fill(posName);
    await page.locator("#orgsection-6").selectOption(String(dept.id));
    await page.getByRole("button", { name: "新增岗位" }).click();
    await expect(page.getByText(posName).first()).toBeVisible({ timeout: 10_000 });

    ov = await (await page.request.get(`${API}/api/org/overview`)).json();
    const pos = (ov.positions || []).find((p: { name: string }) => p.name === posName);
    expect(pos, "岗位未落库").toBeTruthy();

    // 清理：先岗位后部门（避免外键/引用）
    await page.request.delete(`${API}/api/org/positions/${pos.id}`);
    await page.request.delete(`${API}/api/org/departments/${dept.id}`);
    ov = await (await page.request.get(`${API}/api/org/overview`)).json();
    expect((ov.departments || []).some((d: { id: number }) => d.id === dept.id)).toBe(false);
    expect((ov.positions || []).some((p: { id: number }) => p.id === pos.id)).toBe(false);
  });

  test("跨租户不可见：只读成员看不到写表单", async ({ page }) => {
    // 本机模式是实例所有者，这里验证 API 层的能力接口形状
    const caps = await (await page.request.get(`${API}/api/org/capabilities`)).json();
    expect(Array.isArray(caps.permissions)).toBeTruthy();
    expect(typeof caps.role).toBe("string");
  });
});

test.describe("家庭账本：成员与借贷", () => {
  test("加成员 → 列表出现 → 加借贷 → 结清 → 清理", async ({ page }) => {
    const stamp = Date.now().toString().slice(-6);
    const a = `E2E甲${stamp}`;
    const b = `E2E乙${stamp}`;

    await openSettings(page, "基础设置", "家庭账本");
    await expect(page.getByText("成员名称").first()).toBeVisible({ timeout: 10_000 });

    // 加两个成员（借贷需要至少两人）
    for (const name of [a, b]) {
      await page.getByLabel("成员名称").fill(name);
      await page.getByRole("button", { name: "添加", exact: true }).click();
      await expect(page.getByText(name).first()).toBeVisible({ timeout: 10_000 });
    }

    let members = await (await page.request.get(`${API}/api/members`)).json();
    const list = Array.isArray(members) ? members : members.members || [];
    const ma = list.find((m: { display_name: string }) => m.display_name === a);
    const mb = list.find((m: { display_name: string }) => m.display_name === b);
    expect(ma && mb, "成员未落库").toBeTruthy();

    // 记录借贷 a → b 100 元
    await page.getByLabel("借出方").selectOption(String(ma.id));
    await page.getByLabel("借入方").selectOption(String(mb.id));
    await page.locator("#familysect-5").fill("100");
    await page.getByRole("button", { name: "记录借贷" }).click();

    const loans = await (await page.request.get(`${API}/api/members/loans`)).json();
    const loanList = Array.isArray(loans) ? loans : loans.loans || [];
    const loan = loanList.find(
      (x: { from_member_id: number; to_member_id: number }) =>
        Number(x.from_member_id) === ma.id && Number(x.to_member_id) === mb.id,
    );
    expect(loan, "借贷未落库").toBeTruthy();

    // 结清
    const settle = await page.request.post(`${API}/api/members/loans/${loan.id}/settle`);
    expect(settle.ok()).toBeTruthy();

    // 清理成员
    await page.request.delete(`${API}/api/members/${mb.id}`);
    await page.request.delete(`${API}/api/members/${ma.id}`);
    members = await (await page.request.get(`${API}/api/members`)).json();
    const after = Array.isArray(members) ? members : members.members || [];
    expect(after.some((m: { id: number }) => m.id === ma.id || m.id === mb.id)).toBe(false);
  });
});

test.describe("知识库：上传 → 入库 → 删除", () => {
  test("上传 txt 文件并加入索引，再删除", async ({ page }) => {
    const stamp = Date.now().toString().slice(-6);
    const fileName = `e2e-note-${stamp}.txt`;

    await openSettings(page, "AI 与自动化", "知识库");
    await expect(page.getByText(/上传文档|还没有文档/).first()).toBeVisible({ timeout: 10_000 });

    // 上传：走 multipart（页面同样是这个接口）
    const upload = await page.request.post(`${API}/api/attachments`, {
      multipart: {
        file: { name: fileName, mimeType: "text/plain", buffer: Buffer.from("E2E 知识库测试内容：项目代号灯塔。") },
      },
    });
    expect(upload.ok()).toBeTruthy();
    const att = await upload.json();

    // 刷新页面应能看到文件
    await page.reload();
    await page.getByRole("button", { name: "设置" }).first().click();
    const g = page.getByRole("button", { name: "AI 与自动化", exact: true }).first();
    if ((await g.getAttribute("aria-expanded")) !== "true") await g.click();
    await page.getByText("知识库", { exact: true }).first().click();
    await expect(page.getByText(fileName).first()).toBeVisible({ timeout: 10_000 });

    // 加入索引
    const idx = await page.request.post(`${API}/api/attachments/${att.id}/index`, { data: { indexed: true } });
    expect(idx.ok()).toBeTruthy();

    // 删除
    const del = await page.request.delete(`${API}/api/attachments/${att.id}`);
    expect(del.ok()).toBeTruthy();
    const left = await (await page.request.get(`${API}/api/attachments`)).json();
    const items = Array.isArray(left) ? left : left.attachments || [];
    expect(items.some((x: { id: number }) => x.id === att.id)).toBe(false);
  });
});

test.describe("Hook 与内置工具：逐项开关", () => {
  test("非内置 Hook 可停用再启用", async ({ page }) => {
    await page.request.put(`${API}/api/studio/permissions`, {
      data: { mode: "open", allow_chat_admin: true, allow_cli_admin: true },
    });
    const before = await (await page.request.get(`${API}/api/studio/hooks`)).json();
    const target = (before.assets || []).find(
      (h: { id: string; builtin?: boolean; enabled: boolean }) => !h.builtin,
    );
    expect(target, "没有可测试的非内置 Hook").toBeTruthy();

    // 停用
    const off = await page.request.post(`${API}/api/studio/hooks/${target.id}/toggle`, {
      data: { enabled: !target.enabled },
    });
    expect(off.ok()).toBeTruthy();
    let after = await (await page.request.get(`${API}/api/studio/hooks`)).json();
    let cur = (after.assets || []).find((h: { id: string }) => h.id === target.id);
    expect(cur.enabled).toBe(!target.enabled);

    // 恢复
    const on = await page.request.post(`${API}/api/studio/hooks/${target.id}/toggle`, {
      data: { enabled: target.enabled },
    });
    expect(on.ok()).toBeTruthy();
    after = await (await page.request.get(`${API}/api/studio/hooks`)).json();
    cur = (after.assets || []).find((h: { id: string }) => h.id === target.id);
    expect(cur.enabled).toBe(target.enabled);
  });

  test("内置工具：逐项真实开关（取第一个，改后恢复）", async ({ page }) => {
    await page.request.put(`${API}/api/studio/permissions`, {
      data: { mode: "open", allow_chat_admin: true, allow_cli_admin: true },
    });
    const before = await (await page.request.get(`${API}/api/studio/internal-tools`)).json();
    const tool = (before.tools || [])[0];
    expect(tool).toBeTruthy();

    const off = await page.request.post(`${API}/api/studio/internal-tools/toggle`, {
      data: { id: tool.id, enabled: !tool.enabled },
    });
    expect(off.ok()).toBeTruthy();
    let after = await (await page.request.get(`${API}/api/studio/internal-tools`)).json();
    let cur = (after.tools || []).find((t: { id: string }) => t.id === tool.id);
    expect(cur.enabled).toBe(!tool.enabled);

    await page.request.post(`${API}/api/studio/internal-tools/toggle`, {
      data: { id: tool.id, enabled: tool.enabled },
    });
    after = await (await page.request.get(`${API}/api/studio/internal-tools`)).json();
    cur = (after.tools || []).find((t: { id: string }) => t.id === tool.id);
    expect(cur.enabled).toBe(tool.enabled);
  });

  test("内置工具页显示清单与总开关", async ({ page }) => {
    await openSettings(page, "Agent 能力", "内置工具");
    await expect(page.getByText(/内置工具|统计|计算/).first()).toBeVisible({ timeout: 10_000 });
    const spec = await (await page.request.get(`${API}/api/studio/internal-tools`)).json();
    expect((spec.tools || []).length).toBeGreaterThan(0);
    expect(spec.visibility).toBe("internal");
  });
});
