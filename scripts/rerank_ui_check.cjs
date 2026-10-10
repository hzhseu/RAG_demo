// Synthetic inference exercises the actual UI/API; real engines are tested separately.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const base = process.env.UI_BASE_URL || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror', e=>errors.push(e.message));
    await page.goto(base+'/#token=ui-test-only');
    const toggle=page.getByRole('checkbox',{name:'检索重排'});
    await toggle.waitFor({timeout:5000});
    assert.equal(await toggle.isChecked(),true);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/sessions')&&r.request().method()==='POST');
    await toggle.click();
    const hybrid=await (await response).json();
    assert.equal(hybrid.retrieval_mode,'hybrid');
    await page.waitForFunction(()=>!document.querySelector('[aria-label="检索重排"]').checked);
    async function send(text) {
      let release, started;
      const gate=new Promise(resolve=>{release=resolve;});
      const entered=new Promise(resolve=>{started=resolve;});
      await page.route('**/api/chat',async route=>{started();await gate;await route.continue();});
      await page.getByRole('textbox',{name:'输入问题'}).fill(text);
      const chat=page.waitForResponse(r=>r.url().endsWith('/api/chat'));
      await page.getByRole('button',{name:'发送问题'}).click();
      await entered;
      assert.equal(await toggle.isDisabled(),true);
      release();
      await chat;
      await page.getByRole('button',{name:'发送问题'}).waitFor();
      await page.unroute('**/api/chat');
    }
    await send('重排关闭对照 Alpha 保修');
    await page.getByText('原混合检索',{exact:true}).waitFor();
    await toggle.click();
    await page.waitForFunction(()=>document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    assert.equal(await page.locator('.message.user').count(),0);
    await send('重排开启对照 Alpha 保修');
    await page.getByText(/重排暂不可用，已使用原混合检索/).waitFor();
    await page.locator('.session-row button').filter({hasText:'重排关闭对照'}).first().click();
    await page.waitForFunction(()=>!document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    assert.equal(await toggle.isChecked(),false);
    await page.getByRole('button',{name:'高级问答',exact:true}).click();
    await toggle.click();
    await page.waitForFunction(()=>document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    await send('高级重排对照 Alpha 保修');
    await page.getByRole('button',{name:'知识问答',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    assert.equal(await toggle.isChecked(),false);
    await page.getByLabel('回答模型',{exact:true}).selectOption('second');
    await page.waitForFunction(()=>!document.querySelector('[aria-label="回答模型"]').disabled);
    assert.equal(await toggle.isChecked(),false);
    await page.getByRole('button',{name:'选择知识库',exact:true}).click();
    await page.getByRole('button',{name:'打开本机文件',exact:true}).click();
    await page.getByRole('dialog',{name:'选择知识库'}).waitFor({state:'hidden'});
    assert.equal(await toggle.isChecked(),false);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:'artifacts/rerank-ui.png',fullPage:true});
    console.log('Reranking UI: default, toggle, session restore, mode restore and fallback PASS');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
