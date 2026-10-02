import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import './style.css';
import './fonts.css';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || sessionStorage.getItem('nord-token') || '';
if (token) sessionStorage.setItem('nord-token', token);
history.replaceState(null, '', location.pathname);
const headers = {'X-Nord-Token': token, 'Content-Type': 'application/json'};

type Citation = {id: string; doc_id: string; doc_name?: string; page: number; text: string; kind: string};
type Message = {role: string; content: string; citations?: Citation[]; supported?: boolean};
type Session = {id: string; title: string};
type Document = {id: string; name: string; pages: number; summary: string; tags: string[]; category: string; citations: Citation[]};
type Status = {app_version: string; model: string; knowledge: {name: string; version: string; built_at: string; documents: number; pages: number}};

async function api(path: string, init: RequestInit = {}) {
  const response = await fetch('/api' + path, {...init, headers: {...headers, ...init.headers}});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`);
  }
  return response;
}

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
  const bottom = useRef<HTMLDivElement>(null);
  const loadSessions = async () => setSessions(await (await api('/sessions')).json());
  useEffect(() => {Promise.all([api('/status').then(r=>r.json()).then(setStatus), api('/documents').then(r=>r.json()).then(setDocs), loadSessions()]).catch(e=>setError(e.message));}, []);
  useEffect(() => {bottom.current?.scrollIntoView({behavior:'smooth'});}, [messages, progress]);

  async function newSession() {
    const session = await (await api('/sessions', {method:'POST', body:'{}'})).json();
    setSid(session.id); setMessages([]); setCitation(undefined); setView('chat'); await loadSessions();
    return session.id as string;
  }
  async function selectSession(id: string) {
    try {const s = await (await api('/sessions/' + id)).json(); setSid(id); setMessages(s.messages); setView('chat'); setCitation(undefined);} catch(e) {setError(String(e));}
  }
  async function generate(topic = false, question = input) {
    if (busy || (!topic && !question.trim())) return;
    setBusy(true); setError(''); setProgress('正在准备…'); setView('chat');
    try {
      const id = sid || await newSession();
      const label = topic ? '请总结所选文档的主要事实和结论。' : question;
      setInput('');
      setMessages(prev=>[...prev,{role:'user',content:label},{role:'assistant',content:'',citations:[]}]);
      const response = await api(topic ? '/topic' : '/chat', {method:'POST',body:JSON.stringify(topic ? {session_id:id,document_ids:selected} : {session_id:id,question})});
      const reader = response.body!.getReader(); const decoder = new TextDecoder(); let buffer = '';
      let completed = false;
      while (true) {
        const {value, done} = await reader.read(); if (done) break;
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
    try {const response = await api('/export',{method:'POST'});const url = URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=(status?.knowledge.name||'knowledge')+'.ragkb';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);setDirty(false);} catch(e){setError(String(e));}
  }
  async function saveLabels() {
    if(!editing)return;
    try {await api('/documents/'+editing.id,{method:'PATCH',body:JSON.stringify({category,tags:tags.split(/[,，]/).map(t=>t.trim()).filter(Boolean)})});setDocs(await(await api('/documents')).json());setEditing(undefined);setDirty(true);}catch(e){setError(String(e));}
  }
  const openCitation = (c: Citation) => setCitation({...c,doc_name:c.doc_name||docs.find(d=>d.id===c.doc_id)?.name});
  function answerText(message: Message) {
    return message.content.split(/(\[\d+\])/g).map((part,i)=>{
      const n=/^\[(\d+)\]$/.exec(part);const c=n&&message.citations?.[Number(n[1])-1];
      return c?<button className="inline-citation" key={i} onClick={()=>openCitation(c)}>{part}</button>:<React.Fragment key={i}>{part}</React.Fragment>;
    });
  }
  const filtered = docs.filter(d=>[d.name,d.category,...d.tags].join(' ').toLowerCase().includes(filter.toLowerCase()));
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">n</span><div>nord<span>本地知识空间</span></div></div><button className="new-chat" disabled={busy} onClick={()=>newSession().catch(e=>setError(String(e)))}>＋ 新建对话</button><nav><button className={view==='chat'?'active':''} onClick={()=>setView('chat')}>◌ <span>知识问答</span></button><button className={view==='documents'?'active':''} onClick={()=>setView('documents')}>▤ <span>文档库</span><small>{docs.length}</small></button><button className={view==='organize'?'active':''} onClick={()=>setView('organize')}>◇ <span>知识整理</span></button></nav><div className="nav-label">最近对话</div><div className="session-list">{sessions.map(s=><div className={'session-row '+(sid===s.id?'selected':'')} key={s.id}><button disabled={busy} onClick={()=>selectSession(s.id)}>{s.title}</button><button className="delete-session" disabled={busy} aria-label={'删除 '+s.title} onClick={async()=>{try{await api('/sessions/'+s.id,{method:'DELETE'});if(sid===s.id){setSid('');setMessages([]);}await loadSessions();}catch(e){setError(String(e));}}}>×</button></div>)}{!sessions.length&&<p className="muted small">你的对话会保存在本机</p>}</div><div className="sidebar-foot"><span className="status-dot"/> 完全本地 · 数据不离开此电脑<p>Nord Demo / {status?.app_version||'0.1.0'}</p><button className="text-button" disabled={busy} onClick={async()=>{try{await api('/cache/clear',{method:'POST'});setProgress('构建与导出缓存已清理');}catch(e){setError(String(e));}}}>清理缓存</button></div></aside><div className="workspace"><header><div><span className="eyebrow">KNOWLEDGE SPACE</span><h1>{status?.knowledge.name||'本地知识库'}</h1></div><div className="header-meta"><span className="version">版本 {status?.knowledge.version.slice(0,8)||'—'}</span><span>{status?.knowledge.documents||0} 份文档</span><span className="local-pill"><span className="status-dot"/>离线运行</span></div></header>{error&&<div className="error-banner" role="alert">{error}<button onClick={()=>setError('')} aria-label="关闭错误">×</button></div>}<div className="body-columns"><main>{view==='chat'?<><div className="chat-scroll">{!messages.length?<section className="welcome"><div className="welcome-icon">✳</div><span className="eyebrow">让知识，清晰可见</span><h2>从一个问题开始。</h2><p>与文档对话，发现联系。<br/>每个答案，都能回到它的来源。</p><div className="suggestions"><button disabled={busy} onClick={()=>generate(false,'这些资料主要涉及哪些内容？请提供来源。')}><span>了解知识库</span><small>这些资料主要涉及哪些内容？</small>↗</button><button onClick={()=>setView('organize')}><span>连接不同文档</span><small>选择资料，生成专题总结</small>↗</button></div><div className="welcome-note">{status?.knowledge.pages||0} 页资料 · 中英文检索 · 原页引用</div></section>:<div className="messages">{messages.map((m,i)=><article key={i} className={'message '+m.role}><div className="message-label">{m.role==='user'?'你':'NORD'}{m.role==='assistant'&&busy&&i===messages.length-1&&<span>生成中 · 引用待校验</span>}</div><div className="message-text">{answerText(m)||'正在阅读相关资料…'}</div>{m.role==='assistant'&&!!m.citations?.length&&<div className="citation-cards">{m.citations.map((c,n)=>m.content.includes('['+(n+1)+']')&&<button key={n} onClick={()=>openCitation(c)}><span>[{n+1}] {c.doc_name||docs.find(d=>d.id===c.doc_id)?.name}</span><small>第 {c.page} 页 {c.kind==='ocr'?'· OCR':''} ↗</small></button>)}</div>}</article>)}</div>}<div ref={bottom}/></div><div className="composer-area">{progress&&<div className="progress" role="status">{busy&&<span className="spinner"/>}{progress}</div>}<form className="composer" onSubmit={e=>{e.preventDefault();void generate();}}><textarea aria-label="输入问题" placeholder="向你的知识库提问…" value={input} disabled={busy} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void generate();}}} rows={2}/><div className="composer-bottom"><span>▤ 当前知识库 · 本地 Qwen 4B</span>{busy?<button type="button" className="send" disabled={!job} onClick={()=>api('/jobs/'+job+'/cancel',{method:'POST'}).catch(e=>setError(String(e)))}>■ 停止</button>:<button className="send" disabled={!input.trim()} aria-label="发送问题">↑</button>}</div></form><p className="composer-hint">回答基于文档生成。重要数字与结论，请通过引用核对。</p></div></>:<section className="library"><div className="library-heading"><div><span className="eyebrow">{view==='documents'?'DOCUMENT LIBRARY':'KNOWLEDGE NOTES'}</span><h2>{view==='documents'?'你的文档，井然有序。':'把资料，连成知识。'}</h2></div><button className="secondary" disabled={busy} onClick={exportKnowledge}>导出知识库{dirty?' · 有修改':''}</button></div><div className="library-toolbar"><input aria-label="筛选文档" value={filter} onChange={e=>setFilter(e.target.value)} placeholder="搜索文档、分类或标签"/><button className="primary" disabled={!selected.length||busy} onClick={()=>generate(true)}>专题总结 · 已选 {selected.length}</button></div><p className="muted small">新增或替换 PPTX 请使用独立构建工具重新生成知识库。{dirty&&' 标签已在本机保存；导出后可随知识库迁移。'}</p><div className="document-grid">{filtered.map(d=><article className="document-card" key={d.id}><div className="document-top"><span className="file-icon">P</span><label><input type="checkbox" aria-label={'选择 '+d.name} checked={selected.includes(d.id)} onChange={e=>setSelected(prev=>e.target.checked?[...prev,d.id]:prev.filter(x=>x!==d.id))}/> 选择</label></div><h3>{d.name}</h3><div className="muted small">{d.pages} 页 · {d.category||'未分类'}</div><div className="tags">{d.tags.map(t=><span key={t}>{t}</span>)}</div>{view==='organize'&&<div className="summary-text">{answerText({role:'assistant',content:d.summary,citations:d.citations})}</div>}<div className="document-actions"><button onClick={()=>openCitation({id:'',doc_id:d.id,doc_name:d.name,page:1,text:'文档首页预览',kind:'text'})}>查看原页 ↗</button><button onClick={()=>{setEditing(d);setCategory(d.category);setTags(d.tags.join(', '));}}>编辑标签</button></div></article>)}</div></section>}</main>{citation&&<Preview citation={citation} onClose={()=>setCitation(undefined)}/>}</div></div>{editing&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="编辑文档分类标签"><h2>整理文档</h2><p>{editing.name}</p><label>分类<input value={category} onChange={e=>setCategory(e.target.value)} maxLength={80}/></label><label>标签（逗号分隔）<input value={tags} onChange={e=>setTags(e.target.value)}/></label><div className="modal-actions"><button className="secondary" onClick={()=>setEditing(undefined)}>取消</button><button className="primary" onClick={saveLabels}>保存</button></div></section></div>}</div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
