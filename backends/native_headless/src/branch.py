"""同一開始条件とprefixを再実行して1候補の実後状態を作る。未来の標本化APIではない。"""
from pathlib import Path
import argparse
import json
from runtime import NativeEnvironment,EnvironmentFault,sha,write_json
from adapter import read_valid_run,episode_group

def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ['instance','identityScope']}
    if isinstance(value,list):return [stable(v) for v in value]
    return value

def branch(source,target_sequence,candidate_id,output,indices=None):
    source=Path(source);_,rows=read_valid_run(source)
    replay=json.loads((source/'replay-input.private.json').read_text())
    accepted={r['actionSequence'] for r in rows if r['kind']=='action_status' and r['data']['status']=='native_boundary_returned'}
    inputs=[r for r in rows if r['kind']=='action_initiated' and r['actionSequence'] in accepted]
    target=next(r for r in inputs if r['actionSequence']==target_sequence)
    prefix=[r for r in inputs if r['actionSequence']<target_sequence]
    env=NativeEnvironment(output,replay['seed'],progress=source/'profile-before/default/1/modded/profile1/saves/progress.save')
    checks=[];after=None
    try:
        if env.report['profileBefore']!=replay['profileBefore']:raise EnvironmentFault('replay_start_profile_mismatch')
        env.start()
        for row in prefix+[target]:
            if stable(env.last['observation'])!=stable(row['data']['observation']):raise EnvironmentFault('prefix_public_state_or_candidates_mismatch')
            checks.append(row['actionSequence'])
            if row is not target:env.step(row['data']['actionId'])
        after=env.step(candidate_id,indices=indices)
    except Exception as error:env.invalidate(error)
    finally:result=env.close()
    report={'sourceRun':str(source),'sourceActionsSha256':sha(source/'actions.jsonl'),'targetActionSequence':target_sequence,
            'candidate':candidate_id,'indices':indices,'prefixChecks':checks,'afterstate':after,
            'sameStartConditionGroup':episode_group(replay),'sourceReplaySha256':sha(source/'replay-input.private.json'),'fixture':False,'terminalTarget':None,
            'semantics':'Actual one-step native successor after exact replay; no full episode outcome or independent episode claim',
            'passed':after is not None and result['outcome'] in ['interrupted','completed'] and result['exitCode']==0}
    write_json(Path(output)/'candidate-state.json',report)
    if report['passed']:write_json(Path(output)/'AFTERSTATE_VALID.json',{'candidateStateSha256':sha(Path(output)/'candidate-state.json'),'episodeTrainingEligible':False})
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--action-sequence',type=int,required=True)
    parser.add_argument('--candidate',required=True);parser.add_argument('--indices',type=int,nargs='*');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=branch(args.run,args.action_sequence,args.candidate,args.output,args.indices)
    print(json.dumps({k:v for k,v in r.items() if k!='afterstate'},ensure_ascii=False))
