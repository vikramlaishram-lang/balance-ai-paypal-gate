"""Test-only server. Imports v0.5.1 production Executor handler with fake provider.

CANNOT import PayPalSandboxClient or payment credential files. Never ship this as a
credential-bearing runtime command. Requests are held in memory only.
"""
import argparse
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from balance_paypal.executor import TokenBoundExecutor
from balance_paypal.fixture import FixturePayPalSandbox
from balance_paypal.observed_executor import CollectorClient,ObservedExecutor,ObservedProvider
from executor_cli import handler_for

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True)
 p.add_argument('--collector',required=True);p.add_argument('--window',required=True)
 a=p.parse_args();key=bytes.fromhex(os.environ['BALANCE_V051_TEST_ONLY_KEY_HEX'])
 client=CollectorClient(a.collector,a.window)
 provider=ObservedProvider(FixturePayPalSandbox(),client)
 executor=ObservedExecutor(TokenBoundExecutor(provider,key),provider,client)
 with ThreadingHTTPServer(('127.0.0.1',a.port),handler_for(executor)) as server:
  print('READY TEST ONLY PID',os.getpid(),flush=True);server.serve_forever()
