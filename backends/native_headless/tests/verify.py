from pathlib import Path
import argparse
import json
import sys
import copy
import time
from runtime import NativeEnvironment,RequestRejected,write_json
from batch import run_batch
from fixtures import REFERENCE

def smoke(output):
    environment=NativeEnvironment(output,'7KQ2M0AB9C',rpc_timeout=10,max_steps=20)
    checks=[]
    try:
        boundary=environment.start()
        checks.append({'initialPhase':boundary['observation']['state']['phase'],'hello':environment.report['hello']})
        for action,decision in [('not_a_candidate',boundary['decision_id']),
                                (boundary['observation']['actions'][0]['id'],boundary['decision_id']-1)]:
            try:environment.step(action,decision_id=decision)
            except RequestRejected:checks.append({'rejected':action,'decision':decision,'unchanged':environment.last==boundary})
            else:raise AssertionError('Invalid request accepted')
        for _ in range(4):
            observation=environment.last['observation'];options=observation['actions']
            chosen=next((a for a in options if a['id']!='choose_cards:'),options[0])
            indices=None
            if chosen['id']=='choose_cards:':indices=list(range(observation['state']['selection']['min']))
            boundary=environment.step(chosen['id'],indices=indices)
            checks.append({'phase':boundary['observation']['state']['phase'],'candidates':len(boundary['observation']['actions'])})
        environment.report['smokeChecks']=checks
    except Exception as error:
        environment.invalidate(error)
    finally:result=environment.close()
    print(json.dumps({'output':str(output),'outcome':result['outcome'],'error':result.get('error'),'checks':checks},ensure_ascii=False))
    return 0 if result['outcome']=='interrupted' and len(checks)==7 else 1

def contract(output):
    env=NativeEnvironment(output,'7KQ2M0AB9C');checks=[]
    try:
        env.start();first=env.last['observation']['actions'][0]['id']
        env.step(first,request_id='event-request')
        assert env.last['observation']['state']['phase']=='grid_selection'
        before=env.last
        time.sleep(2.5)
        assert env._call('observe')==before,'Pending choice overwritten while the controller was thinking'
        checks.append('pending_choice_stable_for_2.5_seconds')
        for action in ['choose_cards:','choose_cards:0,0','choose_cards:0,1','choose_cards:999','choose_cards:bad']:
            try:env.step(action)
            except RequestRejected:checks.append('rejected:'+action)
            else:raise AssertionError('Invalid selection accepted:'+action)
        valid=next(a['id'] for a in env.last['observation']['actions'] if a['id']!='choose_cards:')
        try:env.step(valid,request_id='event-request')
        except RequestRejected:checks.append('duplicate_request_rejected')
        else:raise AssertionError('Duplicate request accepted')
        env.step(valid)
        env.report['contractChecks']=checks
    except Exception as error:env.invalidate(error)
    finally:result=env.close()
    report={'passed':result['outcome']=='interrupted' and len(checks)==7,'checks':checks,'outcome':result['outcome'],'error':result.get('error')}
    write_json(Path(output)/'contract.json',report);print(json.dumps(report));return 0 if report['passed'] else 1

def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items() if k not in {'instance','identityScope'}}
    if isinstance(value,list):return [canonical(v) for v in value]
    return value

def reference_projection(observation):
    value=copy.deepcopy(observation)
    value.pop('frame',None);value.pop('state_hash',None)
    if value['phase']=='shop':
        room=value['room'];available=[];indices={}
        for option in room['options']:
            index,kind,item,price=option.split(':')
            if int(price)<=value['gold']:
                indices[index]=len(available);available.append(f'{len(available)}:{kind}:{item}:{price}')
        room['options']=available
        cards={}
        for index,card in room['details']['cards'].items():
            if index in indices:
                card['index']=indices[index];cards[str(indices[index])]=card
        room['details']['cards']=cards
    return value

def regression(output):
    reference=REFERENCE
    rows=[json.loads(line) for line in reference.read_text().splitlines()]
    boundaries=[r for r in rows if r['request']['method'] in ['start_run','step']]
    actions=[r['request']['params']['action_id'] for r in rows if r['request']['method']=='step']
    seed=next(r['request']['params']['seed'] for r in rows if r['request']['method']=='start_run')
    output.mkdir(parents=True,exist_ok=False);runs=[];observations=[]
    for repeat in range(2):
        env=NativeEnvironment(output/f'repeat{repeat+1}',seed);seen=[];checks=[]
        try:
            env.start()
            for index,expected in enumerate(boundaries):
                actual=env._call('diagnostic_snapshot')['observation']
                expected=expected['response']['result']['observation']
                left=reference_projection(actual);right=reference_projection(expected)
                if left!=right:
                    delta={k:{'actual':v,'expected':right.get(k)} for k,v in left.items() if v!=right.get(k)}
                    write_json(env.output/'first-difference.private.json',{'index':index,'differences':delta})
                    raise AssertionError('Fixed native observation differs at '+str(index))
                checks.append({'boundary':index,'equal':True})
                seen.append(canonical(env.last['observation']))
                if index<len(actions):env.step(actions[index])
            if env.last['observation']['state']['terminal']!='death':raise AssertionError('Expected natural defeat')
            env.report['regressionChecks']=checks
        except Exception as error:env.invalidate(error)
        finally:runs.append(env.close())
        observations.append(seen)
    public_equal=observations[0]==observations[1] and len(observations[0])==len(boundaries)
    report={'reference':str(reference),'actions':len(actions),'boundaries':len(boundaries),
            'publicObservationsAndCandidatesEqual':public_equal,'runs':[{'outcome':r['outcome'],'steps':r['steps'],'dataValid':r['dataValid'],
                 'elapsedSeconds':r['elapsedSeconds'],'error':r.get('error'),'exitCode':r.get('exitCode')} for r in runs]}
    report['passed']=public_equal and all(r['dataValid'] for r in runs)
    write_json(output/'report.json',report);print(json.dumps(report));return 0 if report['passed'] else 1

def faults(output):
    reference=REFERENCE
    source=[json.loads(s) for s in reference.read_text().splitlines()]
    actions=[r['request']['params']['action_id'] for r in source if r['request']['method']=='step']
    seed=next(r['request']['params']['seed'] for r in source if r['request']['method']=='start_run')
    def choose(boundary):return {'action_id':actions[boundary['decision_id']-1]}
    injected=set()
    def hook(env,index):
        if index in [0,2,4] and env.report['steps']==1 and index not in injected:
            injected.add(index)
            if index in [0,2]:
                env.timeout=2;env.inject_fault('kill' if index==0 else 'stop')
            else:env._call('unsupported_method_injection_for_recovery_test')
    summary=run_batch([{'seed':seed} for _ in range(6)],output,choose,fault_hook=hook)
    results=[json.loads(p.read_text()) for p in sorted(output.glob('run-*/result.json'))]
    passed=summary['completed']==3 and summary['faults']==3 and all(r['processReaped'] and r['endpointClosed'] for r in results)
    passed=passed and all(results[i]['dataValid']==(i%2==1) for i in range(6))
    report={'passed':passed,'summary':summary,'faultCategories':[results[i].get('faultCategory') for i in [0,2,4]],
            'pids':[r['pid'] for r in results],'profiles':[r['instanceId'] for r in results],
            'injectedModes':['SIGKILL','SIGSTOP','unsupported RPC']}
    write_json(output/'fault-drill.json',report);print(json.dumps(report));return 0 if passed else 1

def limits(output):
    reference=REFERENCE
    source=[json.loads(line) for line in reference.read_text().splitlines()]
    actions=[row['request']['params']['action_id'] for row in source if row['request']['method']=='step']
    seed=next(row['request']['params']['seed'] for row in source if row['request']['method']=='start_run')
    summary=run_batch([{'seed':seed,'maxSteps':1},{'seed':seed,'runSeconds':.1},{'seed':seed}],output,
                      lambda boundary:{'action_id':actions[boundary['decision_id']-1]})
    results=[json.loads(path.read_text()) for path in sorted(output.glob('run-*/result.json'))]
    passed=summary['interrupted']==2 and summary['completed']==1 and summary['faults']==0
    passed=passed and all(row['processReaped'] and row['endpointClosed'] for row in results)
    passed=passed and all(not (output/f'run-{index:04d}'/'VALID.json').exists() for index in [0,1])
    def interrupt(env,index):raise KeyboardInterrupt()
    try:
        run_batch([{'seed':seed}],output/'user-interrupt',lambda boundary:{'action_id':actions[boundary['decision_id']-1]},fault_hook=interrupt)
    except KeyboardInterrupt:pass
    else:raise AssertionError('User interruption did not stop the batch')
    interrupted=json.loads((output/'user-interrupt/run-0000/result.json').read_text())
    passed=passed and interrupted['outcome']=='interrupted' and interrupted['processReaped'] and interrupted['endpointClosed']
    report={'passed':passed,'summary':summary,'reasons':[row.get('interruptionReason') for row in results],
            'userInterruptionReapedOwnedProcess':interrupted['processReaped'],'userInterruptionOutcome':interrupted['outcome']}
    write_json(output/'limits.json',report);print(json.dumps(report));return 0 if passed else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--mode',choices=['smoke','regression','contract','faults','limits'],default='smoke')
    args=parser.parse_args();sys.exit({'smoke':smoke,'regression':regression,'contract':contract,'faults':faults,'limits':limits}[args.mode](args.output))
