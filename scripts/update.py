#!/usr/bin/env python3
"""Daily free, server-side updater for UberLLM and optional AA V5.

No paid service, no keys in JS. Fails closed when price schema cannot be verified.
To test without network: python scripts/update.py --fixture-uberllm tests/fixtures/public_models.json --dry-run
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
UBERLLM_PUBLIC_URL = 'https://api.uberllm.dev/api/v1/public/models'
UBERLLM_AUTH_URL = 'https://api.uberllm.dev/v1/models'
AA_FREE_URL = 'https://artificialanalysis.ai/api/v2/language/models/free'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    temp.replace(path)


def finite(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        x = float(str(v).replace('$', '').replace(',', ''))
        return x if math.isfinite(x) and x >= 0 else None
    except (ValueError, TypeError):
        return None


def req_json(url, headers=None, attempts=3):
    request = Request(url, headers={'Accept':'application/json','User-Agent':'UberLLM-Frontier-Tracker/1.0 (+GitHub Actions)', **(headers or {})})
    for n in range(attempts):
        try:
            with urlopen(request, timeout=35) as response:
                return json.load(response)
        except (URLError, HTTPError, TimeoutError, json.JSONDecodeError) as err:
            if n == attempts - 1:
                raise RuntimeError(f'Failed to fetch {url}: {err}') from err
            time.sleep(2**n)


def as_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('models','data','items','results','catalog'):
            v = payload.get(key)
            if isinstance(v, list): return v
            if isinstance(v, dict):
                for subkey in ('models','items','data'):
                    if isinstance(v.get(subkey), list):return v[subkey]
                # Only use keyed dictionary if values look like models.
                if v and all(isinstance(x, dict) for x in v.values()):
                    return [dict(x, id=x.get('id', key)) for key,x in v.items()]
        if payload and all(isinstance(v,dict) for v in payload.values()):
            return [dict(v,id=v.get('id',k)) for k,v in payload.items()]
    raise ValueError('Unrecognized catalog envelope; refusing to write prices')


def price_value(price, names):
    """Return (number, unit clue) from common marketplace price schemas."""
    if not isinstance(price, dict): return None
    lower={str(k).lower(): (k,v) for k,v in price.items()}
    for name in names:
        pair=lower.get(name.lower())
        if pair:
            key,v=pair
            if isinstance(v, dict):
                for field in ('per_million','per_1m','usd_per_million','price_per_million','usd','price','value','amount'):
                    if field in v:
                        num=finite(v[field])
                        if num is not None:return num, 'million' if ('million' in field or '1m' in field) else 'unknown'
            else:
                num=finite(v)
                if num is not None: return num,'million' if ('million' in str(key) or '_1m' in str(key) or '_mtok' in str(key)) else 'unknown'
    return None

INPUT=('input_usd_per_mtok','input_usd_per_million','input_usd_per_1m','price_1m_input_tokens','input_per_million','input_per_1m','prompt_per_million','input_price_per_million','input_usd','prompt_usd','prompt','input','input_price','price_input','input_token_price')
OUTPUT=('output_usd_per_mtok','output_usd_per_million','output_usd_per_1m','price_1m_output_tokens','output_per_million','output_per_1m','completion_per_million','output_usd','completion_usd','completion','output','output_price','price_output','output_token_price')
CACHE=('cache_read_usd_per_mtok','cached_input_usd_per_mtok','cached_input_usd_per_million','cached_input_per_million','cache_read_usd_per_million','cache_hit_usd_per_million','price_1m_cache_hit_tokens','cache_read_per_million','cache_read_usd','cache_hit_usd','cached_input_usd','cache_read','cache_hit','cached_input','cache_price','cache_input','cached_prompt','cached')


def parse_catalog(payload):
    result=[]
    for row in as_items(payload):
        if not isinstance(row,dict):continue
        kind=str(row.get('type') or row.get('category') or row.get('modality') or '').lower()
        if kind and any(word in kind for word in ('image','video','music','speech','transcription','audio')) and 'text' not in kind:
            continue
        id_=str(row.get('id') or row.get('model_id') or row.get('model') or row.get('api_id') or row.get('slug') or '').strip()
        if not id_ or id_.startswith(('best-price:', 'fastest:')): continue
        if '/' not in id_:
            provider=row.get('provider') or row.get('provider_slug') or row.get('creator')
            if isinstance(provider,dict): provider=provider.get('slug') or provider.get('name')
            if isinstance(provider,str) and provider.strip(): id_=f'{provider.lower()}/{id_}'
        choices=[row.get('price_now'),row.get('pricing'),row.get('current_price'),row.get('prices'),row.get('price'),row]
        prices=None
        for obj in choices:
            if not isinstance(obj,dict): continue
            a=price_value(obj,INPUT); b=price_value(obj,OUTPUT); c=price_value(obj,CACHE)
            if a and b:
                prices={'input':a[0],'output':b[0],'cached':c[0] if c else None}
                unit='million' if a[1]=='million' or b[1]=='million' else 'unknown'
                break
        if not prices:continue
        result.append({'id':id_,'name':row.get('name') or row.get('display_name') or id_.split('/')[-1].replace('-',' ').title(),
                       'provider':id_.split('/')[0].lower(), 'prices':prices,'unit_hint':unit,'available':row.get('available'),
                       'model_url':f'https://uberllm.dev/models/{id_}'})
    # Preserve unique IDs, favour first record with price.
    return list({x['id']:x for x in result}.values())


def infer_scale(parsed, prior):
    """Public API might use USD/token or USD/1M. Infer using overlap with baseline.

    Expose one global scale; never silently mix units row by row.
    """
    overlap=[]
    for item in parsed:
        p=prior.get(item['id'],{}).get('prices',{})
        a=item['prices']['input']; b=item['prices']['output']
        if a>0 and b>0 and (p.get('input') or 0)>0 and (p.get('output') or 0)>0:
            overlap.extend([math.log10(p['input']/a), math.log10(p['output']/b)])
    hint_counts=sum(x['unit_hint']=='million' for x in parsed)
    if len(overlap)<8:
        if hint_counts >= max(1, len(parsed)//2):return 1.0
        raise ValueError('Cannot verify raw price units: insufficient model overlap; refusing potentially mis-scaled prices')
    median=statistics.median(overlap)
    candidates=(1., 1e6, 1e-6)
    winner=min(candidates, key=lambda s:abs(math.log10(s)-median))
    if abs(math.log10(winner)-median)>3.0:
        raise ValueError(f'Implausible price scale: median factor 10^{median:.1f}; manual review required')
    if hint_counts and winner!=1.0:
        raise ValueError('Conflicting price unit information: explicit per-million fields but scale is not 1')
    return winner


def normalize_key(s):
    s=str(s).lower()
    # Remove AA effort metadata, but not model-size/tier suffix such as '-max' in actual model ID.
    s=re.sub(r'\s*\((?:max|high|medium|extra.high|low|thinking.high|thinking.max)\)\s*$', '', s)
    return re.sub(r'[^a-z0-9]','',s)


def effort_rank(name):
    name=str(name).lower()
    if any(x in name for x in ('(max)','(extra high)','(xhigh)')):return 5
    if '(high)' in name:return 4
    if '(medium)' in name:return 3
    if '(low)' in name:return 2
    return 1


def aa_models_from_payload(payload):
    version=payload.get('intelligence_index_version')
    if finite(version) is None:raise ValueError('AA response missing Intelligence Index version')
    items=as_items(payload)
    clean=[]
    for row in items:
        if not isinstance(row,dict): continue
        score=finite((row.get('evaluations') or {}).get('artificial_analysis_intelligence_index'))
        if score is None:continue
        clean.append({'slug':str(row.get('slug') or ''),'name':str(row.get('name') or ''),'creator':str((row.get('model_creator') or {}).get('name') or ''),
                      'value':score,'rank':effort_rank(row.get('name'))})
    return float(version),clean


def fetch_aa(key):
    pages=[]; version=None; page=1
    while page<=25:
        url=f'{AA_FREE_URL}?page={page}'
        result=req_json(url,headers={'x-api-key':key})
        if version is None:version=result.get('intelligence_index_version')
        if result.get('intelligence_index_version')!=version:raise ValueError('AA pagination had mixed index versions')
        _, part=aa_models_from_payload(result); pages.extend(part)
        pg=result.get('pagination') or {}
        if not pg.get('has_more'):return float(version),pages
        page+=1
    raise RuntimeError('AA returned >25 pages; refusing incomplete results')

# Provider aliases to guard against cross-provider identically named models.
CREATORS={
 'openai':['openai'], 'anthropic':['anthropic'], 'google':['google','deepmind'], 'meta-llama':['meta','llama'],
 'moonshotai':['moonshot','kimi'], 'z-ai':['z ai','zhipu','z.ai'], 'qwen':['qwen','alibaba'], 'deepseek':['deepseek'],
 'minimax':['minimax'], 'mistralai':['mistral'], 'x-ai':['xai','x.ai'], 'nvidia':['nvidia'],
 'cohere':['cohere'], 'inception':['inception'], 'perplexity':['perplexity'], 'tencent':['tencent'],
 'bytedance':['bytedance','seed'], 'xiaomi':['xiaomi'], 'stepfun':['stepfun'], 'arcee-ai':['arcee']
}


def creator_matches(provider,creator):
    if not creator:return True
    provider=provider.lower().replace('_','-'); cr=normalize_key(creator)
    return any(normalize_key(x) in cr or cr in normalize_key(x) for x in CREATORS.get(provider,[provider]))


def choose_aa(model,aa_rows,alias_map):
    slug=model['id'].split('/',1)[-1]
    alias=alias_map.get(model['id'])
    targets={normalize_key(alias or slug)}
    # Suffixes only when known to preserve weights and model identity.
    for suffix in ('-batch',':batch','-web',':web','-e2ee',':e2ee'):
        if slug.endswith(suffix):targets.add(normalize_key(slug[:-len(suffix)]))
    matches=[]
    for row in aa_rows:
        if normalize_key(row['slug']) in targets and creator_matches(model['provider'],row['creator']):
            matches.append(row)
    return max(matches,key=lambda x:(x['rank'],x['value'])) if matches else None


def initial_score(model, prior):
    provider=model['provider']; name=model['id'].split('/')[-1]
    candidates=[m for m in prior.values() if m['provider']==provider and m.get('score',{}).get('value') is not None]
    if candidates:
        def similarity(a):
            s=a['id'].split('/')[-1]
            exact_family=(name.split('-')[0]==s.split('-')[0])
            return difflib.SequenceMatcher(None,name,s).ratio()+(0.16 if exact_family else 0)
        similar=max(candidates,key=similarity)
        fit=similarity(similar)
        if fit>=0.62:
            val=similar['score']['value']
            tokens=set(re.split(r'[-_/]+',name)); base=set(re.split(r'[-_/]+',similar['id'].split('/')[-1]))
            delta=sum({'flash':-4,'lite':-3,'mini':-4,'nano':-5,'pro':2,'max':2,'thinking':2}.get(t,0) for t in tokens-base)
            # For route-level variations, don't infer higher IQ from price.
            if ('batch' in tokens) or ('web' in tokens):delta=0
            return {'value':round(max(0,min(65,val+delta)),2),'kind':'heuristic','confidence':'low', 'uncertainty':12 if fit>.85 else 17,
                    'basis':f'New model proxy from {similar["id"]}; automatic unvalidated family estimate','source_url':'https://artificialanalysis.ai/'}
        values=[x['score']['value'] for x in candidates]
        return {'value':round(statistics.median(values),2),'kind':'heuristic','confidence':'very_low','uncertainty':20,
                'basis':'Provider median prior only; no verified family anchor','source_url':'https://artificialanalysis.ai/'}
    vals=[m['score']['value'] for m in prior.values() if m.get('score',{}).get('value') is not None]
    return {'value':round(statistics.median(vals),2),'kind':'heuristic','confidence':'very_low','uncertainty':22,
            'basis':'Global median prior; no provider or model-family benchmark','source_url':'https://artificialanalysis.ai/'}


def effective_cost(m, ratio=150, hit=0.9):
    p=m['prices']
    return ratio*(1-hit)*p['input']+ratio*hit*p['cached']+p['output']


def update_prices(old, parsed, scale, stamp):
    prior={m['id']:m for m in old['models']}
    seen=set(); events=[]; new_models=[]; changed=0
    for row in parsed:
        id_=row['id']; seen.add(id_)
        if id_ in prior:
            m=prior[id_]
        else:
            m={'id':id_,'name':row['name'],'provider':row['provider'],'model_url':row['model_url'],
               'status':'new','score':initial_score(row,prior)}
            prior[id_]=m;new_models.append(id_)
            events.append({'date':stamp,'type':'new_model','model_id':id_,'note':'New UberLLM model listing — score is an unvalidated estimate'})
        p=row['prices']; old_p=m.get('prices',{})
        inp=round(p['input']*scale,10); out=round(p['output']*scale,10)
        if inp>1e4 or out>1e4 or (inp==0 and out==0):raise ValueError('Price out of range for '+id_)
        if p['cached'] is not None:
            cache=round(p['cached']*scale,10)
            cq='live_catalog'
        elif old_p.get('input') is not None and old_p.get('cached') is not None and old_p['input']>0:
            cache=round(inp*(old_p['cached']/old_p['input']),10)
            cq='estimated_from_prior_ratio'
        else:
            cache=inp
            cq='assumed_uncached'
        before=effective_cost(m) if old_p.get('input') is not None and old_p.get('output') is not None and old_p.get('cached') is not None else None
        m['prices']={'input':inp,'output':out,'cached':cache}
        m['price_quality']='uberllm_listed';m['cache_quality']=cq
        m['status']='listed' if row['available'] is not False else 'unavailable'
        after=effective_cost(m)
        if before is not None and before>0 and after>0:
            pct=(after/before-1)*100
            if abs(pct)>=20:
                events.append({'date':stamp,'type':'price_change','model_id':id_,'pct':round(pct,1),'note':f'Blended modeled cost {pct:+.1f}% since previous snapshot'})
                changed+=1
    for key, m in prior.items():
        if key not in seen:m['status']='not_listed'
    # Hard fail if the publisher changes schema and only a fraction parse.
    if len(seen)<max(10,len(old['models'])*0.35):
        raise ValueError(f'Parsed only {len(seen)} models, likely API schema change; refusing to replace baseline')
    return list(prior.values()),events,{'new_models':len(new_models),'big_price_moves':changed,'parsed':len(seen)}


def apply_aa(models, aa_rows, version, aliases, stamp):
    out=[]; promoted=0; revised=0
    if int(version)!=5:
        return [{'date':stamp,'type':'index_version','model_id':'AA','note':f'Index version {version} is not V5. No scores overwritten.'}],0,0
    for m in models:
        match=choose_aa(m,aa_rows,aliases)
        if match is None:continue
        old_score=m.get('score') or {}
        old=old_score.get('value'); new=match['value']
        if old_score.get('kind')!='v5' or old is None or abs(new-old)>0.05:
            is_new=old_score.get('kind')!='v5'; promoted+=int(is_new); revised+=int(not is_new)
            out.append({'date':stamp,'type':'new_v5' if is_new else 'v5_revised','model_id':m['id'],
                        'old_score':old,'new_score':new,'note':f'AA V5 {match["name"]}: {new:g}'})
        m['score']={'value':new,'kind':'v5','confidence':'measured','uncertainty':None,
                    'basis':f'Artificial Analysis Intelligence Index v{version:g} at highest reported reasoning effort ({match["name"]})',
                    'source_url':f'https://artificialanalysis.ai/models/{match["slug"]}',
                    'last_verified':stamp}
    return out,promoted,revised


def take_snapshot(models):
    return {m['id']:[m['prices']['input'],m['prices']['output'],m['prices']['cached'],m['score']['value'],m['score'].get('kind','heuristic'),m.get('status','listed')]
            for m in models if m['status'] in ('listed','snapshot','new') and m.get('prices') and m['prices'].get('input') is not None}


def execute(args):
    now=dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    stamp=now.date().isoformat()
    old=read_json(DATA/'latest.json')
    hist=read_json(DATA/'history.json')
    eventfile=read_json(DATA/'events.json')
    if args.fixture_uberllm:
        payload=read_json(args.fixture_uberllm);price_source='test_fixture'
    else:
        key=os.environ.get('UBERLLM_API_KEY','')
        if key:
            try:
                payload=req_json(UBERLLM_AUTH_URL,headers={'Authorization':f'Bearer {key}'})
                price_source='uberllm_authenticated'
            except Exception as err:
                print(f'Authenticated model feed unavailable ({err}); trying public',file=sys.stderr)
                payload=req_json(UBERLLM_PUBLIC_URL);price_source='uberllm_public'
        else:
            payload=req_json(UBERLLM_PUBLIC_URL);price_source='uberllm_public'
    parsed=parse_catalog(payload)
    scale=1.0 if parsed and all(r['unit_hint']=='million' for r in parsed) else infer_scale(parsed,{m['id']:m for m in old['models']})
    models,events,stats=update_prices(copy.deepcopy(old),parsed,scale,stamp)
    warnings=[]
    aa_source='not_configured'
    key=os.environ.get('AA_API_KEY','')
    if args.fixture_aa:
        payload=read_json(args.fixture_aa)
        version, rows=aa_models_from_payload(payload)
        aa_source='test_fixture'
    elif key and os.environ.get('PUBLIC_DASHBOARD') == '1' and os.environ.get('AA_REDISTRIBUTION_ALLOWED','').lower() != 'true':
        version,rows=None,[]
        aa_source='licensing_guard'
        warnings.append('公開展示版尚未確認 AA 再散布權，已停用 API 分數同步；原始基準分數亦須在取得許可後才可公開發布。')
    elif key:
        try:
            version,rows=fetch_aa(key)
            aa_source='artificial_analysis_free_api'
        except Exception as err:
            version,rows=None,[]
            aa_source='fetch_failed'
            warnings.append(f'AA API 更新失敗：{str(err)[:170]}；保留既有分數。')
    else:
        version,rows=None,[]
        warnings.append('未設定 AA_API_KEY：每日價格會更新，但新 V5 分數不會自動同步。')
    reported_index_version=version
    if version is not None:
        aliases=read_json(ROOT/'config/aa_aliases.json')
        ev,added,revised=apply_aa(models,rows,version,aliases,stamp)
        events.extend(ev)
        if int(version)!=5:
            warnings.append(f'Artificial Analysis API 回報 v{version:g}（非 V5），為避免混合量尺，保留 V5 等效分數並暫停覆寫。')
            version=float(old.get('intelligence_index_version') or 5)
    else:
        added=revised=0
        version=float(old.get('intelligence_index_version') or 5)
    eventfile['items']=(events+eventfile.get('items',[]))[:200]
    eventfile['updated_at']=now.isoformat().replace('+00:00','Z')
    hist.setdefault('by_date',{})[stamp]=take_snapshot(models)
    # Retain last 365 days. Existing baseline preserved while still within interval.
    dates=sorted(hist['by_date'].keys())[-365:]
    hist['dates']=dates
    hist['by_date']={d:hist['by_date'][d] for d in dates}
    latest={'schema':1,'generated_at':now.isoformat().replace('+00:00','Z'),
            'price_observed_at':stamp,'price_basis':'listed','score_observed_at':stamp if aa_source in ('artificial_analysis_free_api','test_fixture') and reported_index_version is not None and int(reported_index_version)==5 else old.get('score_observed_at'),
            'sources':{'uberllm':price_source,'artificial_analysis':aa_source},
            'intelligence_index_version':f'{version:g}',
            'aa_api_reported_index_version':reported_index_version,
            'monitoring_active':True,'warnings':warnings,'models':models}
    print(json.dumps({'stamp':stamp,'stats':stats,'price_unit_multiplier':scale,'aa_v5_promoted':added,'aa_v5_revised':revised,
                      'events':len(events),'model_count':len(models),'would_write':not args.dry_run},ensure_ascii=False))
    if args.dry_run:return latest,hist,eventfile
    write_json(DATA/'latest.json',latest)
    write_json(DATA/'history.json',hist)
    write_json(DATA/'events.json',eventfile)
    return latest,hist,eventfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fixture-uberllm',type=Path)
    p.add_argument('--fixture-aa',type=Path)
    p.add_argument('--dry-run',action='store_true')
    execute(p.parse_args())

if __name__=='__main__':main()
