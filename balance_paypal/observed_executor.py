"""Experimental v0.5.1 Executor-owned observation. Not a QF-01 PASS.

The *Executor* emits a collector-acknowledged record immediately before each provider
method invocation. The collector is a separate process. On missing acknowledgement,
dispatch fails closed. Collector collection alone cannot prove lack of out-of-band egress:
network routing / access controls must be verified separately before real Sandbox use.
"""
from __future__ import annotations
import hashlib
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


class ObservationFailure(RuntimeError):
    pass


class CollectorClient:
    def __init__(self, endpoint: str, window_id: str, timeout_seconds=2.0):
        uri = urlparse(endpoint)
        if uri.scheme != 'http' or uri.hostname not in {'localhost', '127.0.0.1'}:
            raise ObservationFailure('Collector endpoint must be loopback HTTP')
        if not window_id or len(window_id) > 128:
            raise ObservationFailure('Missing or invalid collector-owned window ID')
        self.url = endpoint.rstrip('/') + '/event'
        self.window_id = window_id
        self.timeout_seconds = timeout_seconds

    def emit(self, kind: str, *, correlation_id: str, **facts):
        record = {
            'kind': kind, 'window_id': self.window_id,
            'correlation_id': correlation_id,
            'source': 'PAYPAL_EXECUTOR_V051', 'pid': os.getpid(),
            'thread_id': threading.get_ident(),
            'utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'monotonic_ns': time.monotonic_ns(), **facts,
        }
        raw = canonical(record).encode('utf-8')
        req = urllib.request.Request(self.url, data=raw, method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode('utf-8'))
            if value.get('accepted') is not True or value.get('window_id') != self.window_id:
                raise ObservationFailure('Collector did not acknowledge the active test window')
            if value.get('record_sha256') != digest(record):
                raise ObservationFailure('Collector acknowledgement did not bind the submitted event')
            if not isinstance(value.get('entry_sha256'), str) or len(value['entry_sha256']) != 64:
                raise ObservationFailure('Collector returned malformed chain acknowledgement')
        except Exception as exc:
            raise ObservationFailure('Independent collector unavailable/mismatched: ' + type(exc).__name__) from exc
        return value


class ObservedProvider:
    """Wraps the *same* provider object used by the credential-bearing Executor.

    Its pre-dispatch collector ACK is mandatory. Post-dispatch event delivery can fail,
    leaving the effect unknown; a transport failure after dispatch must not be retried.
    """
    def __init__(self, provider, collector: CollectorClient):
        self.provider = provider
        self.collector = collector
        self._context = threading.local()

    @property
    def last_response_metadata(self):
        return getattr(self.provider, 'last_response_metadata', {})

    @last_response_metadata.setter
    def last_response_metadata(self, v):
        self.provider.last_response_metadata = v

    def use(self, correlation_id):
        self._context.correlation_id = correlation_id

    def clear(self):
        self._context.correlation_id = None

    def _invoke(self, method, args=(), kwargs=None):
        correlation_id = getattr(self._context, 'correlation_id', None)
        if correlation_id is None:
            raise ObservationFailure('Provider called without correlated Executor ingress')
        kwargs = kwargs or {}
        # No secrets, order IDs, tokens, or sensitive payload values in telemetry.
        self.collector.emit('PROVIDER_DISPATCH_BEGIN', correlation_id=correlation_id,
                            operation=method, arg_digest=digest({'args':args,'kwargs':kwargs}))
        try:
            result = getattr(self.provider, {'CREATE_ORDER':'create_order',
                                             'CAPTURE_ORDER':'capture_order',
                                             'GET_ORDER':'get_order'}[method])(*args,**kwargs)
        except Exception as exc:
            self.collector.emit('PROVIDER_DISPATCH_RESULT', correlation_id=correlation_id,
                                operation=method, result='EXCEPTION', error_type=type(exc).__name__)
            raise
        self.collector.emit('PROVIDER_DISPATCH_RESULT', correlation_id=correlation_id,
                            operation=method, result='RETURNED')
        return result

    def create_order(self, **kwargs):
        return self._invoke('CREATE_ORDER', kwargs=kwargs)

    def capture_order(self, order_id, request_id):
        return self._invoke('CAPTURE_ORDER', args=(order_id,request_id))

    def get_order(self, order_id):
        return self._invoke('GET_ORDER', args=(order_id,))


class ObservedExecutor:
    """Wraps original TokenBoundExecutor, recording HTTP ingress before validation.

    It is intentionally located at the CLI entrypoint, *not* the Gate.
    """
    def __init__(self, token_bound_executor, provider: ObservedProvider, collector: CollectorClient):
        self.original = token_bound_executor
        self.provider = provider
        self.collector = collector

    def execute(self, token, request):
        corr = uuid4().hex
        op = request.get('operation') if isinstance(request, dict) else '<INVALID>'
        self.collector.emit('EXECUTOR_REQUEST_RECEIVED', correlation_id=corr,
                            operation=op, request_sha256=digest(request),
                            token_sha256=hashlib.sha256(str(token).encode('utf-8')).hexdigest())
        self.provider.use(corr)
        try:
            result = self.original.execute(token, request)
        except Exception as exc:
            self.collector.emit('EXECUTOR_REQUEST_REFUSED', correlation_id=corr,
                                operation=op, error_type=type(exc).__name__)
            raise
        finally:
            self.provider.clear()
        self.collector.emit('EXECUTOR_REQUEST_RESULT', correlation_id=corr,
                            operation=op, ok=result.get('ok') if isinstance(result,dict) else None)
        return result
