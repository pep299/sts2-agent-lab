from pathlib import Path
from collections import Counter
import copy
import json
from runtime import NativeEnvironment,RequestRejected,write_json

from configuration import PROFILE_TEMPLATE
from fixtures import REFERENCE, CAPTURES

def metadata(action):return action['detail'].get('metadata') or {}
def candidate(env,kind,**values):
    found=[a for a in env.last['observation']['actions'] if a['kind']==kind and all(metadata(a).get(k)==v for k,v in values.items())]
    if len(found)!=1:raise AssertionError('Ambiguous or absent candidate: '+str((kind,values,len(found))))
    return found[0]['id']

def checked_case(output,seed,body,**kwargs):
    env=NativeEnvironment(output,seed,**kwargs);checks=[]
    try:env.start();body(env,checks)
    except Exception as error:env.invalidate(error)
    finally:result=env.close()
    report={'passed':result['outcome'] in ['interrupted','completed'] and result.get('exitCode')==0,'checks':checks,
            'outcome':result['outcome'],'error':result.get('error'),'fixture':kwargs.get('fixture',False)}
    write_json(Path(output)/'case.json',report);print(json.dumps({'case':str(output),**report},ensure_ascii=False),flush=True)
    return report

def fixtures(output):
    def body(env,checks):
        env.step('fixture:grid2')
        assert env.last['observation']['state']['selection']['min']==2
        for action in ['choose_cards:0','choose_cards:0,1,2','choose_cards:1,1']:
            try:env.step(action)
            except RequestRejected:checks.append('rejected:'+action)
            else:raise AssertionError('Invalid fixture choice accepted')
        env.step('choose_cards:',indices=[1,3])
        assert env.last['observation']['capabilities']['diagnosticFixtureResult']['indices']==[1,3]
        checks.append('exact_two_card_indices_returned')
        env.step('fixture:bundle')
        assert len(env.last['observation']['state']['bundles'])==2
        expected=[c['state']['id'].split('.',1)[1] for c in env.last['observation']['state']['bundles'][1]['cards']]
        env.step('choose_bundle:1')
        assert env.last['observation']['capabilities']['diagnosticFixtureResult']['card_ids']==expected
        checks.append('selected_bundle_returned')
        env.step('fixture:relic');env.step('choose_relic:0')
        assert env.last['observation']['capabilities']['diagnosticFixtureResult']['relic_ids']==['BURNING_BLOOD']
        checks.append('selected_relic_returned')
        env.step('fixture:potions')
        assert not [a for a in env.last['observation']['actions'] if a['kind']=='potion' and metadata(a).get('potion_id')=='STRENGTH_POTION']
        before=env.last['observation']['state']['status']['maxHp']
        env.step(candidate(env,'potion',potion_id='FRUIT_JUICE'))
        assert env.last['observation']['state']['status']['maxHp']==before+5
        checks.append('anytime_potion_native_effect_plus_5_max_hp')
        env.step(candidate(env,'discard_potion',potion_id='STRENGTH_POTION'))
        assert all(s['potion'] is None for s in env.last['observation']['state']['status']['potionBelt']['slots'])
        checks.append('noncombat_potion_discard')
        env.step('fixture:draw_order')
        assert env.last['observation']['capabilities']['diagnosticFixtureResult']['permutation_invariant']
        checks.append('draw_projection_invariant_under_identical_card_permutation')
        for _ in range(30):
            if env.last['observation']['state']['phase']=='combat':break
            action=next(a['id'] for a in env.last['observation']['actions'] if not a['id'].startswith('fixture:') and a['id']!='choose_cards:')
            env.step(action)
        else:raise AssertionError('Fixture did not reach combat')
        env.step('fixture:combat_potion')
        env.step(candidate(env,'potion',potion_id='EXPLOSIVE_AMPOULE'))
        assert env.last['observation']['state']['phase']=='rewards'
        checks.append('lethal_potion_returns_native_rewards_boundary')
    return checked_case(output,'FIXTURE111',body,fixture=True)

def natural_shop(output):
    rows=[json.loads(s) for s in (REFERENCE).read_text().splitlines()]
    seed=next(r['request']['params']['seed'] for r in rows if r['request']['method']=='start_run')
    inputs=[r['request']['params']['action_id'] for r in rows if r['request']['method']=='step']
    def body(env,checks):
        i=0
        while env.last['observation']['state']['phase']!='shop':env.step(inputs[i]);i+=1
        obs=env.last['observation'];offers=obs['state']['offers']
        assert len(offers)==14
        unavailable=[o for o in offers if not o['affordable']];assert len(unavailable)==4
        bad=unavailable[0]
        try:env.step(f"shop_buy:{bad['index']}:{bad['kind']}")
        except RequestRejected:checks.append('unaffordable_offer_visible_and_purchase_rejected')
        else:raise AssertionError('Unaffordable purchase accepted')
        before=obs['state']['status'];old_gold=before['gold'];deck_size=len(before['deckCards'])
        env.step(candidate(env,'buy',entry_type='MerchantCardRemovalEntry'))
        assert env.last['observation']['state']['phase']=='grid_selection'
        chosen=next(a for a in env.last['observation']['actions'] if a['id']!='choose_cards:')
        env.step(chosen['id']);status=env.last['observation']['state']['status']
        assert status['gold']==old_gold-75 and len(status['deckCards'])==deck_size-1
        env.step(candidate(env,'buy',item_id='TAUNT'));status=env.last['observation']['state']['status']
        assert status['gold']==old_gold-99 and len(status['deckCards'])==deck_size
        assert len(env.last['observation']['state']['offers'])==14
        checks.append('native_removal_then_card_purchase_gold_111_to_12')
        env.step(candidate(env,'shop_leave'))
        checks.append('left_shop_to_next_native_boundary')
    return checked_case(output,seed,body)

def run_view(raw):
    value={k:raw[k] for k in ['phase','is_terminal','is_victory','act','floor','gold','player_hp','player_max_hp','deck_cards','relics','potions']}
    value['deck_cards']=sorted(value['deck_cards']);value['relics']=sorted(value['relics'])
    return value

def translate(env,step,checks):
    chosen=step['chosen'];kind=chosen['action_type'];m=chosen.get('metadata') or {}
    options=env.last['observation']['actions']
    exact=[a for a in options if a['id']==chosen['action_id']]
    if kind=='shop_buy':
        return candidate(env,'buy',item_id=m['item_id'],price=m['price'],entry_type=m['entry_type'])
    if kind=='use_potion':
        target=next((p.get('target') for p in step['before']['observation'].get('potion_details',[]) if p['id']==m['potion_id']),None)
        if target in ['Self','AnyPlayer']:
            converted=candidate(env,'potion',potion_id=m['potion_id'],target='self')
            checks.append({'explicitTransportMapping':{'from':chosen['action_id'],'to':converted,'reason':'same solo-player target and potion identity'}})
            return converted
    if kind=='skip_card':
        found=[a['id'] for a in options if a['kind']=='reward_alternative' and a['label'].strip().lower()=='skip']
        if len(found)==1:return found[0]
    if len(exact)==1:return exact[0]['id']
    raise AssertionError('No exact semantic mapping: '+str(chosen))

def capture_case(output,name):
    source=CAPTURES/name/'report.json';capture=json.loads(source.read_text())
    output=Path(output)
    progress=None
    if capture.get('fixtureZeroWinHistory'):
        progress=output.parent/(output.name+'-zero-win-progress.save')
        data=json.loads((PROFILE_TEMPLATE/'default/1/modded/profile1/saves/progress.save').read_text())
        for c in data.get('character_stats',[]):c['total_wins']=0
        progress.write_text(json.dumps(data))
    def body(env,checks):
        for index,step in enumerate(capture['actions']):
            actual=env._call('diagnostic_snapshot')['observation']
            assert run_view(actual)==run_view(step['before']['observation']),f'Capture before differs at {index}'
            action=translate(env,step,checks);env.step(action)
            actual=env._call('diagnostic_snapshot')['observation']
            assert run_view(actual)==run_view(step['after']['observation']),f'Capture successor differs at {index}'
            checks.append({'index':index,'beforeAndAfterEqual':True})
        checks.append({'source':str(source),'actions':len(capture['actions']),'terminal':env.last['observation']['state']['terminal']})
    return checked_case(output,capture['seed'],body,save=capture['sourceSave'],progress=progress,fixture=True)

def transitions(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    reports=[capture_case(output/name,name) for name in ['native-act1-boundary-v2','native-act2-boundary-v1','native-victory-boundary-v3','native-dummy-timeout-v1']]
    report={'passed':all(r['passed'] for r in reports),'cases':reports,'naturalVictoryTrainingData':False}
    write_json(output/'report.json',report);return report

def rooms(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    capture=json.loads((CAPTURES/'native-act3-through-v1/report.json').read_text())
    progress=output/'zero-win-progress.private.save'
    data=json.loads((PROFILE_TEMPLATE/'default/1/modded/profile1/saves/progress.save').read_text())
    for c in data.get('character_stats',[]):c['total_wins']=0
    progress.write_text(json.dumps(data))
    def advance(env,phase,checks):
        for index,step in enumerate(capture['actions']):
            actual=env._call('diagnostic_snapshot')['observation']
            if actual['phase']==phase:return step
            if run_view(actual)!=run_view(step['before']['observation']):
                write_json(env.output/'first-prefix-difference.private.json',{'index':index,'actual':actual,'expected':step['before']['observation']})
                raise AssertionError('Known native prefix differs at '+str(index))
            env.step(translate(env,step,checks))
        raise AssertionError('Requested room absent from reference: '+phase)
    def heal(env,checks):
        step=advance(env,'rest_site',checks)
        env.step(translate(env,step,checks))
        assert run_view(env._call('diagnostic_snapshot')['observation'])==run_view(step['after']['observation'])
        checks.append('native_rest_heal_matches_existing_capture')
    def smith(env,checks):
        advance(env,'rest_site',checks)
        env.step(candidate(env,'rest',option_key='SMITH'))
        observation=env.last['observation'];assert observation['state']['phase']=='grid_selection'
        chosen=next(a for a in observation['actions'] if a['id']!='choose_cards:')
        card_index=metadata(chosen)['card_index'];card=observation['state']['selection']['cards'][card_index]['cardDetails']['state']
        before=Counter((c['cardDetails']['state']['id'],c['cardDetails']['state']['upgrade']) for c in observation['state']['status']['deckCards'])
        env.step(chosen['id'])
        after=Counter((c['cardDetails']['state']['id'],c['cardDetails']['state']['upgrade']) for c in env.last['observation']['state']['status']['deckCards'])
        before[(card['id'],card['upgrade'])]-=1;before[(card['id'],card['upgrade']+1)]+=1
        assert +before==after
        checks.append('smith_upgraded_exact_selected_card')
    def treasure(env,checks,take):
        advance(env,'treasure',checks)
        observation=env.last['observation'];before=Counter(observation['state']['status']['relics'])
        if take:
            chosen=next(a for a in observation['actions'] if a['kind']=='claim_relic')
            relic='RELIC.'+metadata(chosen)['relic_id'];env.step(chosen['id']);before[relic]+=1
        else:env.step('skip_treasure')
        after=Counter(env.last['observation']['state']['status']['relics'])
        assert before==after
        checks.append('native_treasure_take' if take else 'native_treasure_skip')
    reports=[]
    for name,body in [('heal',heal),('smith',smith),('treasure-take',lambda e,c:treasure(e,c,True)),('treasure-skip',lambda e,c:treasure(e,c,False))]:
        reports.append(checked_case(output/name,capture['seed'],body,save=capture['sourceSave'],progress=progress,fixture=True,run_seconds=600))
    report={'passed':all(r['passed'] for r in reports),'cases':reports,'scope':'Native room mechanisms from saved fixture; not natural complete-run training data'}
    write_json(output/'report.json',report);return report
