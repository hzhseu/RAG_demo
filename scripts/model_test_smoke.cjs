// Real packaged application + existing Qwen weights; no knowledge base.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));

(async()=>{
  const runtimeRoot=path.join(root,'dist/NordRAG');
  const runtime=JSON.parse(fs.readFileSync(path.join(runtimeRoot,'runtime.json'),'utf8'));
  const catalog=path.join(root,'artifacts/model-tester-smoke-models.json');
  fs.writeFileSync(catalog,JSON.stringify({models:[
    {id:'qwen-small-context',name:'Qwen · 4096 上下文测试配置',path:path.resolve(runtimeRoot,runtime.chat_model),sha256:runtime.chat_model_sha256,context:4096,threads:4},
    {id:'missing',name:'缺失文件测试',path:path.join(root,'artifacts/no-such-model.gguf'),sha256:'0'.repeat(64)}
  ]}));
  const processHandle=spawn(path.join(root,'dist/ModelTester/ModelTester.exe'),['--no-browser','--models',catalog],{cwd:root,windowsHide:true});
  let log='',browser;
  processHandle.stdout.on('data',data=>log+=data.toString());
  processHandle.stderr.on('data',data=>log+=data.toString());
  processHandle.on('error',error=>log+=error.message);
  const cases=[],errors=[];
  try {
    let url;
    for(let i=0;i<180;i++) {
      url=log.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[\w-]+/)?.[0];
      if(url)break;
      if(processHandle.exitCode!==null)throw Error(log);
      await delay(500);
    }
    if(!url)throw Error('Startup timeout: '+log);
    browser=await chromium.launch({headless:true,channel:'msedge'});
    const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
    page.on('pageerror',error=>errors.push(error.message));
    page.on('request',request=>{const parsed=new URL(request.url());if(['http:','https:'].includes(parsed.protocol)&&parsed.hostname!=='127.0.0.1')errors.push('External request: '+parsed.origin);});
    await page.goto(url);
    await page.waitForFunction(()=>!document.getElementById('run').disabled);
    assert.match(await page.locator('#model').innerText(),/Qwen3.5-4B-Q4_K_M/);
    assert.equal(await page.locator('#model-select option').count(),4);
    async function newChat() {
      await page.locator('#new-session').click();
      await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('status').textContent==='就绪');
      assert.equal(await page.locator('.turn').count(),0);
    }
    async function run(mode,question,material,instruction,expected) {
      if(mode!==null)await page.locator('#mode').selectOption(mode);
      if(mode!=='summary')await page.locator('#question').fill(question);
      if(material!==null)await page.locator('#material').fill(material);
      await page.locator('#instruction').fill(instruction);
      await page.locator('#max-tokens').fill('128');
      await page.locator('#run').click();
      await page.waitForFunction(()=>!document.getElementById('run').disabled&&['已完成','测试失败','已停止'].includes(document.getElementById('status').textContent),{},{timeout:180000});
      assert.equal(await page.locator('#status').innerText(),'已完成',await page.locator('#result-note').innerText());
      const output=await page.locator('#output').innerText();assert.match(output,expected);
      const downloading=page.waitForEvent('download');await page.locator('#export').click();
      const download=await downloading;
      const file=path.join(root,'artifacts','model-test-round-'+cases.length+'.json');await download.saveAs(file);
      const record=JSON.parse(fs.readFileSync(file,'utf8'));
      assert.equal(record.text,output);assert.ok(record.first_token_seconds>=0);assert.ok(record.elapsed_seconds>0);assert.ok(record.output_tokens>0);
      cases.push(record);console.log(JSON.stringify({mode:record.request.mode,text:output,seconds:record.elapsed_seconds}));
      return record;
    }
    const first=await run('chat','本次测试的暗号是松鼠4826。请记住。',null,'只回答已记住。',/记住/);
    const second=await run(null,'刚才我告诉你的暗号是什么？',null,'只回答暗号。',/松鼠\s*4826/);
    assert.equal(second.session_id,first.session_id);assert.equal(second.messages.length,4);
    assert.equal(await page.locator('.turn').count(),2);
    await page.reload();await page.waitForFunction(()=>!document.getElementById('run').disabled);
    assert.equal(await page.locator('.turn').count(),2);
    await run(null,'把暗号中的数字单独写出来。',null,'只回答数字。',/4826/);
    await page.screenshot({path:path.join(root,'artifacts/model-tester-desktop.png'),fullPage:true});
    const sessionDownload=page.waitForEvent('download');await page.locator('#export-session').click();
    const exported=await sessionDownload;const sessionFile=path.join(root,'artifacts/model-test-conversation.json');await exported.saveAs(sessionFile);
    const transcript=JSON.parse(fs.readFileSync(sessionFile,'utf8'));assert.equal(transcript.turns.length,3);assert.equal(transcript.messages.length,7);
    await newChat();
    const isolated=await run('chat','7加5等于多少？',null,'只回答数字。',/12/);assert.equal(isolated.messages.length,2);
    await newChat();
    await run('grounded','保修期是多久？','星河设备标准保修期为24个月，人为损坏不在保修范围内。','一句话回答。',/24/);
    await run(null,'人为损坏呢？',null,'一句话回答。',/不/);
    await newChat();
    await run('summary','','第三季度销售额120万元，环比增长20%。新增客户30家。','用一句话总结，保留全部数字。',/120/);
    await run(null,'刚才材料中的新增客户数量是多少？',null,'只回答数字。',/30/);
    await page.locator('#model-select').selectOption('qwen-small-context');
    await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('config').textContent.includes('4096'));
    assert.equal(await page.locator('.turn').count(),0);
    const switched=await run('chat','3加4等于多少？',null,'只回答数字。',/7/);
    assert.equal(switched.model_id,'qwen-small-context');assert.equal(switched.parameters.context,4096);assert.equal(switched.messages.length,2);
    await page.locator('#model-select').selectOption('missing');
    await page.waitForFunction(()=>!document.getElementById('run').disabled&&!document.getElementById('notice').hidden);
    assert.equal(await page.locator('#model-select').inputValue(),'qwen-small-context');
    assert.equal(await page.locator('.turn').count(),1);
    await page.locator('#history-list button').filter({hasText:'本次测试的暗号'}).click();
    await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('model-select').value==='qwen35-4b');
    await run(null,'再说一遍我最开始告诉你的暗号。',null,'只回答暗号。',/松鼠\s*4826/);
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(root,'artifacts/model-tester-mobile.png'),fullPage:true});await page.setViewportSize({width:1440,height:1100});
    await newChat();await page.locator('#question').fill('请详细介绍中国古代历史，至少写三千字。');await page.locator('#max-tokens').fill('4096');await page.locator('#run').click();
    await page.waitForFunction(()=>document.getElementById('status').textContent==='正在生成…',{},{timeout:120000});
    await page.locator('#stop').click();
    await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('status').textContent==='已停止',{},{timeout:30000});
    const afterCancel=await run('chat','9减4等于多少？',null,'只回答数字。',/5/);assert.equal(afterCancel.messages.length,2);
    // At the session cap, deleting a conversation must free a slot.
    await page.evaluate(async()=>{
      const token=new URLSearchParams(location.hash.slice(1)).get('token');
      const headers={'X-Nord-Token':token,'Content-Type':'application/json'};
      const state=await (await fetch('/api/status',{headers})).json();
      for(let count=state.sessions.length;count<30;count++) {
        const response=await fetch('/api/sessions',{method:'POST',headers,body:'{}'});
        if(!response.ok)throw Error('Could not fill session capacity');
      }
    });
    await page.reload();await page.waitForFunction(()=>!document.getElementById('run').disabled);
    assert.equal(await page.locator('#history-list button').count(),30);
    page.once('dialog',dialog=>dialog.accept());await page.locator('#delete-session').click();
    await page.waitForFunction(()=>!document.getElementById('new-session').disabled);
    assert.equal(await page.locator('#history-list button').count(),29,'Deleting must free a session slot');
    await page.locator('#model-select').selectOption('qwen-small-context');
    await page.waitForFunction(()=>!document.getElementById('run').disabled&&document.getElementById('model-select').value==='qwen-small-context');
    assert.equal(await page.locator('#history-list button').count(),30);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(root,'artifacts/model-tester-smoke.json'),JSON.stringify({pass:true,realModel:true,packaged:true,modelSwitchNote:'Qwen3.5 default and retained Qwen3 weights; shared registry and optional custom profiles.',checks:['multi-turn recall','refresh retains context','new-session isolation','material followup','summary followup','model profile switch','bad-model rollback','resume old-model session','session JSON export','responsive layout','cancel excludes partial turn','no remote requests'],cases,pageErrors:errors},null,2));
    console.log('Packaged continuous-conversation smoke passed');
  } finally {
    if(browser)await browser.close();
    if(processHandle.pid&&processHandle.exitCode===null)spawnSync('taskkill',['/PID',String(processHandle.pid),'/T','/F'],{windowsHide:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
