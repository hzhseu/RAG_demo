const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
const home=path.join(root,'artifacts','dual-exe-home-'+Date.now());
const child=spawn(path.join(root,'dist/NordRAG/nord-chat.exe'),['--no-browser','--knowledge',path.join(root,'dist/NordRAG/samples/demo.ragkb')],{cwd:root,windowsHide:true,env:{...process.env,NORDRAG_DATA:home,PATH:path.join(process.env.WINDIR,'System32'),PYTHONPATH:'',PYTHONHOME:''}});
let log='',browser;child.stdout.on('data',d=>log+=d);child.stderr.on('data',d=>log+=d);
const report={checks:[],externalRequests:[],errors:[]};
try {
 let url;for(let i=0;i<360;i++){url=log.match(/http:\/\/127\.0\.0\.1:\d+\/#token=[\w-]+/)?.[0];if(url)break;if(child.exitCode!==null)throw Error(log);await delay(500);}
 if(!url)throw Error('launch timeout '+log);
 const token=url.split('token=')[1],base=url.split('/#')[0];
 browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext({viewport:{width:1600,height:1000}});
 await context.route('**/*',route=>{const u=new URL(route.request().url());if(['http:','https:'].includes(u.protocol)&&u.hostname!=='127.0.0.1'){report.externalRequests.push(u.origin);return route.abort();}return route.continue();});
 const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url);
 await page.getByLabel('回答模型',{exact:true}).waitFor();
 await page.waitForFunction(()=>document.querySelector('select[aria-label="回答模型"]').value==='qwen35-4b',null,{timeout:120000});
 const request=async(endpoint,method='GET',data,sequence)=>{
  const status=await (await fetch(base+'/api/status',{headers:{'X-Nord-Token':token}})).json();
  return fetch(base+'/api'+endpoint,{method,headers:{'X-Nord-Token':token,'Content-Type':'application/json','X-Knowledge-Sequence':String(status.sequence),'X-Model-Sequence':String(sequence??status.model_sequence)},...(data?{body:JSON.stringify(data)}:{})});
 };
 const initial=await (await request('/status')).json();report.initial=initial;
 assert.equal(initial.model_id,'qwen35-4b');
 async function ask(q){await page.getByLabel('输入问题',{exact:true}).fill(q);await page.getByLabel('发送问题',{exact:true}).click();await page.getByRole('button',{name:'■ 停止'}).waitFor({state:'hidden',timeout:180000});assert.equal(await page.locator('.error-banner').count(),0);}
 await ask('Alpha 的标准保修期限是多少？');assert.match(await page.locator('.message.assistant').last().innerText(),/24/);
 await ask('这个期限从什么时候开始计算？');assert.equal(await page.locator('.message.assistant').count(),2);report.checks.push('Qwen3.5 RAG two turns');
 const oldSessions=await (await request('/sessions')).json(),newSid=oldSessions[0].id;
 await page.locator('.inline-citation').first().click();await page.locator('.source-panel canvas').waitFor();await page.waitForFunction(()=>document.querySelector('.source-panel canvas')?.width>300);report.checks.push('old KB citations and original PDF preview');await page.getByLabel('关闭引用',{exact:true}).click();
 await page.getByLabel('回答模型',{exact:true}).selectOption('default');
 await page.waitForFunction(()=>!document.querySelector('select[aria-label="回答模型"]').disabled,null,{timeout:120000});
 await ask('Alpha 的标准保修期限是多少？');assert.match(await page.locator('.message.assistant').last().innerText(),/24/);report.checks.push('old model switch and new session');
 const stale=await request('/chat','POST',{session_id:newSid,question:'stale'},initial.model_sequence);assert.equal(stale.status,409);report.checks.push('stale browser conflict');
 const active=await request('/sessions/'+newSid+'/activate','POST');assert.equal(active.status,200);await page.reload();await page.waitForFunction(()=>document.querySelector('select[aria-label="回答模型"]')?.value==='qwen35-4b');report.checks.push('resume original model');
 const docs=await (await request('/documents')).json();
 const topic=await request('/topic','POST',{session_id:newSid,document_ids:[docs[0].id]});assert.equal(topic.status,200);assert.match(await topic.text(),/"type": "done"/);report.checks.push('real topic summary');
 const exported=await (await request('/sessions/'+newSid+'/export')).json();assert.equal(exported.model.id,'qwen35-4b');assert.ok(exported.messages.filter(m=>m.role==='assistant').every(m=>m.model.id==='qwen35-4b'));report.checks.push('model metadata export');
 await page.screenshot({path:path.join(root,'artifacts/dual-model-main.png'),fullPage:true});
 report.pass=true;assert.deepEqual(report.externalRequests,[]);assert.deepEqual(report.errors,[]);
 fs.writeFileSync(path.join(root,'artifacts/dual-model-exe.json'),JSON.stringify(report,null,2));console.log('Dual-model packaged browser acceptance passed');
} finally {if(browser)await browser.close();if(child.pid&&child.exitCode===null)spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
