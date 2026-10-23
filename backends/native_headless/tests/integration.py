"""固定した検証群を順次実行し、結果を保存して終了する。"""
from pathlib import Path
import argparse
import json
import signal
import subprocess
import sys
import time

WORK=Path(__file__).resolve().parent
CASES={'contract','fixtures','shop','transitions','faults','limits','regression','branch','adapter','rooms'}

def worker(case,output,source=None):
    def terminate(signum,frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,terminate)
    import verify
    import verify_cases
    if case in ['contract','faults','limits','regression']:
        return getattr(verify,case)(output)
    if case in ['fixtures','transitions']:report=getattr(verify_cases,case)(output)
    elif case=='rooms':report=verify_cases.rooms(output)
    elif case=='shop':report=verify_cases.natural_shop(output)
    elif case=='branch':
        from branch import branch
        rows=[json.loads(line) for line in (source/'actions.jsonl').read_text().splitlines()]
        target=next(r for r in rows if r['kind']=='action_initiated' and r['data']['choice']['detail']['nativeKind']=='TakeReward')
        options=target['data']['observation']['actions'];original=target['data']['choice']['id']
        alternate=next(a['id'] for a in options if a['detail']['nativeKind']=='TakeReward' and a['id']!=original)
        report=branch(source,target['actionSequence'],alternate,output)
    elif case=='adapter':
        return subprocess.run([sys.executable,str(WORK.parent/'src/adapter.py'),'--run',str(source),'--output',str(output)]).returncode
    else:raise ValueError(case)
    return 0 if report['passed'] else 1

def suite(output):
    output.mkdir(parents=True,exist_ok=False)
    history=[];source=None
    cases=['contract','fixtures','shop','transitions','rooms','faults','limits','regression','branch','adapter']
    for index,case in enumerate(cases,1):
        folder=output/f'{index:03d}-{case}'
        if case in ['branch','adapter'] and source is None:
            history.append({'case':case,'skipped':'requires a passing current-build regression'});continue
        args=[sys.executable,str(WORK/'integration.py'),'--case',case,'--output',str(folder)]
        if source:args+=['--source',str(source)]
        print(json.dumps({'caseStarted':case,'output':str(folder)}),flush=True)
        start=time.monotonic();result=subprocess.Popen(args)
        try:result.wait(timeout=1200)
        except (KeyboardInterrupt,subprocess.TimeoutExpired):
            result.send_signal(signal.SIGINT)
            try:result.wait(timeout=15)
            except subprocess.TimeoutExpired:result.kill();result.wait()
            raise
        history.append({'case':case,'output':str(folder),'exitCode':result.returncode,'seconds':time.monotonic()-start})
        (output/'suite.json').write_text(json.dumps(history,indent=2)+'\n')
        if case=='regression' and result.returncode==0:source=folder/'repeat1'
        print(json.dumps({'caseFinished':case,'exitCode':result.returncode}),flush=True)
    passed=len(history)==len(cases) and all(r.get('exitCode')==0 for r in history)
    print(json.dumps({'finished':True,'passed':passed,'cases':len(history)}),flush=True)
    return 0 if passed else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--case',choices=sorted(CASES));parser.add_argument('--source',type=Path)
    args=parser.parse_args()
    if args.case:sys.exit(worker(args.case,args.output,args.source))
    sys.exit(suite(args.output))
