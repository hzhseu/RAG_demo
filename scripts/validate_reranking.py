"""Real offline comparison on synthetic/public fixtures; never asserts business quality."""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nordrag.config import load_config
from nordrag.engines import Engines
from nordrag.index import retrieve
from nordrag.package import open_package
from nordrag.reranking import retrieve_evidence, rank_candidates
from nordrag.util import read_json, write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--knowledge',type=Path,default=ROOT/'artifacts/delivery-demo.ragkb')
    parser.add_argument('--gold',type=Path,default=ROOT/'artifacts/fixtures/gold.json')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/validation/reranking-comparison.json')
    args=parser.parse_args()
    engine=Engines(load_config())
    event=threading.Event()
    report={'real_models':True,'real_business_data':False,'engine':'llama.cpp b11326',
            'reranker':{k:v for k,v in engine.base_cfg.items() if k.startswith('reranker_')},
            'cases':[],'probes':[]}
    try:
        root,manifest=open_package(args.knowledge,ROOT/'artifacts/rerank-validation/work',engine.embedding_id)
        report['knowledge_version']=manifest['version']
        docs={d['id']:d['name'] for d in read_json(root/'documents.json')}
        for case in read_json(args.gold)['answerable']:
            vector=engine.embed([case['question']],query=True)[0]
            t=time.perf_counter(); baseline=retrieve(root,case['question'],vector)
            baseline_seconds=time.perf_counter()-t
            hits,meta=retrieve_evidence(root,case['question'],vector,engine,event)
            assert not meta['rerank_fallback'],meta
            def rank(values):
                return next((i+1 for i,c in enumerate(values) if docs[c['doc_id']]==case['file'] and c['page']==case['page']),None)
            report['cases'].append({**case,'baseline_rank':rank(baseline),'rerank_rank':rank(hits),
                'baseline_search_seconds':baseline_seconds,**meta,
                'hits':[{'id':c['id'],'file':docs[c['doc_id']],'page':c['page'],'rrf_score':c['score'],'rerank_score':c['rerank_score']} for c in hits]})
            write_json(args.output,report)
            print(f"case {len(report['cases'])}: {rank(baseline)} -> {rank(hits)}, rerank {meta['rerank_seconds']}s",flush=True)
        probes=[
            ('中文','Alpha 的保修期限是多少？',['Beta 收入为 99 欧元。','Alpha 保修期限为24个月。','SLA 是服务水平协议。'],1),
            ('English','What is Alpha warranty?',['Beta warranty is 12 months.','Alpha warranty is 24 months.','Alpha revenue is 120 EUR.'],1),
            ('numbers','Alpha 2025年收入是多少欧元？',['Alpha 2024年收入99.00 EUR。','Alpha 2025年增长率12.5%。','Alpha 2025年收入120.50 EUR。'],2),
            ('historical','2023 年 Alpha 保修期是多少？',['现行 Alpha 保修期为24个月。','2023年 Alpha 保修期为18个月。','Beta 保修期为12个月。'],1),
        ]
        for label,query,texts,expected in probes:
            chunks=[{'id':str(i),'doc_id':'fixture','page':i+1,'kind':'text','text':text} for i,text in enumerate(texts)]
            scores=engine.rerank(query,chunks,event)
            hits=rank_candidates(chunks,scores)
            record={'case':label,'query':query,'texts':texts,'scores':scores,'expected':expected,'first':int(hits[0]['id'])}
            report['probes'].append(record)
            write_json(args.output,report)
            assert record['first']==expected,record
        values=report['cases']
        report['summary']={}
        for name in ('baseline','rerank'):
            ranks=[v[name+'_rank'] for v in values]
            report['summary'][name]={'recall_at_8':sum(r is not None for r in ranks)/len(ranks),
                'mrr_at_8':sum(1/r if r else 0 for r in ranks)/len(ranks)}
        durations=[v['rerank_seconds'] for v in values]
        report['summary']['first_cold_rerank_seconds']=durations[0]
        report['summary']['warm_mean_rerank_seconds']=sum(durations[1:])/len(durations[1:])
        report['regressions']=[v['question'] for v in values if v['baseline_rank'] and (not v['rerank_rank'] or v['rerank_rank']>v['baseline_rank'])]
        report['pass']=not report['regressions']
        report['limitation']='Small artificial fixture set; no business-data accuracy claim. Scores are not calibrated confidence.'
        write_json(args.output,report)
        print(json.dumps(report['summary'],indent=2),flush=True)
        print('regressions:',report['regressions'],flush=True)
    finally:
        engine.close()


if __name__=='__main__':main()
