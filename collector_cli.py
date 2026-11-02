"""Separately run, hash-chained, window-scoped collection for v0.5.1.

Test-only implementation. Same-user local files are NOT a separately protected
security domain. For PayPal qualification, independent custody and egress monitoring
need an explicit threat model and demonstrable boundary.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import threading
import time
import uuid
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

CANON=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)
SHA=lambda x:hashlib.sha256(CANON(x).encode()).hexdigest()
class Store:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('x',encoding='utf-8'):pass
        self.mutex=threading.RLock(); self.seq=0; self.head='0'*64
        self.window=None; self.counters={'ingress':0,'create':0,'capture':0,'get':0,'refused':0}
    def append(self,kind, data):
        with self.mutex:
            core={'seq':self.seq+1,'previous_sha256':self.head,
                  'kind':kind,'window_id':self.window,
                  'collector_pid':os.getpid(),
                  'collector_utc':datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  'collector_monotonic_ns':time.monotonic_ns(),
                  'record':data}
            row={**core,'entry_sha256':SHA(core)}
            with self.path.open('a',encoding='utf-8') as f:
                f.write(CANON(row)+'\n');f.flush();os.fsync(f.fileno())
            self.seq+=1;self.head=row['entry_sha256']
            return row

def handler_for(s):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def reply(self,status,data):
            raw=CANON(data).encode();self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def read(self):
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>50000:raise ValueError('Invalid body size')
            return json.loads(self.rfile.read(n).decode('utf-8'))
        def do_GET(self):
            with s.mutex:
                if self.path=='/health':
                    self.reply(200,{'ready':True,'collector_pid':os.getpid(),
                                    'window_id':s.window,'chain_head':s.head})
                else:self.reply(404,{'error':'unknown endpoint'})
        def do_POST(self):
            try:
                x=self.read()
                with s.mutex:
                    if self.path=='/begin':
                        if s.window: raise ValueError('Active window already exists')
                        s.window=uuid.uuid4().hex
                        s.counters={'ingress':0,'create':0,'capture':0,'get':0,'refused':0}
                        s.append('WINDOW_BEGIN',{'name':str(x['name']), 'counts':dict(s.counters)})
                        self.reply(200,{'window_id':s.window,'counts':dict(s.counters)})
                    elif self.path=='/event':
                        if s.window is None or x.get('window_id') != s.window:
                            raise ValueError('Collector-owned active window mismatch')
                        if x.get('source')!='PAYPAL_EXECUTOR_V051' or not x.get('correlation_id'):
                            raise ValueError('Missing Executor event identity')
                        kind=x.get('kind');op=x.get('operation')
                        if kind=='EXECUTOR_REQUEST_RECEIVED':s.counters['ingress']+=1
                        if kind=='PROVIDER_DISPATCH_BEGIN':
                            name={'CREATE_ORDER':'create','CAPTURE_ORDER':'capture','GET_ORDER':'get'}.get(op)
                            if name is None:raise ValueError('Unexpected provider dispatch')
                            s.counters[name]+=1
                        if kind=='EXECUTOR_REQUEST_REFUSED':s.counters['refused']+=1
                        row=s.append('EXECUTOR_EVENT',x)
                        self.reply(200,{'accepted':True,'window_id':s.window,
                                        'record_sha256':SHA(x), 'entry_sha256':row['entry_sha256']})
                    elif self.path=='/end':
                        if s.window is None or x.get('window_id')!=s.window:
                            raise ValueError('End-window mismatch')
                        counts=dict(s.counters)
                        row=s.append('WINDOW_END',{'counts':counts})
                        end=s.window;s.window=None
                        self.reply(200,{'window_id':end,'counts':counts,
                                        'entry_sha256':row['entry_sha256']})
                    else:self.reply(404,{'error':'unknown endpoint'})
            except Exception as exc:self.reply(403,{'error':type(exc).__name__+': '+str(exc)})
    return Handler

def main():
    p=argparse.ArgumentParser();p.add_argument('--log',required=True);p.add_argument('--port',type=int,required=True)
    a=p.parse_args();s=Store(a.log)
    with ThreadingHTTPServer(('127.0.0.1',a.port),handler_for(s)) as server:
        print(CANON({'collector':'READY','collector_pid':os.getpid(),'port':a.port}),flush=True)
        server.serve_forever()

if __name__=='__main__':main()
