"""Real-model retrieval acceptance. Never uses mocked embeddings."""
import argparse
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from nordrag.config import load_config
from nordrag.engines import Engines
from nordrag.package import open_package
from nordrag.index import retrieve
from nordrag.util import read_json,write_json,data_home


def main():
    p=argparse.ArgumentParser();p.add_argument('knowledge',type=Path);p.add_argument('--gold',type=Path,default=ROOT/'artifacts/fixtures/gold.json');p.add_argument('--output',type=Path,default=ROOT/'artifacts/retrieval-report.json')
    a=p.parse_args();e=Engines(load_config())
    try:
        root,m=open_package(a.knowledge,data_home()/'acceptance',e.embedding_id)
        docs={d['id']:d for d in read_json(root/'documents.json')}
        results=[]
        for q in read_json(a.gold)['answerable']:
            started=time.perf_counter();hits=retrieve(root,q['question'],e.embed([q['question']],query=True)[0])
            correct=any(docs[h['doc_id']]['name']==q['file'] and h['page']==q['page'] for h in hits)
            results.append(q|{'retrieval_pass':correct,'elapsed_seconds':time.perf_counter()-started,'hits':[{'file':docs[h['doc_id']]['name'],'page':h['page'],'score':h['score']} for h in hits]})
        recall=sum(r['retrieval_pass'] for r in results)/len(results)
        write_json(a.output,{'knowledge_version':m['version'],'recall_at_8':recall,'target':.9,'pass':recall>=.9,'cases':results,'answer_faithfulness':'Requires separate human evaluation; not inferred from retrieval scores'})
        print(f'Recall@8: {recall:.1%}; report: {a.output}')
        return 0 if recall>=.9 else 1
    finally:e.close()


if __name__=='__main__':raise SystemExit(main())
