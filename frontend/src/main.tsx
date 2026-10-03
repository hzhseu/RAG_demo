import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import './style.css';
import './fonts.css';
import { createApiClient } from './apiClient';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || sessionStorage.getItem('nord-token') || '';
if (token) sessionStorage.setItem('nord-token', token);
history.replaceState(null, '', location.pathname);
const client = createApiClient(token, () => window.dispatchEvent(new Event('knowledge-changed')));
const api = client.request;
const apiJson = client.json;

type Citation = {id: string; doc_id: string; doc_name?: string; page: number; text: string; kind: string};
type Message = {role: string; content: string; citations?: Citation[]; supported?: boolean};
type Session = {id: string; title: string};
type Document = {id: string; name: string; pages: number; summary: string; tags: string[]; category: string; citations: Citation[]};
type Status = {app_version: string; model: string; sequence: number; busy: boolean; switching: boolean; startup_error?: string; knowledge: {name: string; version: string; built_at: string; documents: number; pages: number} | null};

function Preview({citation, onClose}: {citation: Citation; onClose: () => void}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let abandoned = false;
    let task: ReturnType<typeof pdfjs.getDocument> | undefined;
    setLoading(true); setError('');
    (async () => {
      const response = await api(`/documents/${citation.doc_id}/preview`);
      task = pdfjs.getDocument({data: new Uint8Array(await response.arrayBuffer()), useSystemFonts: true});
      const pdf = await task.promise;
      const page = await pdf.getPage(citation.page);
      if (abandoned || !canvas.current) return;
      const viewport = page.getViewport({scale: 1.2});
      canvas.current.width = viewport.width; canvas.current.height = viewport.height;
      await page.render({canvas: canvas.current, viewport}).promise;
      if (!abandoned) setLoading(false);
    })().catch(e => {if (!abandoned) {setError(String(e)); setLoading(false);}});
    return () => {abandoned = true; if (task) void task.destroy();};
  }, [citation.doc_id, citation.page]);
  return <aside className="source-panel"><div className="panel-heading"><span>引用来源</span><button className="icon" onClick={onClose} aria-label="关闭引用">×</button></div><h3>{citation.doc_name || '原始文档'}</h3><span className="eyebrow">SLIDE {String(citation.page).padStart(2, '0')}</span><div className="slide-preview">{loading && <p>正在加载原页…</p>}<canvas ref={canvas}/>{error && <p role="alert">{error}</p>}</div><div className="evidence-heading">证据片段 {citation.kind === 'ocr' && <span className="badge">OCR 识别</span>}</div><blockquote>{citation.text}</blockquote><p className="muted small">原页为离线转换预览。涉及数字或图片文字时，请核对表头、单位与原始资料。</p></aside>;
}

type RecentKnowledge = {id: string; name: string; path: string; current: boolean};
function KnowledgePicker({recent, loading, error, onChoose, onClose}: {
  recent: RecentKnowledge[]; loading: boolean; error: string;
  onChoose: (id?: string) => void; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {dialog.current?.showModal(); return () => dialog.current?.close();}, []);
  return <dialog ref={dialog} className="modal knowledge-picker" aria-labelledby="knowledge-picker-title"
    onCancel={e=>{e.preventDefault();if(!loading)onClose();}}>
    <div className="picker-heading"><h2 id="knowledge-picker-title">选择知识库</h2><button className="icon" aria-label="关闭知识库选择" disabled={loading} onClick={onClose}>×</button></div>
    <p>打开本机的 .ragkb 文件，或从最近使用中切换。</p>
    <button className="primary" autoFocus disabled={loading} onClick={()=>onChoose()}>打开本机文件</button>
    {loading&&<p className="picker-progress" role="status"><span className="spinner"/> 正在选择、校验并加载知识库，请稍候…</p>}
    {error&&<p className="picker-error" role="alert">{error}</p>}
    <h3>最近使用</h3><div className="recent-knowledge">{recent.map(item=><button className={'recent-knowledge-item'+(item.current?' current':'')} disabled={loading||item.current} key={item.id} onClick={()=>onChoose(item.id)}>
      <span>{item.name}{item.current&&<small>当前知识库</small>}</span><small className="knowledge-path">{item.path}</small>
    </button>)}{!recent.length&&<p className="muted">暂无记录，请先打开知识库文件。</p>}</div>
    <p className="small">切换后，对话和标签仍保存在各自知识库中。</p>
  </dialog>;
}

function App() {
  const [status, setStatus] = useState<Status>();
  const [docs, setDocs] = useState<Document[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sid, setSid] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [view, setView] = useState<'chat'|'documents'|'organize'>('chat');
  const [input, setInput] = useState('');
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [citation, setCitation] = useState<Citation>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState('');
  const [progress, setProgress] = useState('');
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState<Document>();
  const [category, setCategory] = useState('');
  const [tags, setTags] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [recent, setRecent] = useState<RecentKnowledge[]>([]);
  const [switching, setSwitching] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [pickerError, setPickerError] = useState('');
  const hydratedSequence = useRef<number | undefined>(undefined);
  const refreshId = useRef(0);
  const refreshTask = useRef<Promise<void> | null>(null);
  const locked = busy || switching || exporting || !status?.knowledge;
  const bottom = useRef<HTMLDivElement>(null);
  const loadSessions = async () => setSessions(await apiJson('/sessions'));
  async function refreshKnowledge(force = false): Promise<void> {
    if (refreshTask.current) {
      await refreshTask.current;
      if (!force) return;
    }
    const task = refreshSnapshot(force);
    refreshTask.current = task;
    try {await task;} finally {if(refreshTask.current === task)refreshTask.current = null;}
  }
  async function refreshSnapshot(force: boolean) {
    const ticket = ++refreshId.current;
    const next: Status = await apiJson<Status>('/status');
    if (ticket !== refreshId.current) return;
    const changed = next.sequence !== client.sequence;
    setStatus(next);
    if (next.switching) return;
    client.sequence = next.sequence;
    if (!changed && !force && hydratedSequence.current === next.sequence) return;
    setSid('');setMessages([]);setDocs([]);setSessions([]);setCitation(undefined);
    setFilter('');setSelected([]);setInput('');setEditing(undefined);setDirty(false);
    setView('chat');setJob('');setProgress('');setError(next.startup_error||'');
    if (next.knowledge) {
      const [documents, history] = await Promise.all([apiJson<Document[]>('/documents'), apiJson<Session[]>('/sessions')]);
      if (ticket === refreshId.current && client.sequence === next.sequence) {setDocs(documents);setSessions(history);hydratedSequence.current = next.sequence;}
    } else {hydratedSequence.current = next.sequence;}
  }
  useEffect(() => {
    let active = true;
    const refresh = () => {if(active)void refreshKnowledge().catch(e=>{if(active)setError(e.message);});};
    void refreshKnowledge(true).catch(e=>setError(e.message));
    const timer = window.setInterval(refresh, 3000);
    window.addEventListener('focus', refresh);window.addEventListener('knowledge-changed', refresh);
    return () => {active=false;clearInterval(timer);++refreshId.current;window.removeEventListener('focus', refresh);window.removeEventListener('knowledge-changed', refresh);};
  }, []);
  async function openPicker() {
    setPickerError('');setPickerOpen(true);
    try {setRecent(await apiJson('/knowledge/recent'));}catch(e){setPickerError(String(e));}
  }
  async function chooseKnowledge(id?: string) {
    if (busy || switching || exporting) return;
    setSwitching(true);setPickerError('');
    try {
      const result = await apiJson(id?'/knowledge/switch':'/knowledge/choose', {method:'POST', ...(id?{body:JSON.stringify({id})}:{})});
      if (!result.cancelled) {await refreshKnowledge(true);setPickerOpen(false);}
      setRecent(await apiJson('/knowledge/recent'));
    } catch(e) {setPickerError(String(e));}
    finally {setSwitching(false);}
  }
  useEffect(() => {bottom.current?.scrollIntoView({behavior:'smooth'});}, [messages, progress]);

  async function newSession() {
    const session = await apiJson('/sessions', {method:'POST', body:'{}'});
    setSid(session.id); setMessages([]); setCitation(undefined); setView('chat'); await loadSessions();
    return session.id as string;
  }
  async function selectSession(id: string) {
    try {const s = await apiJson('/sessions/' + id); setSid(id); setMessages(s.messages); setView('chat'); setCitation(undefined);} catch(e) {setError(String(e));}
  }
  async function generate(topic = false, question = input) {
    if (locked || (!topic && !question.trim())) return;
    setBusy(true); setError(''); setProgress('正在准备…'); setView('chat');
    try {
      const generationSequence = client.sequence;
      const id = sid || await newSession();
      const label = topic ? '请总结所选文档的主要事实和结论。' : question;
      setInput('');
      setMessages(prev=>[...prev,{role:'user',content:label},{role:'assistant',content:'',citations:[]}]);
      const response = await api(topic ? '/topic' : '/chat', {method:'POST',body:JSON.stringify(topic ? {session_id:id,document_ids:selected} : {session_id:id,question})});
      const reader = response.body!.getReader(); const decoder = new TextDecoder(); let buffer = '';
      let completed = false;
      while (true) {
        const {value, done} = await reader.read();
        if (generationSequence !== client.sequence) {await reader.cancel();throw new Error('知识库已切换，请重试');}
        if (done) break;
        buffer += decoder.decode(value,{stream:true});
        const parts = buffer.split('\n\n'); buffer = parts.pop()!;
        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          const event = JSON.parse(part.slice(6));
          if (event.type === 'job') setJob(event.id);
          if (event.type === 'status') setProgress(event.message);
          if (event.type === 'progress') setProgress(`正在总结 ${event.completed} / ${event.total} 个证据片段`);
          if (event.type === 'evidence') setMessages(prev=>prev.map((m,i)=>i===prev.length-1?{...m,citations:event.citations}:m));
          if (event.type === 'delta') setMessages(prev=>prev.map((m,i)=>i===prev.length-1?{...m,content:m.content+event.text}:m));
          if (event.type === 'done') {completed=true; setMessages(prev=>prev.map((m,i)=>i===prev.length-1?{...m,content:event.text,citations:event.citations,supported:event.supported}:m));}
          if (event.type === 'error') throw new Error(event.message);
          if (event.type === 'cancelled') {completed=true;setMessages(prev=>prev.map((m,i)=>i===prev.length-1?{...m,content:'已停止生成，本次内容未保存。',citations:[]}:m));}
        }
      }
      if (!completed) throw new Error('连接中断，本次回答未完成。');
      await loadSessions();
    } catch(e) {setError(String(e)); setMessages(prev=>prev.map((m,i)=>i===prev.length-1&&m.role==='assistant'?{...m,content:'本次生成未完成。请查看错误提示后重试。',citations:[]}:m));}
    finally {setBusy(false);setJob('');setProgress('');}
  }

  async function exportKnowledge() {
    if(locked)return;setExporting(true);
    try {const response = await api('/export',{method:'POST'});const url = URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=(status?.knowledge?.name||'knowledge')+'.ragkb';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);setDirty(false);} catch(e){setError(String(e));} finally {setExporting(false);}
  }
  async function saveLabels() {
    if(!editing)return;
    try {await apiJson('/documents/'+editing.id,{method:'PATCH',body:JSON.stringify({category,tags:tags.split(/[,，]/).map(t=>t.trim()).filter(Boolean)})});setDocs(await apiJson('/documents'));setEditing(undefined);setDirty(true);}catch(e){setError(String(e));}
  }
  const openCitation = (c: Citation) => setCitation({...c,doc_name:c.doc_name||docs.find(d=>d.id===c.doc_id)?.name});
  function answerText(message: Message) {
    return message.content.split(/(\[\d+\])/g).map((part,i)=>{
      const n=/^\[(\d+)\]$/.exec(part);const c=n&&message.citations?.[Number(n[1])-1];
      return c?<button className="inline-citation" key={i} onClick={()=>openCitation(c)}>{part}</button>:<React.Fragment key={i}>{part}</React.Fragment>;
    });
  }
  const filtered = docs.filter(d=>[d.name,d.category,...d.tags].join(' ').toLowerCase().includes(filter.toLowerCase()));
  return <div className="app-shell"><aside className="sidebar"><div className="brand" aria-label="RadioMind"><span className="brand-mark"><svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M5 11a8 8 0 0 0 0 10m22-10a8 8 0 0 1 0 10M10 8a12 12 0 0 0 0 16M22 8a12 12 0 0 1 0 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/><path d="M16 11v10m-3-7v4m6-4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg></span><div>RadioMind<span>本地知识空间</span></div></div><button className="new-chat" disabled={locked} onClick={()=>newSession().catch(e=>setError(String(e)))}>＋ 新建对话</button><nav><button aria-label="知识问答" className={view==='chat'?'active':''} onClick={()=>setView('chat')}>◌ <span>知识问答</span></button><button aria-label="文档库" className={view==='documents'?'active':''} onClick={()=>setView('documents')}>▤ <span>文档库</span><small>{docs.length}</small></button><button aria-label="知识整理" className={view==='organize'?'active':''} onClick={()=>setView('organize')}>◇ <span>知识整理</span></button></nav><div className="nav-label">最近对话</div><div className="session-list">{sessions.map(s=><div className={'session-row '+(sid===s.id?'selected':'')} key={s.id}><button disabled={locked} onClick={()=>selectSession(s.id)}>{s.title}</button><button className="delete-session" disabled={locked} aria-label={'删除 '+s.title} onClick={async()=>{try{await apiJson('/sessions/'+s.id,{method:'DELETE'});if(sid===s.id){setSid('');setMessages([]);}await loadSessions();}catch(e){setError(String(e));}}}>×</button></div>)}{!sessions.length&&<p className="muted small">你的对话会保存在本机</p>}</div><div className="sidebar-foot"><span className="status-dot"/> 完全本地 · 数据不离开此电脑<p>RadioMind / {status?.app_version||'0.1.0'}</p><button className="text-button" disabled={locked} onClick={async()=>{try{await api('/cache/clear',{method:'POST'});setProgress('构建与导出缓存已清理');}catch(e){setError(String(e));}}}>清理缓存</button></div></aside><div className="workspace"><header><div><span className="eyebrow">KNOWLEDGE SPACE</span><div className="knowledge-title-row"><h1>{status?.knowledge?.name||'请选择知识库'}</h1><button className="secondary knowledge-select" disabled={!status||busy||switching||exporting||status.busy} title={busy||exporting||status?.busy?'请等待当前任务完成或停止生成后切换':'选择或切换知识库'} onClick={openPicker}>选择知识库</button></div></div><div className="header-meta"><span className="version">版本 {status?.knowledge?.version.slice(0,8)||'—'}</span><span>{status?.knowledge?.documents||0} 份文档</span><span className="local-pill"><span className="status-dot"/>离线运行</span></div></header>{error&&<div className="error-banner" role="alert">{error}<button onClick={()=>setError('')} aria-label="关闭错误">×</button></div>}<div className="body-columns"><main>{view==='chat'?<><div className="chat-scroll">{!messages.length?<section className="welcome"><div className="welcome-icon"><svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M5 11a8 8 0 0 0 0 10m22-10a8 8 0 0 1 0 10M10 8a12 12 0 0 0 0 16M22 8a12 12 0 0 1 0 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/><path d="M16 11v10m-3-7v4m6-4v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg></div><span className="eyebrow">让知识，清晰可见</span><h2>{status?.knowledge?'从一个问题开始。':'先选择你的知识库。'}</h2><p>{status?.knowledge?<>与文档对话，发现联系。<br/>每个答案，都能回到它的来源。</>:<>点击顶部“选择知识库”，打开本机 .ragkb 文件。<br/>加载完成后即可开始问答。</>}</p><div className="suggestions"><button disabled={locked} onClick={()=>generate(false,'这些资料主要涉及哪些内容？请提供来源。')}><span>了解知识库</span><small>这些资料主要涉及哪些内容？</small>↗</button><button onClick={()=>setView('organize')}><span>连接不同文档</span><small>选择资料，生成专题总结</small>↗</button></div><div className="welcome-note">{status?.knowledge?.pages||0} 页资料 · 中英文检索 · 原页引用</div></section>:<div className="messages">{messages.map((m,i)=><article key={i} className={'message '+m.role}><div className="message-label">{m.role==='user'?'你':'RadioMind'}{m.role==='assistant'&&busy&&i===messages.length-1&&<span>生成中 · 引用待校验</span>}</div><div className="message-text">{answerText(m)||'正在阅读相关资料…'}</div>{m.role==='assistant'&&!!m.citations?.length&&<div className="citation-cards">{m.citations.map((c,n)=>m.content.includes('['+(n+1)+']')&&<button key={n} onClick={()=>openCitation(c)}><span>[{n+1}] {c.doc_name||docs.find(d=>d.id===c.doc_id)?.name}</span><small>第 {c.page} 页 {c.kind==='ocr'?'· OCR':''} ↗</small></button>)}</div>}</article>)}</div>}<div ref={bottom}/></div><div className="composer-area">{progress&&<div className="progress" role="status">{busy&&<span className="spinner"/>}{progress}</div>}<form className="composer" onSubmit={e=>{e.preventDefault();void generate();}}><textarea aria-label="输入问题" placeholder="向你的知识库提问…" value={input} disabled={locked} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void generate();}}} rows={2}/><div className="composer-bottom"><span>▤ 当前知识库 · 本地 Qwen 4B</span>{busy?<button type="button" className="send" disabled={!job} onClick={()=>api('/jobs/'+job+'/cancel',{method:'POST'}).catch(e=>setError(String(e)))}>■ 停止</button>:<button className="send" disabled={locked||!input.trim()} aria-label="发送问题">↑</button>}</div></form><p className="composer-hint">回答基于文档生成。重要数字与结论，请通过引用核对。</p></div></>:<section className="library"><div className="library-heading"><div><span className="eyebrow">{view==='documents'?'DOCUMENT LIBRARY':'KNOWLEDGE NOTES'}</span><h2>{view==='documents'?'你的文档，井然有序。':'把资料，连成知识。'}</h2></div><button className="secondary" disabled={locked} onClick={exportKnowledge}>导出知识库{dirty?' · 有修改':''}</button></div><div className="library-toolbar"><input aria-label="筛选文档" value={filter} onChange={e=>setFilter(e.target.value)} placeholder="搜索文档、分类或标签"/><button className="primary" disabled={!selected.length||locked} onClick={()=>generate(true)}>专题总结 · 已选 {selected.length}</button></div><p className="muted small">新增或替换 PPTX 请使用独立构建工具重新生成知识库。{dirty&&' 标签已在本机保存；导出后可随知识库迁移。'}</p><div className="document-grid">{filtered.map(d=><article className="document-card" key={d.id}><div className="document-top"><span className="file-icon">P</span><label><input type="checkbox" aria-label={'选择 '+d.name} checked={selected.includes(d.id)} onChange={e=>setSelected(prev=>e.target.checked?[...prev,d.id]:prev.filter(x=>x!==d.id))}/> 选择</label></div><h3>{d.name}</h3><div className="muted small">{d.pages} 页 · {d.category||'未分类'}</div><div className="tags">{d.tags.map(t=><span key={t}>{t}</span>)}</div>{view==='organize'&&<div className="summary-text">{answerText({role:'assistant',content:d.summary,citations:d.citations})}</div>}<div className="document-actions"><button onClick={()=>openCitation({id:'',doc_id:d.id,doc_name:d.name,page:1,text:'文档首页预览',kind:'text'})}>查看原页 ↗</button><button onClick={()=>{setEditing(d);setCategory(d.category);setTags(d.tags.join(', '));}}>编辑标签</button></div></article>)}</div></section>}</main>{citation&&<Preview citation={citation} onClose={()=>setCitation(undefined)}/>}</div></div>{pickerOpen&&<KnowledgePicker recent={recent} loading={switching} error={pickerError} onChoose={chooseKnowledge} onClose={()=>setPickerOpen(false)}/>} {editing&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="编辑文档分类标签"><h2>整理文档</h2><p>{editing.name}</p><label>分类<input value={category} onChange={e=>setCategory(e.target.value)} maxLength={80}/></label><label>标签（逗号分隔）<input value={tags} onChange={e=>setTags(e.target.value)}/></label><div className="modal-actions"><button className="secondary" onClick={()=>setEditing(undefined)}>取消</button><button className="primary" onClick={saveLabels}>保存</button></div></section></div>}</div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
