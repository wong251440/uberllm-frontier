import copy
import importlib.util
import json
from pathlib import Path

import pytest

path=Path(__file__).resolve().parents[1]/'scripts/update.py'
spec=importlib.util.spec_from_file_location('updater',path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def price_fixture():
    return {'data':[{'id':'openai/gpt-oss-20b','name':'GPT-OSS 20B', 'type':'text',
                     'price_now':{'input':0.000020,'output':0.000090,'cached_input':0.000008}},
                    {'id':'openai/gpt-oss-120b','name':'GPT-OSS 120B', 'type':'chat',
                     'price_now':{'input':0.000080,'output':0.000310,'cached_input':0.000011}}]}


def test_price_parse_and_unit():
    rows=mod.parse_catalog(price_fixture())
    assert len(rows)==2 and rows[0]['prices']['cached']==0.000008
    assert rows[1]['prices']['output']==0.000310


def test_price_parsing_alternate_fields():
    rows=mod.parse_catalog({'models':[{'id':'m/x','type':'text','pricing':{'prompt_usd':'0.0000002','completion_usd':'0.000003','cache_read_usd':'0.00000002'}}]})
    assert rows[0]['prices']['input']==0.0000002


def test_aa_max_effort_choice():
    model={'id':'z-ai/glm-5.3','provider':'z-ai'}
    rows=[{'slug':'glm-5-3','name':'GLM-5.3 (Medium)','creator':'Z AI','value':27,'rank':3},
          {'slug':'glm-5-3','name':'GLM-5.3 (Max)','creator':'Z AI','value':32,'rank':5}]
    assert mod.choose_aa(model,rows,{})['value']==32


def test_aa_different_models_not_matched():
    model={'id':'openai/gpt-6-astra','provider':'openai'}
    rows=[{'slug':'gpt-6-sol','name':'GPT-6 Sol','creator':'OpenAI','value':60,'rank':5},
          {'slug':'gpt-6-astra','name':'GPT-6 Astra','creator':'Another Company','value':55,'rank':5}]
    assert mod.choose_aa(model,rows,{}) is None


def test_major_v6_halts():
    records=[{'id':'z-ai/glm-5.3','provider':'z-ai','score':{'kind':'heuristic','value':20}}]
    rows=[{'slug':'glm-5-3','name':'GLM-5.3 (Max)','creator':'Z AI','value':47,'rank':5}]
    ev,add,_=mod.apply_aa(records,rows,6,{},'2026-11-02')
    assert add==0 and records[0]['score']['value']==20 and ev[0]['type']=='index_version'


def test_modeling_cost():
    m={'prices':{'input':1,'cached':0.1,'output':10}}
    assert abs(mod.effective_cost(m)-38.5)<1e-8  # 15 + 13.5 + 10


def test_latest_seed_has_complete_data():
    seed=mod.read_json(path.parents[1]/'data/latest.json')
    assert len(seed['models'])>=251
    assert len(set(m['id'] for m in seed['models']))==len(seed['models'])
    assert all(m['score']['value'] is not None for m in seed['models'])


def test_batch_route_matches_highest_effort():
    model={'id':'anthropic/claude-haiku-5.5:batch','provider':'anthropic'}
    rows=[{'slug':'claude-haiku-5-5','name':'Claude Haiku 5.5 (High)','creator':'Anthropic','value':36,'rank':4}]
    assert mod.choose_aa(model,rows,{})['value']==36


def test_score_history_tracks_provenance():
    model={'id':'openai/x','status':'listed','prices':{'input':1,'output':2,'cached':.3},'score':{'kind':'heuristic','value':7.5}}
    rec=mod.take_snapshot([model])
    assert rec['openai/x']==[1,2,.3,7.5,'heuristic','listed']


def test_dry_run_integration_full_catalog_and_new_v5(tmp_path,monkeypatch):
    original_data=mod.DATA
    for fn in ('latest.json','history.json','events.json'):
        src=original_data/fn
        (tmp_path/fn).write_bytes(src.read_bytes())
    baseline=mod.read_json(tmp_path/'latest.json')
    fixture=[]
    for model in baseline['models']:
        p=model['prices']
        fixture.append({'id':model['id'],'type':'text',
            'price_now':{'input_usd_per_million':p['input']*1.04,'output_usd_per_million':p['output']*1.04,'cached_input_usd_per_million':p['cached']*1.04}})
    fixture.append({'id':'openai/gpt-new-test','type':'text',
        'price_now':{'input_usd_per_million':.01,'output_usd_per_million':.10,'cached_input_usd_per_million':.002}})
    uber_file=tmp_path/'public_fixture.json'
    uber_file.write_text(json.dumps({'data':fixture}))
    aa_file=tmp_path/'aa_fixture.json'
    aa_file.write_text(json.dumps({'intelligence_index_version':5.0,'data':[
        {'slug':'gpt-new-test','name':'GPT New Test (Max)','model_creator':{'name':'OpenAI'},
         'evaluations':{'artificial_analysis_intelligence_index':59}}]}))
    class Args:
        fixture_uberllm=uber_file
        fixture_aa=aa_file
        dry_run=True
    monkeypatch.setattr(mod,'DATA',tmp_path)
    latest,hist,events=mod.execute(Args())
    assert len(latest['models'])==len(baseline['models'])+1
    new=next(x for x in latest['models'] if x['id']=='openai/gpt-new-test')
    assert new['score']['value']==59 and new['score']['kind']=='v5'
    assert latest['monitoring_active'] is True
    assert any(e['type']=='new_v5' and e['model_id']=='openai/gpt-new-test' for e in events['items'])
    assert len(hist['dates'])>=2
    assert len(hist['by_date'][hist['dates'][-1]]['openai/gpt-new-test'])==6
    assert mod.read_json(tmp_path/'latest.json')==baseline


def test_public_mode_license_guard_hides_aa_live_updates(tmp_path,monkeypatch):
    original_data=mod.DATA
    for fn in ('latest.json','history.json','events.json'):
        (tmp_path/fn).write_bytes((original_data/fn).read_bytes())
    baseline=mod.read_json(tmp_path/'latest.json')
    fixture=[]
    for m in baseline['models']:
        p=m['prices']
        fixture.append({'id':m['id'],'type':'text','pricing':{'input_usd_per_million':p['input'],
                        'output_usd_per_million':p['output']}})
    uber_file=tmp_path/'prices.json'
    uber_file.write_text(json.dumps({'data':fixture}))
    class Args:
        fixture_uberllm=uber_file
        fixture_aa=None
        dry_run=True
    monkeypatch.setenv('AA_API_KEY','placeholder')
    monkeypatch.setenv('PUBLIC_DASHBOARD','1')
    monkeypatch.delenv('AA_REDISTRIBUTION_ALLOWED',raising=False)
    monkeypatch.setattr(mod,'DATA',tmp_path)
    def unexpected(*_,**__):raise AssertionError('Unlicensed AA API must not be fetched')
    monkeypatch.setattr(mod,'fetch_aa',unexpected)
    latest,_,_=mod.execute(Args())
    assert latest['sources']['artificial_analysis']=='licensing_guard'
    assert any('AA' in x for x in latest['warnings'])


def test_api_v4_does_not_relabel_v5_snapshot(tmp_path,monkeypatch):
    olddata=mod.DATA
    for fn in ('latest.json','history.json','events.json'):
        (tmp_path/fn).write_bytes((olddata/fn).read_bytes())
    baseline=mod.read_json(tmp_path/'latest.json')
    fixture=[{'id':m['id'],'pricing':{'input_usd_per_million':m['prices']['input'],
                'output_usd_per_million':m['prices']['output']}} for m in baseline['models']]
    price_file=tmp_path/'p.json';price_file.write_text(json.dumps({'data':fixture}))
    aa_file=tmp_path/'aa.json';aa_file.write_text(json.dumps({'intelligence_index_version':4.1,'data':[]}))
    class Args:
        fixture_uberllm=price_file
        fixture_aa=aa_file
        dry_run=True
    monkeypatch.setattr(mod,'DATA',tmp_path)
    latest,_,_=mod.execute(Args())
    assert latest['intelligence_index_version']=='5'
    assert latest['aa_api_reported_index_version']==4.1
    assert latest['score_observed_at']==baseline['score_observed_at']
    assert any('4.1' in x for x in latest['warnings'])


def test_public_mtok_prices_are_already_per_million():
    rows=mod.parse_catalog({'models':[{'id':'openai/gpt-oss-120b',
        'price_now':{'input_usd_per_mtok':0.0308,'output_usd_per_mtok':0.132,
                     'cache_read_usd_per_mtok':0.00462}}]})
    assert rows[0]['prices']=={'input':0.0308,'output':0.132,'cached':0.00462}
    assert rows[0]['unit_hint']=='million'
    assert mod.infer_scale(rows,{})==1.0


def test_market_prices_override_listed_prices_for_every_model():
    catalog={'models':[
        {'id':'deepseek/deepseek-v4.1-flash','price_now':{'input_usd_per_mtok':.00675,'output_usd_per_mtok':.075}},
        {'id':'other/model','pricing':{'input_usd_per_mtok':10,'output_usd_per_mtok':20}}]}
    market={'models':{
        'deepseek/deepseek-v4.1-flash':{'available':True,'price_now':{
            'input_usd_per_mtok':.000179,'output_usd_per_mtok':.001374,'cache_read_usd_per_mtok':.000004}},
        'other/model':{'available':True,'price_now':{
            'input_usd_per_mtok':.02,'output_usd_per_mtok':.03}}}}
    rows=mod.market_catalog(catalog,market)
    assert len(rows)==2
    assert rows[0]['prices']=={'input':.000179,'output':.001374,'cached':.000004}
    assert rows[1]['prices']=={'input':.02,'output':.03,'cached':None}
    assert all(r['price_basis']=='market_lowest' for r in rows)
    assert mod.infer_scale(rows,{})==1



def test_market_missing_price_never_falls_back_to_listed_rate():
    catalog={'models':[{'id':'x/y','pricing':{'input':10,'output':20}}]}
    with pytest.raises(ValueError):mod.market_catalog(catalog,{'models':{}})
    with pytest.raises(ValueError):mod.market_catalog(catalog,{'models':{'x/y':{'price_now':None}}})
    with pytest.raises(ValueError):mod.market_catalog(catalog,{'models':{'x/y':{'price_now':{'input':1,'output':2}}}})
