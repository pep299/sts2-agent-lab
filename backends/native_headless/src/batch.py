"""環境障害を隔離して次ランへ進む入口。方策は公開境界から明示的に選ぶ。"""
from pathlib import Path
import argparse
import json
import os
import selectors
import subprocess
import time
import traceback
from runtime import NativeEnvironment,EnvironmentFault,DeclaredLimit,Unsupported,RequestRejected,write_json,RESULTS

class PolicyFault(RuntimeError):pass

def summarize(runs,requested):
    completed=[r for r in runs if r['outcome']=='completed' and r['dataValid']]
    faults=[r for r in runs if r['outcome']=='fault']
    interruptions=[r for r in runs if r['outcome']=='interrupted']
    wins=sum(r['terminal']=='victory' for r in completed)
    full=[r for r in completed if r['eligibleForNaturalFullRunTraining']]
    return {'requested':requested,'processed':len(runs),'completed':len(completed),'faults':len(faults),'interrupted':len(interruptions),
            'wins':wins,'losses':sum(r['terminal']=='death' for r in completed),'faultRateOfProcessed':len(faults)/len(runs) if runs else None,
            'completionRateOfRequested':len(completed)/requested if requested else None,
            'winRateAmongValidCompleted':wins/len(completed) if completed else None,
            'naturalFullRuns':len(full),'naturalFullRunWinRate':sum(r['terminal']=='victory' for r in full)/len(full) if full else None,
            'invalidatedByFault':len(faults),'evaluationCaveat':'Fault exclusion can bias observed win rate; report all requested, faults and interruptions separately.'}

def run_batch(specs,output,choose,*,fault_hook=None):
    output=Path(output).resolve()
    if not output.is_relative_to(RESULTS):raise ValueError('Batch evidence must be inside the dedicated results root')
    output.mkdir(parents=True,exist_ok=False)
    runs=[];repair=(output/'repair-queue.jsonl').open('x')
    try:
        for index,spec in enumerate(specs):
            folder=output/f'run-{index:04d}';environment=None
            try:
                environment=NativeEnvironment(folder,spec['seed'],save=spec.get('save'),progress=spec.get('progress'),fixture=spec.get('fixture',False),
                       rpc_timeout=spec.get('rpcTimeout',35),run_seconds=spec.get('runSeconds',600),max_steps=spec.get('maxSteps',5000))
                environment.start()
                while not environment.last['observation']['state']['terminal']:
                    if environment.report['steps']>=min(spec.get('cutoffSteps',5000),spec.get('maxSteps',5000)):
                        environment.report['interruptionReason']='declared_step_cutoff';break
                    try:
                        decision=choose(environment.last,run_deadline=environment.deadline) if isinstance(choose,JsonLinePolicy) else choose(environment.last)
                    except DeclaredLimit:raise
                    except Exception as error:raise PolicyFault(str(error)) from error
                    if fault_hook:fault_hook(environment,index)
                    environment.step(decision['action_id'],indices=decision.get('indices'))
            except KeyboardInterrupt:
                if environment:
                    environment.report.update(outcome='interrupted',terminal=None,interruptionReason='user_interrupt',skipGracefulClose=True)
                    environment.close()
                raise
            except DeclaredLimit as error:
                if environment:environment.report.update(outcome='interrupted',terminal=None,interruptionReason=str(error),declaredLimitReached=True,skipGracefulClose=True)
                else:raise
            except Exception as error:
                if environment:environment.invalidate(error,'policy_error' if isinstance(error,PolicyFault) else None)
                else:
                    folder.mkdir(exist_ok=True)
                    write_json(folder/'result.json',{'outcome':'fault','dataValid':False,'terminal':None,'faultCategory':'setup_error','error':str(error),'traceback':traceback.format_exc(),
                         'eligibleForNaturalFullRunTraining':False,'processReaped':True,'steps':0})
            finally:
                if environment:result=environment.close()
                else:result=json.loads((folder/'result.json').read_text())
                runs.append(result)
                if result['outcome']=='fault':
                    repair.write(json.dumps({'run':str(folder),'category':result.get('faultCategory'),'error':result.get('error'),
                            'owner':'environment_maintenance','learnerAction':'none; invalidated and advanced by prepared runner',
                            'status':'untriaged','replayInput':str(folder/'replay-input.private.json'),'lastPublicState':str(folder/'last-public-boundary.json')},ensure_ascii=False)+'\n');repair.flush()
                write_json(output/'summary.json',summarize(runs,len(specs)))
                print(json.dumps({'run':index,'outcome':result['outcome'],'terminal':result['terminal'],'dataValid':result['dataValid'],'error':result.get('error')},ensure_ascii=False),flush=True)
    finally:repair.close()
    return summarize(runs,len(specs))

class JsonLinePolicy:
    def __init__(self,command,output,timeout=30):
        self.stderr=Path(output).open('x');self.timeout=timeout;self.command=command;self.process=None
        try:self._start()
        except BaseException:self.stderr.close();raise

    def _start(self):
        if self.stderr.closed:raise PolicyFault('policy_closed')
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,bufsize=0)
        os.set_blocking(self.process.stdin.fileno(),False)
        os.set_blocking(self.process.stdout.fileno(),False)

    def __call__(self,boundary,*,run_deadline=None):
        if self.process is None:self._start()
        try:return self._exchange(boundary,run_deadline)
        except BaseException:
            # 遅延応答を次ランで受け取らないよう、失敗した通信路は破棄する。
            self._stop()
            raise

    def _exchange(self,boundary,run_deadline):
        deadline=time.monotonic()+self.timeout
        if run_deadline is not None:deadline=min(deadline,run_deadline)
        payload=memoryview((json.dumps(boundary,ensure_ascii=False)+'\n').encode())
        if len(payload)>32*1024*1024:raise PolicyFault('policy_input_too_large')
        def ready(selector):
            remaining=deadline-time.monotonic()
            if remaining<=0 or not selector.select(remaining):
                if run_deadline is not None and time.monotonic()>=run_deadline:raise DeclaredLimit('declared_wall_time_limit')
                raise PolicyFault('policy_response_timeout')
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin,selectors.EVENT_WRITE)
            while payload:
                ready(selector)
                try:written=os.write(self.process.stdin.fileno(),payload)
                except BlockingIOError:continue
                except BrokenPipeError as error:raise PolicyFault('policy_input_closed') from error
                payload=payload[written:]
            selector.unregister(self.process.stdin)
            selector.register(self.process.stdout,selectors.EVENT_READ)
            response=bytearray()
            while b'\n' not in response:
                ready(selector)
                try:chunk=os.read(self.process.stdout.fileno(),65536)
                except BlockingIOError:continue
                if not chunk:raise PolicyFault('policy_process_exit:'+str(self.process.poll()))
                response.extend(chunk)
                if len(response)>1024*1024:raise PolicyFault('policy_response_too_large')
        line,extra=response.split(b'\n',1)
        if extra.strip():raise PolicyFault('policy_unsolicited_output')
        try:decision=json.loads(line)
        except (ValueError,UnicodeDecodeError) as error:raise PolicyFault('policy_response_not_json') from error
        if not isinstance(decision,dict) or not isinstance(decision.get('action_id'),str):
            raise PolicyFault('policy_response_missing_action_id')
        return decision
    def _stop(self):
        if self.process is None:return
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        self.process.stdin.close();self.process.stdout.close();self.process=None

    def close(self):
        self._stop();self.stderr.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy-command',nargs='+',required=True);args=parser.parse_args()
    specs=json.loads(args.plan.read_text())
    policy=JsonLinePolicy(args.policy_command,args.output.with_suffix('.policy-stderr.log'))
    try:print(json.dumps(run_batch(specs,args.output,policy),ensure_ascii=False))
    finally:policy.close()
