'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
const terminal = new Set(['done', 'cancelled', 'error']);
const labels = {loading:'正在加载模型…', generating:'正在生成…', cancelling:'正在停止…', done:'已完成', cancelled:'已停止', error:'测试失败'};
const modes = {chat:'自由问答', grounded:'材料问答', summary:'摘要'};
let current=null, session=null, active=null, polling=false, locked=true, info=null;

function notice(text='') { $('notice').textContent=text; $('notice').hidden=!text; }
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{'X-Nord-Token':token,'Content-Type':'application/json'}});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:(data.detail||[]).map(x=>x.msg).join('；')||'请求失败');
  return data;
}
function hasHistory() {return !!session?.messages.length;}
function modeChanged() {
  const mode=$('mode').value, followup=hasHistory();
  $('material-group').hidden=mode==='chat';
  $('material').required=mode!=='chat'&&!followup;
  $('question-group').hidden=mode==='summary'&&!followup;
  $('question').required=mode!=='summary'||followup;
  $('question-label').textContent=followup?'继续提问':'问题';
  $('question').placeholder=followup?'例如：请继续解释，或将刚才的回答改写成三点。':'输入你的问题…';
  $('mode-hint').textContent=followup?'后续问题会携带已完成的问答。更改模式或材料，请新建对话。':mode==='chat'?'直接向模型提问，后续问题会携带本会话的历史问答。':mode==='grounded'?'先提供材料和问题，回答后可以继续追问。':'先生成摘要，之后可以要求补充、解释或改写。';
  $('run').textContent=followup?'发送追问 ↗':'开始测试 ↗';
  $('mode').disabled=locked||followup;
  $('material').disabled=locked||followup;
  $('example').disabled=locked||followup;
}
function busy(value) {
  locked=value;
  for(const element of $('test-form').elements) element.disabled=value;
  $('run').disabled=value||!session;
  $('stop').disabled=!active;
  $('new-session').disabled=value;
  $('model-select').disabled=value;
  $('delete-session').disabled=value||!session;
  $('export-session').disabled=value||!session?.turns.length;
  modeChanged(); renderHistory();
}
function seconds(value) {return value===null||value===undefined?'—':value.toFixed(2)+' s';}
function renderConversation() {
  const box=$('conversation'), bottom=box.scrollHeight-box.scrollTop-box.clientHeight<70, previousTop=box.scrollTop;
  box.replaceChildren();
  const turns=session?.turns||[];
  if(!turns.length) {
    const empty=document.createElement('div');empty.id='output';empty.className='empty';
    empty.textContent='你的对话会显示在这里。点击“填入示例”，即可开始。';box.append(empty);
  }
  turns.forEach((record,index)=>{
    const turn=document.createElement('article');turn.className='turn';
    const user=document.createElement('div');user.className='bubble user';
    const userLabel=document.createElement('strong');userLabel.textContent=`你 · 第${index+1}轮`;
    const question=document.createElement('div');question.textContent=record.request.question||'请根据要求总结提供的材料。';
    user.append(userLabel,question);
    const answer=document.createElement('div');answer.className='bubble assistant';
    const answerLabel=document.createElement('strong');answerLabel.textContent='模型';
    const text=document.createElement('div');if(index===turns.length-1)text.id='output';
    text.textContent=record.text||(terminal.has(record.status)?'未生成文字':'正在处理，请稍候…');
    answer.append(answerLabel,text);
    if(record.status==='error'||record.status==='cancelled') {
      const note=document.createElement('small');note.textContent=`${labels[record.status]} · 此轮不带入后续上下文`;answer.append(note);
    } else if(record.finish_reason==='length') {
      const note=document.createElement('small');note.textContent='已达到输出上限，可继续追问。';answer.append(note);
    }
    turn.append(user,answer);box.append(turn);
  });
  if(bottom)box.scrollTop=box.scrollHeight;else box.scrollTop=previousTop;
  $('session-title').textContent=session?.title||'新对话';
  $('session-info').textContent=session?`${session.turns.length} 轮 · ${session.model_name}`:'';
}
function renderRecord(record) {
  current=record;
  if(session) {
    const index=session.turns.findIndex(r=>r.id===record.id);
    if(index<0)session.turns.push(record);else session.turns[index]=record;
  }
  $('status').textContent=labels[record.status]||record.status;
  $('load').textContent=seconds(record.load_seconds);
  $('first').textContent=seconds(record.first_token_seconds);
  $('elapsed').textContent=terminal.has(record.status)?seconds(record.elapsed_seconds):'运行中';
  $('tokens').textContent=record.output_tokens??'—';
  $('result-note').textContent=record.error||(record.finish_reason==='length'?'已达到输出上限，回答可能未完。可以继续要求模型补充。':record.status==='cancelled'?'已停止。该轮不会带入后续上下文。':'');
  $('copy').disabled=!record.text;
  $('export').disabled=!terminal.has(record.status);
  renderConversation();
}
function resetResult() {
  current=null;$('status').textContent='就绪';$('result-note').textContent='';
  for(const id of ['load','first','elapsed','tokens'])$(id).textContent='—';
  $('copy').disabled=true;$('export').disabled=true;renderConversation();
}
function restoreSession(value) {
  session=value;
  $('mode').value=session.mode;$('material').value=session.material;$('question').value='';
  const last=session.turns.at(-1);
  $('instruction').value=last?.request.instruction||'';
  $('max-tokens').value=last?.request.max_tokens||768;
  if(last)renderRecord(last);else resetResult();
  modeChanged();
}
function renderHistory() {
  const list=$('history-list');list.replaceChildren();
  for(const item of info?.sessions||[]) {
    const button=document.createElement('button');button.type='button';
    button.textContent=`${modes[item.mode]} · ${item.title}`;button.title=`${item.model_name} · ${item.title}`;
    button.classList.toggle('selected',item.id===session?.id);button.disabled=locked;
    button.addEventListener('click',()=>changeSession('/api/sessions/'+item.id+'/activate'));list.append(button);
  }
}
async function refreshInfo() {
  info=await api('/api/status');
  $('model').textContent=info.model;$('config').textContent=`CPU ${info.threads} 线程 · 上下文 ${info.context} tokens`;
  const select=$('model-select');select.replaceChildren();
  for(const model of info.models) {const option=document.createElement('option');option.value=model.id;option.textContent=model.name;select.append(option);}
  select.value=info.model_id;renderHistory();
}
async function changeSession(path,body) {
  notice();busy(true);
  try {
    const value=await api(path,{method:'POST',body:body?JSON.stringify(body):undefined});
    restoreSession(value);await refreshInfo();
  } catch(error){notice(error.message);if(info)$('model-select').value=info.model_id;}
  finally{busy(false);}
}
async function poll() {
  if(polling||!active)return;polling=true;
  try {
    const record=await api('/api/tests/'+active);notice();renderRecord(record);
    if(terminal.has(record.status)) {
      session=await api('/api/sessions/'+record.session_id);
      await refreshInfo();active=null;
      if(record.status==='done')$('question').value='';
      busy(false);renderConversation();
    }
  } catch(error){notice('读取进度失败：'+error.message+'。重新连接后会继续显示。');}
  finally{polling=false;if(active)setTimeout(poll,350);}
}
$('mode').addEventListener('change',modeChanged);
$('new-session').addEventListener('click',()=>changeSession('/api/sessions',{model_id:info.model_id}));
$('model-select').addEventListener('change',()=>changeSession('/api/sessions',{model_id:$('model-select').value}));
$('delete-session').addEventListener('click',async()=>{
  if(!session||!confirm('删除当前会话？未导出的记录将被清除。'))return;
  busy(true);notice();
  try {
    await api('/api/sessions/'+session.id,{method:'DELETE'});
    session=null;resetResult();await refreshInfo();
    const remaining=info.sessions.find(item=>item.model_id===info.model_id)||info.sessions[0];
    const next=remaining
      ?await api('/api/sessions/'+remaining.id+'/activate',{method:'POST'})
      :await api('/api/sessions',{method:'POST',body:JSON.stringify({model_id:info.model_id})});
    restoreSession(next);await refreshInfo();
  } catch(error){notice(error.message+(session?'':'。请新建对话或选择其他会话。'));}
  finally{busy(false);}
});
$('example').addEventListener('click',()=>{
  const mode=$('mode').value;
  $('material').value='星河设备的标准保修期为24个月，自交付日起计算。人为损坏不在保修范围内。2025年第三季度销售额为120万元，比第二季度增长20%。售后服务时间为工作日9:00至18:00。';
  $('question').value=mode==='chat'?'请用一个生活中的例子解释什么是向量检索。':'设备保修多久？人为损坏能保修吗？';
  $('instruction').value=mode==='summary'?'用中文分3点总结，保留关键数字，控制在150字以内。':'用中文简短回答。';
});
$('test-form').addEventListener('submit',async event=>{
  event.preventDefault();notice();busy(true);
  $('status').textContent='正在提交…';$('copy').disabled=true;$('export').disabled=true;$('result-note').textContent='';
  for(const id of ['load','first','elapsed','tokens'])$(id).textContent='—';
  try {
    const mode=$('mode').value;
    const data=await api('/api/tests',{method:'POST',body:JSON.stringify({session_id:session.id,mode,
      question:mode==='summary'&&!hasHistory()?'':$('question').value,
      material:mode==='chat'||hasHistory()?'':$('material').value,
      instruction:$('instruction').value,max_tokens:Number($('max-tokens').value)})});
    active=data.id;$('stop').disabled=false;await poll();
  } catch(error){notice(error.message);$('status').textContent='提交失败';busy(false);}
});
$('stop').addEventListener('click',async()=>{
  if(!active)return;$('stop').disabled=true;
  try{await api('/api/tests/'+active+'/cancel',{method:'POST'});$('status').textContent='正在停止…';}
  catch(error){notice(error.message);$('stop').disabled=false;}
});
$('copy').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(current.text);$('copy').textContent='已复制';setTimeout(()=>$('copy').textContent='复制最新回答',1200);}
  catch{notice('复制失败，请在输出区域选择文字后复制。');}
});
function download(data,name) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('export').addEventListener('click',()=>download({format:'radiomind-model-test-v2',...current},'model-test-'+current.id.slice(0,8)+'.json'));
$('export-session').addEventListener('click',()=>download({format:'radiomind-model-session-v1',...session},'model-session-'+session.id.slice(0,8)+'.json'));
async function init() {
  busy(true);
  try {
    await refreshInfo();
    const value=info.session_id?await api('/api/sessions/'+info.session_id):await api('/api/sessions',{method:'POST',body:'{}'});
    restoreSession(value);await refreshInfo();active=info.active_id;
    if(active){busy(true);await poll();}else busy(false);
  } catch(error){notice(error.message+'。请检查启动窗口是否仍在运行。');}
}
modeChanged();init();
