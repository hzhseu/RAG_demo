// Packaged real-model acceptance, with developer runtimes removed from PATH.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const home=path.join(root,'artifacts','rerank-exe-'+Date.now());
  const child=spawn(path.join(root,'dist/NordRAG/nord-chat.exe'),['--no-browser','--knowledge',path.join(root,'dist/NordRAG/samples/demo.ragkb')],{
    cwd:root,windowsHide:true,env:{...process.env,NORDRAG_DATA:home,PATH:path.join(process.env.WINDIR,'System32'),PYTHONPATH:'',PYTHONHOME:''}});
  let log='',browser;
  child.stdout.on('data',d=>log+=d);child.stderr.on('data',d=>log+=d);
  const report={real_models:true,clean_path:true,clean_windows:false,checks:[],external_requests:[],errors:[],answers:[]};
  try {
    let url;
    for(let i=0;i<480;i++){
      url=log.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[\w-]+/)?.[0];
      if(url)break;
      if(child.exitCode!==null)throw Error(log);
      await delay(500);
    }
    if(!url)throw Error('Packaged startup timeout: '+log);
    const base=url.split('/#')[0],token=url.split('token=')[1];
    browser=await chromium.launch({headless:true,channel:'msedge'});
    const context=await browser.newContext({viewport:{width:1500,height:1000}});
    await context.route('**/*',route=>{
      const u=new URL(route.request().url());
      if(['http:','https:'].includes(u.protocol)&&u.hostname!=='127.0.0.1'){
        report.external_requests.push(u.origin);return route.abort();
      }
      return route.continue();
    });
    const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
    page.setDefaultTimeout(180000);
    await page.goto(url);
    const toggle=page.getByRole('checkbox',{name:'检索重排'});
    await page.waitForFunction(()=>document.querySelector('[aria-label="检索重排"]')&&!document.querySelector('[aria-label="检索重排"]').disabled,null,{timeout:180000});
    assert.equal(await toggle.isChecked(),true);
    async function session(id){
      const headers={'X-Nord-Token':token};
      const status=await (await fetch(base+'/api/status',{headers})).json();
      headers['X-Knowledge-Sequence']=String(status.sequence);
      headers['X-Model-Sequence']=String(status.model_sequence);
      return (await fetch(base+'/api/sessions/'+id,{headers})).json();
    }
    async function ask(question,mode){
      await page.getByRole('textbox',{name:'输入问题'}).fill(question);
      const response=page.waitForResponse(r=>r.url().endsWith('/api/chat'));
      await page.getByRole('button',{name:'发送问题'}).click();
      const r=await response;
      await page.getByRole('button',{name:'发送问题'}).waitFor();
      assert.equal(await page.locator('.error-banner').count(),0);
      const saved=await session(r.request().postDataJSON().session_id);
      const answer=saved.messages.at(-1);
      assert.equal(answer.retrieval_mode,mode);assert.equal(answer.rerank_fallback,false);
      assert.match(answer.content,/120\.50/);assert.ok(answer.citations.length);
      report.answers.push({mode,answer:answer.content,rerank_seconds:answer.rerank_seconds,citations:answer.citations});
      return saved.id;
    }
    const rerankId=await ask('Alpha 收入是多少 EUR？请引用表格。','rerank');
    await page.getByText(/已重排证据/).waitFor();
    assert.ok(report.answers[0].citations.every(c=>Number.isFinite(c.rerank_score)));
    await page.locator('.inline-citation').first().click();
    await page.waitForFunction(()=>document.querySelector('.source-panel canvas')?.width>300);
    await page.getByLabel('关闭引用',{exact:true}).click();
    report.checks.push('real reranker, generated numeric answer, original-page preview');
    await toggle.click();
    await page.waitForFunction(()=>!document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    await ask('Alpha 收入是多少 EUR？请引用表格。','hybrid');
    await page.getByText('原混合检索',{exact:true}).waitFor();
    report.checks.push('hybrid baseline via new session');
    await page.locator('.session-row button').filter({hasText:'Alpha 收入是多少'}).nth(1).click();
    await page.waitForFunction(()=>document.querySelector('[aria-label="检索重排"]').checked&&!document.querySelector('[aria-label="检索重排"]').disabled);
    assert.equal((await session(rerankId)).retrieval_mode,'rerank');
    report.checks.push('rerank history restored');
    await page.screenshot({path:path.join(root,'artifacts/rerank-packaged.png'),fullPage:true});
    assert.deepEqual(report.external_requests,[]);assert.deepEqual(report.errors,[]);
    report.pass=true;
    console.log('Packaged reranking acceptance PASS');
  } catch(e) {report.pass=false;report.error=String(e);throw e;}
  finally {
    fs.writeFileSync(path.join(root,'artifacts/rerank-exe.json'),JSON.stringify(report,null,2));
    if(browser)await browser.close();
    if(child.pid&&child.exitCode===null)spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true});
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
