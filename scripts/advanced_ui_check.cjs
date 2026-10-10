// Run against scripts/ui_fixture_server.py; synthetic inference, real UI and API.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:8765';

(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/#token=ui-test-only');
    const advanced = page.getByRole('button', {name: '高级问答', exact: true});
    const knowledge = page.getByRole('button', {name: '知识问答', exact: true});
    await advanced.waitFor({timeout: 5000});
    await page.waitForFunction(()=>document.querySelector('nav')?.textContent.includes('文档库2'));
    assert.deepEqual(await page.locator('nav button').allTextContents(),
      ['◌ 知识问答', '✧ 高级问答', '▤ 文档库2', '◇ 知识整理']);
    async function send(question) {
      await page.getByRole('textbox', {name: '输入问题'}).fill(question);
      const done = page.waitForResponse(r => r.url().endsWith('/api/chat'));
      await page.getByRole('button', {name: '发送问题'}).click();
      const response = await done;
      await page.getByRole('button', {name: '发送问题'}).waitFor();
      const sid = response.request().postDataJSON().session_id;
      const headers = {'X-Nord-Token': 'ui-test-only'};
      const status = await (await page.request.get(base + '/api/status', {headers})).json();
      headers['X-Knowledge-Sequence'] = String(status.sequence);
      const saved = await (await page.request.get(base + '/api/sessions/' + sid, {headers})).json();
      assert.equal(saved.messages.at(-2).content, question);
      return saved.messages.at(-1);
    }
    await advanced.click();
    assert.equal(await advanced.getAttribute('class'), 'active');
    assert.equal((await send('高级测试：结合常识解释 Alpha 保修期限')).mode, 'advanced');
    await page.getByRole('button', {name: /\[1\].*01_产品/}).click();
    await page.locator('.source-panel canvas').waitFor();
    await page.getByRole('button', {name: '关闭引用'}).click();
    await knowledge.click();
    assert.equal(await page.locator('.messages').count(), 0);
    assert.equal((await send('普通测试：Alpha 保修多久？')).mode, 'knowledge');
    await advanced.click();
    await page.getByText('高级测试：结合常识解释 Alpha 保修期限', {exact: true}).waitFor();
    assert.equal(await page.locator('.message.user').count(), 1);
    if (await page.getByRole('combobox', {name: '回答模型'}).locator('option[value="second"]').count()) {
      const switched = page.waitForResponse(r => r.url().endsWith('/api/models/switch'));
      await page.getByRole('combobox', {name: '回答模型'}).selectOption('second');
      assert.equal((await switched).status(), 200);
      await page.getByRole('heading', {name: '让专业知识与通用知识一起工作。'}).waitFor();
      assert.equal(await advanced.getAttribute('class'), 'active');
      await send('模型二高级测试：Alpha 保修多久？');
      await page.locator('.session-row button').filter({hasText: '普通测试：'}).first().click();
      await page.getByText('普通测试：Alpha 保修多久？', {exact: true}).waitFor();
      await advanced.click();
      await page.getByText('模型二高级测试：Alpha 保修多久？', {exact: true}).waitFor({timeout: 5000});
      assert.equal(await page.getByRole('combobox', {name: '回答模型'}).inputValue(), 'second');
    }
    await page.screenshot({path: 'artifacts/advanced-ui.png', fullPage: true});
    let releaseCreation, creationStarted;
    const creationGate = new Promise(resolve => {releaseCreation = resolve;});
    const started = new Promise(resolve => {creationStarted = resolve;});
    await page.route('**/api/sessions', async route => {
      if (route.request().method() === 'POST') {creationStarted(); await creationGate;}
      await route.continue();
    });
    await page.getByRole('button', {name: '＋ 新建对话'}).click();
    await started;
    try {assert.equal(await knowledge.isDisabled(), true, 'Mode navigation must lock while creating a session');}
    finally {releaseCreation();}
    await page.getByRole('heading', {name: '让专业知识与通用知识一起工作。'}).waitFor();
    assert.equal(await advanced.getAttribute('class'), 'active');
    await page.unroute('**/api/sessions');
    await page.reload();
    await page.locator('.session-row button').filter({hasText: '高级测试：结合常识解释 Alpha 保修期限'}).first().click();
    await page.getByText('高级测试：结合常识解释 Alpha 保修期限', {exact: true}).waitFor();
    assert.equal(await advanced.getAttribute('class'), 'active');
    await page.getByRole('button', {name: '文档库', exact: true}).click();
    await page.getByRole('checkbox', {name: /选择 .*01_产品/}).check();
    const topicResponse = page.waitForResponse(r => r.url().endsWith('/api/topic'));
    await page.getByRole('button', {name: /专题总结 · 已选 1/}).click();
    assert.equal((await topicResponse).status(), 200);
    await page.getByRole('button', {name: '发送问题'}).waitFor();
    assert.equal(await knowledge.getAttribute('class'), 'active');
    if (await page.getByRole('combobox', {name: '回答模型'}).locator('option[value="second"]').count()) {
      await advanced.click();
      for (const name of ['RadioMind · 流程知识库', '北境 · 产品与运营知识库']) {
        await page.getByRole('button', {name: '选择知识库', exact: true}).click();
        await page.getByRole('button', {name: '打开本机文件', exact: true}).click();
        await page.getByRole('heading', {name, exact: true}).waitFor();
        assert.equal(await advanced.getAttribute('class'), 'active');
        assert.equal(await page.locator('.messages').count(), 0);
        await knowledge.click();
        await advanced.click();
        assert.equal(await page.locator('.messages').count(), 0);
      }
    }
    assert.deepEqual(errors, []);
    console.log('Advanced UI passed: navigation, mode isolation, history, new session lock, model restoration, citations, topic routing, knowledge switching');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
