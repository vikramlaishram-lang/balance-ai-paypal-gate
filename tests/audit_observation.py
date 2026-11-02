"""Independent read-only replay of v0.5.1 local test collector output.
No imports from candidate runtime and no sockets or writes.
"""
import argparse
import hashlib
import json
from pathlib import Path

canon=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)
sha=lambda x:hashlib.sha256(canon(x).encode()).hexdigest()

def audit(output):
    path=Path(output);report=json.loads((path/'observation_report.json').read_text('utf-8'))
    expected={
      'invalid-token-negative':{'ingress':1,'create':0,'capture':0,'get':0,'refused':1},
      'positive-fixture-create-get':{'ingress':2,'create':1,'capture':0,'get':1,'refused':0},
      'stale-collector-window-refusal':{'ingress':0,'create':0,'capture':0,'get':0,'refused':0},
      'no-executor-request':{'ingress':0,'create':0,'capture':0,'get':0,'refused':0}}
    last='0'*64;seq=0;active=None;counts={};seen={};collpid=None
    for line in (path/'executor_collector_events.jsonl').read_text('utf-8').splitlines():
        row=json.loads(line);seq+=1
        assert row['seq']==seq and row['previous_sha256']==last
        last=sha({k:v for k,v in row.items() if k!='entry_sha256'})
        assert last==row['entry_sha256']
        if collpid is None:collpid=row['collector_pid']
        assert collpid==row['collector_pid'],'Unexpected collector PID change'
        kind=row['kind']
        if kind=='WINDOW_BEGIN':
            assert active is None
            active=(row['window_id'],row['record']['name'])
            assert active[1] not in seen and active[1] in expected
            counts={'ingress':0,'create':0,'capture':0,'get':0,'refused':0}
        elif kind=='EXECUTOR_EVENT':
            assert active and active[0]==row['window_id']
            event=row['record'];assert event['window_id']==active[0]
            assert event['source']=='PAYPAL_EXECUTOR_V051'
            if event['kind']=='EXECUTOR_REQUEST_RECEIVED':counts['ingress']+=1
            if event['kind']=='EXECUTOR_REQUEST_REFUSED':counts['refused']+=1
            if event['kind']=='PROVIDER_DISPATCH_BEGIN':
                operation={'CREATE_ORDER':'create','CAPTURE_ORDER':'capture','GET_ORDER':'get'}[event['operation']]
                counts[operation]+=1
        elif kind=='WINDOW_END':
            assert active and active[0]==row['window_id']
            assert counts==row['record']['counts']
            assert counts==expected[active[1]],f'Unexpected counter for {active[1]}'
            seen[active[1]]=dict(counts);active=None
        else:raise AssertionError('Unexpected event kind')
    assert active is None and seen.keys()==expected.keys()
    assert report['verdict']=='SUPPLEMENTARY_V051_OBSERVED_EXECUTOR_LOCAL_PASS'
    assert report['replay']['head_sha256']==last and report['replay']['rows']==seq
    assert {case['name']:case['counts'] for case in report['cases']}==seen
    return {'audit':'PASS','entries':seq,'collector_pid':collpid,'windows':list(seen), 'head':last}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args()
    print(json.dumps(audit(a.out),indent=2))
