"""No-effect/no-PayPal v0.5.1 observed production-handler local integration.

Runs two distinct local processes: collector and production handler + fixture.
Never loads external credentials, invokes PayPalSandboxClient or starts a payment.
This is a development probe; full frozen QF-01 qualification still INCONCLUSIVE.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from balance_paypal.security import mint_execution_token
from balance_paypal.observed_executor import canonical

def call(url, payload=None):
 raw=canonical(payload).encode() if payload is not None else None
 req=urllib.request.Request(url,raw,headers={'Content-Type':'application/json'} if raw is not None else {},
                             method='POST' if raw is not None else 'GET')
 try:
  with urllib.request.urlopen(req,timeout=2) as r:return r.status,json.loads(r.read().decode())
 except urllib.error.HTTPError as e:return e.code,json.loads(e.read().decode())

def free_port():
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def wait_ready(url,proc):
 for _ in range(80):
  if proc.poll() is not None:raise AssertionError('Child process terminated')
  try:return call(url)[1]
  except Exception:time.sleep(0.05)
 raise AssertionError('Service unavailable')

def log_replay(path):
 head='0'*64;seq=0;windows=[];active=None
 for line in Path(path).read_text().splitlines():
  row=json.loads(line);seq+=1
  core={k:v for k,v in row.items() if k!='entry_sha256'}
  assert row['seq']==seq and row['previous_sha256']==head,'Chain order mismatch'
  head=hashlib.sha256(canonical(core).encode()).hexdigest()
  assert row['entry_sha256']==head,'Hash mismatch'
  if row['kind']=='WINDOW_BEGIN':
   assert active is None,'Nested window'
   active={'id':row['window_id'],'name':row['record']['name'],'events':0,'dispatch':0,'ingress':0}
  if row['kind']=='EXECUTOR_EVENT':
   assert active and row['window_id']==active['id'],'Unscoped event'
   active['events']+=1
   if row['record']['kind']=='EXECUTOR_REQUEST_RECEIVED':active['ingress']+=1
   if row['record']['kind']=='PROVIDER_DISPATCH_BEGIN':active['dispatch']+=1
  if row['kind']=='WINDOW_END':
   assert active is not None and row['window_id']==active['id'],'Bad close'
   assert active['ingress']==row['record']['counts']['ingress'],'Bad ingress counter'
   assert active['dispatch']==sum(row['record']['counts'][k] for k in ('create','capture','get')),'Bad dispatch count'
   windows.append(active);active=None
 assert active is None and windows,'Incomplete log'
 return {'rows':seq,'head_sha256':head,'windows':windows}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
 out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
 py=sys.executable;collector_port=free_port();executor_port=free_port()
 collector=f'http://127.0.0.1:{collector_port}';ex=f'http://127.0.0.1:{executor_port}'
 log=out/'executor_collector_events.jsonl'
 cp=subprocess.Popen([py,'-B',str(ROOT/'collector_cli.py'),'--log',str(log),'--port',str(collector_port)],
                     cwd=ROOT,stdout=(out/'collector.stdout.txt').open('w'),stderr=(out/'collector.stderr.txt').open('w'))
 children=[];key=os.urandom(32);cases=[]
 try:
  ready=wait_ready(collector+'/health',cp)
  assert ready['ready'] and ready['window_id'] is None
  def window(name,which):
   status,b=call(collector+'/begin',{'name':name});assert status==200
   wid=b['window_id'];proc=None
   try:
    if which in ('bad-token','create-and-get','stale-window'):
     env=dict(os.environ,BALANCE_V051_TEST_ONLY_KEY_HEX=key.hex())
     use_wid='wrong-window-id' if which=='stale-window' else wid
     proc=subprocess.Popen([py,'-B',str(ROOT/'tests/observed_fixture_server.py'),
                             '--port',str(executor_port),'--collector',collector,'--window',use_wid],
                            cwd=ROOT,env=env,stdout=(out/f'{name}.stdout.txt').open('w'),
                            stderr=(out/f'{name}.stderr.txt').open('w'))
     children.append(proc)
     # We do not need to make a request to check readiness: local port connect only
     for _ in range(80):
      if proc.poll() is not None:raise AssertionError('Fixture Executor exited unexpectedly')
      try:
       with socket.create_connection(('127.0.0.1',executor_port),timeout=0.2):break
      except OSError:time.sleep(0.05)
     else:raise AssertionError('Fixture Executor not ready')
     mission=str(uuid.uuid4())
     request={'mission_id':mission,'operation':'CREATE_ORDER','act_digest':'a'*64,
              'body':{'mission_id':mission,'payee_id':'MERCHANT-TEST','amount':'1.00',
                       'currency':'USD','description':'Offline fixture only',
                       'request_id':str(uuid.uuid4()),'invoice_id':'INV-TEST'}}
     token=mint_execution_token(key,mission_id=mission,operation='CREATE_ORDER',
                                 act_digest_value='a'*64,request=request)
     if which=='bad-token':
      status,resp=call(ex+'/execute',{'token':'invalid-token','request':request})
      assert status==403,'Invalid token should fail'
     else:
      status,resp=call(ex+'/execute',{'token':token,'request':request})
      if which=='stale-window':assert status==403,'Bad window should reject before dispatch'
      else:
       assert status==200 and resp.get('ok') is True,'Valid fixture CREATE failed'
       order=resp['payload']['id']
       get={'mission_id':mission,'operation':'GET_ORDER','act_digest':'a'*64,'body':{'order_id':order}}
       t=mint_execution_token(key,mission_id=mission,operation='GET_ORDER',act_digest_value='a'*64,request=get)
       status,resp=call(ex+'/execute',{'token':t,'request':get})
       assert status==200 and resp.get('ok') is True,'Valid GET failed'
    # else no-executor-request window, positive proof of collection availability
   finally:
    if proc is not None:
     proc.terminate()
     try:proc.wait(timeout=5)
     except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
   status,e=call(collector+'/end',{'window_id':wid});assert status==200
   cases.append({'name':name,'counts':e['counts']})
  window('invalid-token-negative','bad-token')
  window('positive-fixture-create-get','create-and-get')
  window('stale-collector-window-refusal','stale-window')
  window('no-executor-request','none')
  replay=log_replay(log)
  expected=[{'ingress':1,'create':0,'capture':0,'get':0,'refused':1},
            {'ingress':2,'create':1,'capture':0,'get':1,'refused':0},
            {'ingress':0,'create':0,'capture':0,'get':0,'refused':0},
            {'ingress':0,'create':0,'capture':0,'get':0,'refused':0}]
  assert [v['counts'] for v in cases]==expected,'Unexpected collector counts'
  assert len(replay['windows'])==4
  report={'verdict':'SUPPLEMENTARY_V051_OBSERVED_EXECUTOR_LOCAL_PASS',
          'limitations':'Fixture provider, credential-free, local files same OS account; not real PayPal egress. '
                        'No Gate refusal A-H retest, no B full-predicate proof. QF-01 unchanged INCONCLUSIVE.',
          'collector_pid':cp.pid,'runner_pid':os.getpid(),'cases':cases,'replay':replay}
  (out/'observation_report.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps({'verdict':report['verdict'],'cases':cases,'replay_head':replay['head_sha256']},indent=2))
  return 0
 finally:
  for proc in children:
   if proc.poll() is None:proc.kill();proc.wait()
  if cp.poll() is None:cp.terminate();cp.wait(timeout=5)

if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:
  print('FAIL',type(e).__name__,str(e),file=sys.stderr)
  raise SystemExit(1)
