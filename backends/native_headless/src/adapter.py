"""検証済み公開ログを現行価値入力へ渡す。学習・語彙変更・重み更新は行わない。"""
from pathlib import Path
import argparse
import hashlib
import json
from runtime import GAME_HASH,sha,write_json

from public_run_state import project

def read_valid_run(folder):
    folder=Path(folder);valid=json.loads((folder/'VALID.json').read_text())
    if valid['resultSha256']!=sha(folder/'result.json') or valid['actionsSha256']!=sha(folder/'actions.jsonl'):raise ValueError('Valid manifest hash mismatch')
    result=json.loads((folder/'result.json').read_text())
    if result['gameSha256']!=GAME_HASH or not result['dataValid']:raise ValueError('Unqualified result')
    if not result['eligibleForNaturalFullRunTraining']:raise ValueError('Not a natural full run')
    rows=[json.loads(s) for s in (folder/'actions.jsonl').read_text().splitlines()]
    return result,rows

def episode_group(replay):
    return hashlib.sha256((GAME_HASH+'\0'+replay['seed']+'\0'+json.dumps(replay['profileBefore'],sort_keys=True)).encode()).hexdigest()

def resolved_successors(rows):
    successors={};origins={}
    for row in rows:
        if row['kind'] in ['action_successor','nested_action_closed']:
            successors[row['actionSequence']]=row['data']['observation']
            origins[row['actionSequence']]=row['kind']
    return successors,origins

def export_value_decisions(folder,output):
    folder=Path(folder);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    result,rows=read_valid_run(folder)
    replay=json.loads((folder/'replay-input.private.json').read_text())
    group=episode_group(replay)
    accepted={r['actionSequence'] for r in rows if r['kind']=='action_status' and r['data']['status']=='native_boundary_returned'}
    successors,origins=resolved_successors(rows)
    examples=[];source_hash=sha(folder/'actions.jsonl')
    for row in rows:
        if row['kind']!='action_initiated' or row['actionSequence'] not in accepted:continue
        sequence=row['actionSequence'];data=row['data'];choice=data['choice']
        if choice['detail']['nativeKind'] not in ['TakeReward','TakeCardRewardAlternative']:continue
        if sequence not in successors:raise ValueError('Missing successor')
        if successors[sequence]['resolution']['pendingChoice']:raise ValueError('Unresolved nested afterstate')
        examples.append({'schema':'native-value-example-1','sourceActionsSha256':source_hash,'rootRunId':row['rootRunId'],
            'actionSequence':sequence,'source':'native_headless','expert_data':False,'episode_group':group,
            'before':project(data['observation']),'chosen':choice,'observed_afterstate':project(successors[sequence]),
            'afterstate_origin':'actual_native_successor','afterstate_resolution':origins[sequence],
            'terminal':result['terminal'],'win_target':int(result['terminal']=='victory')})
    (output/'examples.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in examples))
    report={'source':str(folder),'examples':len(examples),'terminal':result['terminal'],
            'projectorSha256':sha(Path(__file__).with_name('public_run_state.py'))}
    write_json(output/'report.json',report);return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(export_value_decisions(args.run,args.output),ensure_ascii=False))
