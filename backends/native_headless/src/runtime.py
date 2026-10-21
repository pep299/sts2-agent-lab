"""実Godotを1ラン1プロセスで所有する環境。方策へは公開境界だけを返す。"""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
import uuid

from configuration import RESULTS, PROFILE_TEMPLATE, EPISODES, MANIFEST, LOCK, load_config
GAME_HASH='9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write_json(path,value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    with temp.open('w') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    temp.replace(path)

class EnvironmentFault(RuntimeError):pass
class DeclaredLimit(EnvironmentFault):pass
class Unsupported(EnvironmentFault):pass
class RequestRejected(ValueError):pass

def unreviewed_native_errors(log):
    errors=[]
    for block in re.split(r'(?m)(?=^\[ERROR\])',log):
        if not block.startswith('[ERROR]'):continue
        lines=block.splitlines()
        optional_os_error=(lines[0]=='[ERROR] System.IndexOutOfRangeException: Index was outside the bounds of the array.'
                           and len(lines)>2
                           and lines[1].strip().startswith('at MegaCrit.Sts2.Core.Debug.OsDebugInfo.FormatBytes(')
                           and lines[2].strip().startswith('at MegaCrit.Sts2.Core.Debug.OsDebugInfo.GetSystemInfoString('))
        if not optional_os_error:errors.append(block.strip())
    return errors

class OwnedProcess:
    def __init__(self,*args,**kwargs):
        self.process=subprocess.Popen(*args,**kwargs)
        self.pid=self.process.pid;self.returncode=None;self.usage=None

    def poll(self):
        if self.returncode is None:
            pid,status,usage=os.wait4(self.pid,os.WNOHANG)
            if pid:
                self.returncode=os.waitstatus_to_exitcode(status)
                self.process.returncode=self.returncode
                self.usage={'peakRssBytes':int(usage.ru_maxrss)*(1 if sys.platform=='darwin' else 1024),
                            'userCpuSeconds':usage.ru_utime,'systemCpuSeconds':usage.ru_stime,
                            'source':'wait4 for the owned native PID, including any child resources reported by the OS'}
        return self.returncode

    def wait(self,timeout):
        deadline=time.monotonic()+timeout
        while self.poll() is None:
            if time.monotonic()>=deadline:raise subprocess.TimeoutExpired(self.process.args,timeout)
            time.sleep(.01)
        return self.returncode

    def send_signal(self,sig):
        if self.poll() is None:
            try:os.kill(self.pid,sig)
            except ProcessLookupError:self.poll()

    def terminate(self):self.send_signal(signal.SIGTERM)
    def kill(self):self.send_signal(signal.SIGKILL)

class NativeEnvironment:
    def __init__(self,output,seed,*,save=None,progress=None,fixture=False,rpc_timeout=35,run_seconds=600,max_steps=5000):
        load_config()
        self.output=Path(output).resolve()
        if not self.output.is_relative_to(RESULTS):raise ValueError('Evidence must be inside the dedicated results root')
        self.output.mkdir(parents=True,exist_ok=False)
        self.output.chmod(0o700)
        self.id='native-'+uuid.uuid4().hex
        self.seed=seed;self.save=Path(save).resolve() if save else None
        self.fixture=fixture;self.timeout=rpc_timeout;self.run_seconds=run_seconds;self.max_steps=max_steps
        self.proc=None;self.sock=None;self.reader=None;self.serial=0;self.action_sequence=0;self.event_sequence=0
        self.pending=[];self.last=None;self.closed=False;self.deadline=None;self.started=time.monotonic()
        self.journal=(self.output/'actions.jsonl').open('x')
        self.private=(self.output/'rpc.private.jsonl').open('x')
        self.manifest=json.loads((MANIFEST).read_text())
        self.run_dir=EPISODES/self.id
        self.run_dir.mkdir(parents=True,exist_ok=False)
        shutil.copytree(PROFILE_TEMPLATE,self.run_dir/'profile')
        (self.run_dir/'tmp').mkdir()
        self.profile=self.run_dir/'profile/default/1/modded/profile1/saves'
        if self.save:shutil.copy2(self.save,self.profile/'current_run.save')
        if progress:shutil.copy2(progress,self.profile/'progress.save')
        self.report={'schema':'native-run-result-1','instanceId':self.id,'backend':'native_headless','gameSha256':GAME_HASH,
                     'seedPrivate':True,'sourceSave':str(self.save) if self.save else None,
                     'sourceSaveSha256':sha(self.save) if self.save else None,'continuity':'saved_segment' if save else 'new_run',
                     'fixture':fixture,'expertData':False,'outcome':'running','dataValid':False,'terminal':None,'steps':0,
                     'startedUtc':time.time(),'profileBefore':{str(p.relative_to(self.run_dir/'profile')):sha(p) for p in (self.run_dir/'profile').rglob('*') if p.is_file()}}
        write_json(self.output/'result.json',self.report)
        write_json(self.output/'replay-input.private.json',{'seed':seed,'character':'IRONCLAD','ascension':0,'fixture':fixture,
                    'save':str(self.save) if self.save else None,'sourceSaveSha256':self.report['sourceSaveSha256'],
                    'profileBefore':self.report['profileBefore'],'runtime':self.manifest,'policyInput':False})
        shutil.copytree(self.run_dir/'profile',self.output/'profile-before')
        self.app_lock=(LOCK).open('a+')
        fcntl.flock(self.app_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        self.files=[]

    def _event(self,kind,data,sequence=None):
        self.event_sequence+=1
        row={'schema':'sts2-gui-semantic-v1','kind':kind,'utc':time.time(),'elapsedSeconds':time.monotonic()-self.started,
             'sessionId':self.id,'processRunId':self.id,'rootRunId':self.id,'eventSequence':self.event_sequence,
             'actionSequence':sequence,'decisionId':self.last['decision_id'] if self.last else 0,'data':data}
        self.journal.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');self.journal.flush()

    def _call(self,method,params=None,timeout=None):
        self.serial+=1
        request={'id':self.serial,'method':method,'params':params or {}}
        begin=time.monotonic();response=None
        self.private.write(json.dumps({'kind':'request','utc':time.time(),'request':request})+'\n');self.private.flush()
        try:
            if self.proc.poll() is not None:raise EnvironmentFault('process_exit:'+str(self.proc.returncode))
            budgeted=method in ['start_run','step'] and self.deadline is not None
            left=(self.deadline-time.monotonic()) if budgeted else (timeout or self.timeout)
            if budgeted and left<=0:raise DeclaredLimit('declared_wall_time_limit')
            self.sock.settimeout(max(.05,min(timeout or self.timeout,left)))
            self.sock.sendall((json.dumps(request)+'\n').encode())
            line=self.reader.readline(32*1024*1024)
            if not line:raise EnvironmentFault('process_closed_transport:'+str(self.proc.poll()))
            if not line.endswith('\n'):raise EnvironmentFault('oversized_or_partial_response')
            response=json.loads(line.lstrip('\ufeff'))
            if response.get('id')!=self.serial:raise EnvironmentFault('response_request_id_mismatch')
            if response.get('error'):
                message=response['error']
                if 'NotSupportedException' in message:raise Unsupported(message)
                if 'ArgumentException' in message or any(x in message for x in ['Stale decision_id','duplicate request_id','No input is currently accepted','Terminal boundary']):raise RequestRejected(message)
                raise EnvironmentFault(message)
            return response['result']
        except (socket.timeout,TimeoutError) as error:
            if self.deadline is not None and time.monotonic()>=self.deadline and method in ['start_run','step']:
                raise DeclaredLimit('declared_wall_time_limit') from error
            raise EnvironmentFault('response_timeout:'+method) from error
        except (OSError,json.JSONDecodeError) as error:raise EnvironmentFault('transport_error:'+str(error)) from error
        finally:
            self.private.write(json.dumps({'kind':'response','requestId':self.serial,'method':method,'wallMs':(time.monotonic()-begin)*1000,'response':response})+'\n');self.private.flush()

    def start(self):
        exe=Path(self.manifest['executable'])
        for file,expected in [(exe,self.manifest['executableSha256']),(Path(self.manifest['gameData'])/'sts2.dll',GAME_HASH),
                              (exe.parent/'mods/spire-jev-bridge/spire-jev-bridge.dll',self.manifest['modSha256'])]:
            if sha(file)!=expected:raise EnvironmentFault('runtime_identity_changed:'+str(file))
        codex_sandbox=os.environ.get('CODEX_SANDBOX')=='seatbelt'
        override=(exe.parent/'override.cfg').read_text()
        if codex_sandbox:
            override+='\n[sentry]\noptions/auto_init=false\noptions/dsn=""\nconfig/dsn=""\n'
        (self.run_dir/'override.cfg').write_text(override)
        args=[str(exe),'--headless','--force-steam=off','--path',str(self.run_dir),
              '--clientId=1','--max-fps','60','--log-file',str(self.output/'godot.log')]
        if not codex_sandbox:
            quote=lambda p:json.dumps(str(p))
            rules=['(version 1)','(allow default)',
                   '(deny file-write* (require-all (require-not (subpath '+quote(self.run_dir)+')) (require-not (subpath '+quote(self.output)+')) (require-not (literal "/dev/null")) (require-not (regex #"^/private/tmp/mm-exhelper[.]dylib[.][^/]+$"))))',
                   '(deny process-exec (require-not (literal '+quote(exe)+')))']
            sb=self.output/'sandbox.sb';sb.write_text('\n'.join(rules)+'\n')
            args=['/usr/bin/sandbox-exec','-f',str(sb)]+args
        self.report['launchIsolation']='codex-seatbelt' if codex_sandbox else 'dedicated-seatbelt'
        self.report['episodeReportingDisabled']=codex_sandbox
        env={'PATH':'/usr/bin:/bin','LANG':'en_US.UTF-8','TMPDIR':str(self.run_dir/'tmp'),
             'STS2_FULL_APP_BRIDGE_PORT':'0','STS2_FULL_APP_BRIDGE_PORT_FILE':str(self.output/'port.txt'),
             'STS2_FORCE_CHARACTER':'IRONCLAD','STS2_EXPECTED_USERDATA':str(self.run_dir/'profile'),
             'STS2_PRIVATE_DIAGNOSTICS':'1','DOTNET_EnableDiagnostics':'0'}
        if self.fixture:env['STS2_DIAGNOSTIC_FIXTURE']='1'
        self.files=[(self.output/name).open('w') for name in ['stdout.log','stderr.log']]
        self.proc=OwnedProcess(args,cwd=self.run_dir,env=env,stdout=self.files[0],stderr=self.files[1])
        self.report.update(pid=self.proc.pid,command=args);write_json(self.output/'result.json',self.report)
        until=time.monotonic()+35
        while not (self.output/'port.txt').exists():
            if self.proc.poll() is not None:raise EnvironmentFault('startup_process_exit:'+str(self.proc.returncode))
            if time.monotonic()>until:raise EnvironmentFault('startup_timeout')
            time.sleep(.05)
        self.port=int((self.output/'port.txt').read_text())
        self.sock=socket.create_connection(('127.0.0.1',self.port),timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.reader=self.sock.makefile('r',encoding='utf-8')
        hello=self._call('hello');self.report['hello']=hello
        if hello['pid']!=self.proc.pid or hello['game_sha256']!=GAME_HASH or hello['protocol']!='native-headless-1' or hello['test_mode'] or not hello['non_interactive'] or hello['time_scale']!=1:
            raise EnvironmentFault('loaded_identity_mismatch')
        if Path(hello['user_data']).resolve()!=self.run_dir/'profile':raise EnvironmentFault('profile_isolation_mismatch')
        self.deadline=time.monotonic()+self.run_seconds
        self.last=self._call('start_run',{'seed':self.seed,'character':'IRONCLAD','ascension':0,'continue':bool(self.save)})
        self._validate_boundary(self.last)
        self._event('recorder_initialized',{'assemblySha256':GAME_HASH,'recorderRevision':'native-headless-1','observationRevision':'public-state-v3',
                    'backend':'native_headless','expertData':False,'fixture':self.fixture,'continuity':self.report['continuity']})
        self._event('run_started',{'character':'IRONCLAD','ascension':0,'continuity':self.report['continuity']})
        self._event('observation',{'observation':self.last['observation']})
        write_json(self.output/'result.json',self.report)
        return self.last

    @staticmethod
    def _validate_boundary(boundary):
        o=boundary['observation'];s=o['state'];ids=[a['id'] for a in o['actions']]
        if len(set(ids))!=len(ids):raise EnvironmentFault('duplicate_candidates')
        if s['terminal'] and ids:raise EnvironmentFault('terminal_has_candidates')
        if not s['terminal'] and not ids:raise Unsupported('nonterminal_without_candidates')
        if s['terminal'] not in [None,'victory','death']:raise EnvironmentFault('unclassified_terminal')
        if s['terminal']=='death' and s['status']['hp']!=0:raise EnvironmentFault('death_hp_inconsistent')

    def observe(self):return self.last

    def step(self,action_id,*,indices=None,request_id=None,decision_id=None):
        if self.action_sequence>=self.max_steps:raise DeclaredLimit('declared_step_limit')
        if indices is not None:
            if action_id!='choose_cards:' or any(type(i) is not int for i in indices):raise RequestRejected('Invalid parameterized selection')
            action_id='choose_cards:'+','.join(map(str,indices))
        before=self.last;observation=before['observation']
        matches=[a for a in observation['actions'] if a['id']==action_id]
        if not matches and action_id.startswith('choose_cards:'):
            try:selected_indices=list(map(int,action_id.split(':',1)[1].split(','))) if action_id.split(':',1)[1] else []
            except ValueError:selected_indices=None
            matches=[dict(a,detail=a['detail']|{'indices':selected_indices}) for a in observation['actions'] if a['id']=='choose_cards:']
        chosen=matches[0] if len(matches)==1 else {'id':action_id,'kind':'unadvertised','detail':{}}
        self.action_sequence+=1;sequence=self.action_sequence
        params={'action_id':action_id,'decision_id':decision_id if decision_id is not None else before['decision_id'],
                'request_id':request_id or uuid.uuid4().hex}
        self._event('action_initiated',{'actionId':action_id,'kind':chosen['kind'],'source':'native_headless.step','detail':chosen['detail'],
                    'choice':chosen,'observation':observation,'parentActionSequence':self.pending[-1] if self.pending else None},sequence)
        try:after=self._call('step',params)
        except RequestRejected as error:
            unchanged=self._call('observe')
            if unchanged!=before:raise EnvironmentFault('rejected_request_changed_state') from error
            self._event('action_status',{'status':'rejected','error':str(error),'stateUnchanged':True},sequence)
            raise
        self._validate_boundary(after)
        if after['decision_id']<=before['decision_id']:raise EnvironmentFault('decision_did_not_advance')
        self.last=after
        self._event('action_status',{'status':'native_boundary_returned'},sequence)
        self._event('observation',{'observation':after['observation']})
        nested=after['observation']['resolution']['pendingChoice']
        self._event('action_successor',{'actionId':action_id,'status':'entered_nested_decision' if nested else 'next_decision_observed',
                    'observation':after['observation'],'mechanicalCompletion':'native decision boundary; not a claim that every parent effect finished'},sequence)
        if nested:self.pending.append(sequence)
        else:
            for parent in reversed(self.pending):self._event('nested_action_closed',{'status':'selection_resolved_to_next_boundary','observation':after['observation']},parent)
            self.pending.clear()
        self.report['steps']+=1
        return after

    def invalidate(self,error,category=None):
        if category is None:
            message=str(error)
            category=('unsupported' if isinstance(error,Unsupported)
                      else 'process_exit' if self.proc and self.proc.poll() is not None
                      else 'startup_timeout' if message.startswith('startup_timeout')
                      else 'response_timeout' if message.startswith('response_timeout:')
                      else 'native_timeout' if 'AutoSlayTimeoutException' in message
                      else 'transport_error' if message.startswith('transport_error:')
                      else 'environment_error')
        self.report.update(outcome='fault',faultCategory=category,error=str(error),traceback=traceback.format_exc(),dataValid=False,terminal=None)
        if self.last:write_json(self.output/'last-public-boundary.json',self.last)
        if self.sock and self.proc and self.proc.poll() is None and category!='response_timeout':
            try:write_json(self.output/'last-diagnostic.private.json',self._call('diagnostic_snapshot',timeout=1))
            except Exception:pass
        self._event('environment_fault',{'category':category,'error':str(error),'dataValid':False})

    def inject_fault(self,mode):
        if mode not in ['kill','stop']:raise ValueError(mode)
        self.report['injectedFault']=mode
        os.kill(self.proc.pid,signal.SIGKILL if mode=='kill' else signal.SIGSTOP)
        if mode=='kill':self.proc.wait(timeout=3)

    def close(self,*,interrupted=False):
        if self.closed:return self.report
        self.closed=True
        terminal=self.last and self.last['observation']['state']['terminal']
        if self.report['outcome']=='running':
            self.report.update(outcome='completed' if terminal else 'interrupted',terminal=terminal)
        try:
            if self.proc and self.proc.poll() is None and self.report['outcome']!='fault' and not self.report.get('skipGracefulClose'):
                self.report['closeResponse']=self._call('close',timeout=5)
                self.proc.wait(timeout=10)
        except Exception as error:
            self.invalidate(error,'shutdown_failure')
        finally:
            if self.sock:self.sock.close()
            if self.reader:self.reader.close()
            if self.proc and self.proc.poll() is None:
                self.report['forcedCleanup']=True
                self.proc.send_signal(signal.SIGCONT);self.proc.terminate()
                try:self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=3)
            if self.proc:
                self.report['exitCode']=self.proc.returncode
                self.report['nativeExitResourceUsage']=self.proc.usage
                if self.proc.returncode!=0 and self.report['outcome']=='completed':
                    self.report.update(outcome='fault',faultCategory='shutdown_failure',error='Natural terminal followed by abnormal process exit',dataValid=False)
            if hasattr(self,'port'):
                probe=socket.socket();probe.settimeout(.2)
                self.report['endpointClosed']=probe.connect_ex(('127.0.0.1',self.port))!=0;probe.close()
            for f in self.files:f.close()
            errors=unreviewed_native_errors((self.output/'stderr.log').read_text(errors='replace')) if self.files else []
            self.report['unreviewedNativeErrorCount']=len(errors)
            if errors:
                self.report['unreviewedNativeErrors']=[message[:4096] for message in errors]
                if self.report['outcome']=='completed':self.invalidate(EnvironmentFault('Native game logged an unreviewed error'),'native_logged_error')
            if (self.run_dir/'profile').exists():shutil.move(self.run_dir/'profile',self.output/'profile-after')
            self.report.update(processReaped=self.proc is None or self.proc.poll() is not None,
                    elapsedSeconds=time.monotonic()-self.started,finishedUtc=time.time(),pendingActions=self.pending)
            self.report['dataValid']=self.report['outcome']=='completed' and not self.pending and self.report.get('exitCode')==0
            self.report['eligibleForNaturalFullRunTraining']=self.report['dataValid'] and not self.fixture and not self.save
            self._event('run_ended',{'outcome':self.report['outcome'],'terminal':self.report['terminal'],'dataValid':self.report['dataValid']})
            self._event('process_exit',{'exitCode':self.report.get('exitCode'),'pending':self.pending})
            self.journal.flush();os.fsync(self.journal.fileno());self.journal.close();self.private.close()
            write_json(self.output/'result.json',self.report)
            if self.report['dataValid']:write_json(self.output/'VALID.json',{'resultSha256':sha(self.output/'result.json'),'actionsSha256':sha(self.output/'actions.jsonl'),
                    'naturalFullRun':self.report['eligibleForNaturalFullRunTraining'],'terminal':terminal,'fixture':self.fixture})
            fcntl.flock(self.app_lock,fcntl.LOCK_UN);self.app_lock.close()
        return self.report
