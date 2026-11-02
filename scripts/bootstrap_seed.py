#!/usr/bin/env python3
"""One-time baseline import from the audited 2026-11-01 snapshot."""
import csv
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
CSV=ROOT/'seed/uberllm_all_251_estimated_v5.csv'


def pretty(s):
    return s.rsplit('/',1)[-1].replace('-', ' ').replace('_',' ').title()


def pack():
    records=list(csv.DictReader(CSV.open(encoding='utf-8')))
    def ff(v):
        try:return float(v)
        except (TypeError, ValueError):return None
    models=[]
    for r in records:
        method=r['score_method']
        source='v5' if 'V5 official' in method else 'v4_calibrated' if 'V4' in method else 'heuristic'
        cache_method=('observed' if 'Observed model' in r['cache_price_method'] else 'proxy' if 'proxy' in r['cache_price_method'] else 'assumed_uncached')
        m={
            'id':r['model_id'],
            'name':pretty(r['model_id']),
            'provider':r['provider'],
            'model_url':r['model_url'],
            'prices':{'input':ff(r['input_usd_per_million']),'output':ff(r['output_usd_per_million']),'cached':ff(r['cached_input_usd_per_million_assumed'])},
            'price_quality':'baseline_2026_11_01',
            'cache_quality':cache_method,
            'status':'snapshot',
            'score':{'value':ff(r['intelligence_v5_equiv']),'kind':source,'confidence':r['score_confidence'],'uncertainty':ff(r['estimate_uncertainty_plusminus_pts']),'basis':r['score_basis'],'source_url':r['score_reference_url'],'last_verified': '2026-11-01' if source=='v5' else None},
        }
        models.append(m)
    latest={
        'schema':1,
        'generated_at':'2026-11-02T00:44:00Z',
        'price_observed_at':'2026-11-01',
        'score_observed_at':'2026-11-01',
        'sources':{'uberllm':'bootstrap_snapshot','artificial_analysis':'bootstrap_snapshot'},
        'intelligence_index_version':'5.0',
        'monitoring_active':False,
        'warnings':['初始資料為 2026-11-01 價格快照；尚未從 GitHub Actions 成功抓取即時價格。','無 API key 時不會自動取得新 V5；估計值並非實測。'],
        'models':models,
    }
    history={'schema':1,'dates':['2026-11-01'],'by_date':{
        '2026-11-01':{m['id']:[m['prices']['input'],m['prices']['output'],m['prices']['cached'],m['score']['value'],m['score']['kind'],m['status']] for m in models}
    }}
    events={'schema':1,'updated_at':'2026-11-02T00:44:00Z','items':[]}
    (ROOT/'data/latest.json').write_text(json.dumps(latest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (ROOT/'data/history.json').write_text(json.dumps(history,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (ROOT/'data/events.json').write_text(json.dumps(events,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (ROOT/'assets/bootstrap.js').write_text('window.FRONTIER_BOOTSTRAP = '+json.dumps({'latest':latest,'history':history,'events':events},ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    print('Seed',len(models),'records,',len(latest['models']))

if __name__=='__main__':pack()
