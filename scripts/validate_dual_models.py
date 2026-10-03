"""Real CPU acceptance; no fabricated model outputs. Run from repository root."""
import json,sys,time,threading,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import psutil
from nordrag.config import load_config
from nordrag.chat_models import load_models
from nordrag.engines import Engines
from nordrag.package import open_package
from nordrag.index import retrieve,all_chunks
from nordrag.generation import prepare_messages,checked_answer,summarize_topic

cfg=load_config();registry=load_models(cfg)
engine=Engines(cfg,allow_unavailable_chat=True)
out=Path('artifacts/dual-model-acceptance.json');results=[]
root,manifest=open_package(Path('artifacts/delivery-demo.ragkb'),Path('artifacts/dual-model-kb'),engine.embedding_id)
chunks=all_chunks(root)
questions=[('chinese','Alpha 的保修期限是多少？'),('english','What is the warranty period for Alpha?'),('numbers','Alpha 的收入和增长率是多少？'),('no_evidence','Alpha 的 CEO 的生日是哪天？')]
try:
 for key in ('default','qwen35-4b'):
  engine.select_model(registry[key]['cfg']);record={'model':engine.model_identity,'engine':'b11326','knowledge_version':manifest['version'],'questions':[]};results.append(record)
  for kind,q in questions:
   t=time.perf_counter();evidence=retrieve(root,q,engine.embed([q],query=True)[0]);messages,citations=prepare_messages(q,evidence,[],engine.count)
   first=None;answer='';peak=0
   for part in engine.stream(messages,threading.Event(),384):
    if part and first is None:first=time.perf_counter()-t
    answer+=part
    if engine.chat.process:peak=max(peak,psutil.Process(engine.chat.process.pid).memory_info().rss)
   checked,valid=checked_answer(answer,citations)
   record['questions'].append({'kind':kind,'question':q,'answer':answer,'citation_valid':valid,'citations':citations,'first_token_seconds':first,'seconds':time.perf_counter()-t,'peak_rss_bytes_sampled':peak})
   out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(key,kind,round(time.perf_counter()-t,2),flush=True)
  t=time.perf_counter();record['organization']=engine.organize(chunks[:6],threading.Event());record['organization_seconds']=time.perf_counter()-t
  record['topic']=summarize_topic(engine,chunks[:6],threading.Event())
  history=[{'role':'user','content':'请记住代号“松鼠七号”。只回复已记住。'}]
  a=''.join(engine.stream(history,threading.Event(),64));history += [{'role':'assistant','content':a},{'role':'user','content':'刚才的代号是什么？'}]
  record['followup']=''.join(engine.stream(history,threading.Event(),64))
  long='材料：项目编号 RX-739，预算 128.50 万元，截止日期 2026-11-30。\n'+('补充记录：本段不改变项目预算或截止日期。\n'*150)
  record['long_material']=''.join(engine.stream([{'role':'user','content':long+'仅回答项目编号、预算及截止日期。'}],threading.Event(),128))
  record['no_thinking_visible']=all('<think>' not in x['answer'] for x in record['questions'])
  out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(key,'complete',flush=True)
finally:engine.close()
