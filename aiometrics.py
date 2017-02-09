import abc
import asyncio
import json
import logging
import os
import socket
import uuid
from collections import OrderedDict
from datetime import datetime
from functools import wraps

import crontab as crontab
from aiohttp import ClientOSError, ClientConnectionError

logger = logging.getLogger('aiometrics')
logger.setLevel(logging.INFO)


class BaseStreamDriver(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def stream(self, report):
        """Stream trace reports"""


class StdoutDriver(BaseStreamDriver):
    """Print stream reports to stdout"""

    def stream(self, report):
        """print trace reports to stdout"""
        print(json.dumps(report))


class LogDriver(BaseStreamDriver):
    """Stream reports to application logs"""
    def __init__(self, logger=None, name='aiometrics.LogDriver', log_level=logging.INFO):
        if logger is None:
            self.logger = logging.getLogger(name)
            self.logger.setLevel(log_level)
        else:
            self.logger = logger

    def stream(self, report):
        """Stream reports to application logs"""
        self.logger.info(json.dumps(report))


class PrometheusPushGatewayDriver(BaseStreamDriver):
    """Stream reports to prometheus pushgateway"""
    def __init__(self, name, url):
        import aiohttp
        self.name = name
        self.url = os.path.join(url, 'metrics/job', self.name)
        self.ClientSession = aiohttp.ClientSession

    @asyncio.coroutine
    def stream(self, report):
        """Stream reports to application logs"""
        with self.ClientSession() as session:
            lines = []
            for job in report['traces']:
                key = '%s:%s' % (self.name, job)
                for minute in report['traces'][job]:
                    for k, v in report['traces'][job][minute].items():
                        lines.append('# TYPE %s_%s gauge' % (key, k))
                        lines.append('%s_%s %0.2f' % (key, k, v))

            # Empty is required at the end of the payload
            lines.append("")
            data = "\n".join(lines)
            logger.info(data)
            yield from session.post(self.url, data=bytes(data.encode('utf-8')))


class NewRelicPluginCollector(BaseStreamDriver):
    """Stream reports to newrelic as a plugin"""
    def __init__(self, name, license_key):
        import aiohttp
        self.name = name
        self.license_key = license_key
        self.ClientSession = aiohttp.ClientSession

    @asyncio.coroutine
    def stream(self, report):
        """Stream reports to application logs"""

        payload = {
            "agent": {
                "host": report['instance']['hostname'],
                "version": "1.0.0"
            },
            "components": [
                {
                    "name": self.name,
                    "guid": "com.darwinmonroy.aiometrics",
                    "duration": 60,
                    "metrics": {
                        'Component/{}'.format(key): {
                            "total": metric['count'] * metric['avg'],
                            "count": metric['count'],
                            "min": metric['min'],
                            "max": metric['max'],
                            "sum_of_squares": metric['min']**2 + metric['max']**2,
                        } for key, metric in report['traces'].items()
                    }
                }
            ]
        }

        with self.ClientSession() as session:

            try:
                r = yield from session.post(
                    'https://platform-api.newrelic.com/platform/v1/metrics',
                    data=json.dumps(payload),
                    headers=(
                        ('X-License-Key', self.license_key),
                        ('Content-Type', 'application/json'),
                        ('Accept', 'application/json'),
                    )
                )
                r.close()
            except Exception as e:
                # Any exception should affect the execution of the main
                # program, so we must explicitly silence any error caused by
                # by the streaming of metrics
                # TODO: consider the implementation of a retry logic
                logger.exception(e)


class TraceCollector:
    _traces = OrderedDict()

    @classmethod
    def setup(cls, stream_driver=None):
        instance = cls.instance()
        logger.info('new instance initialized {id}@{hostname}'.format(**instance))
        cls.stream_driver = stream_driver or StdoutDriver()

    @classmethod
    def initialized(cls):
        return hasattr(cls, '_instance_id')

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance_id'):
            setattr(cls, '_instance_id', cls.generate_id())

        if not hasattr(cls, '_instance_hostname'):
            setattr(cls, '_instance_hostname', socket.gethostname())

        return dict(
            id=cls._instance_id,
            hostname=cls._instance_hostname
        )

    @classmethod
    def trace_start(cls, func):
        if not cls.initialized():
            cls.setup()

        trace_id = cls.generate_id()
        key = '{}:{}'.format(func.__module__, func.__qualname__)
        cls._traces[trace_id] = dict(
            id=trace_id,
            key=key,
            start_time=datetime.utcnow(),
            end_time=None
        )
        return trace_id

    @classmethod
    def trace_exception(cls, exception, func):
        if not cls.initialized():
            cls.setup()

        trace_id = cls.generate_id()
        ex_class = exception.__class__.__name__
        ex_lines = str(exception).splitlines()
        ex_label = '{}({})'.format(
            ex_class, ex_lines[0] if len(ex_lines) else None
        )
        key = 'Exception:{}:{}:{}'.format(
            func.__module__, func.__qualname__, ex_label
        )
        cls._traces[trace_id] = dict(
            id=trace_id,
            key=key,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow(),
            total_time=0
        )

    @classmethod
    @asyncio.coroutine
    def trace_end(cls, trace_id):
        trace = cls._traces[trace_id]
        end_time = datetime.utcnow()
        total_time = (end_time-trace['start_time']).total_seconds() * 1000
        trace.update(dict(
            end_time=end_time,
            total_time=total_time
        ))

    @classmethod
    @asyncio.coroutine
    def time_to_stream(cls):
        if cls._traces.__len__() == 0:
            return

        now = datetime.utcnow()
        first_trace_id = list(cls._traces)[0]
        first_trace = cls._traces[first_trace_id]
        first_start = first_trace['start_time']

        if now.minute != first_start.minute:
            yield from cls.stream()

    @classmethod
    @asyncio.coroutine
    def stream(cls):
        now = datetime.utcnow()
        traces = [t for t in cls._traces.values() if t['start_time'] < now and t['end_time'] is not None]
        if not len(traces):
            return

        report = dict(
            instance=cls.instance(),
            traces=cls.stats(traces)
        )

        if asyncio.iscoroutinefunction(cls.stream_driver.stream):
            yield from cls.stream_driver.stream(report)
        else:
            cls.stream_driver.stream(report)

    @classmethod
    def stats(cls, traces):
        """Build per minute stats for each key"""

        data = {}
        stats = {}
        # Group traces by key and minute
        for trace in traces:
            key = trace['key']
            if key not in data:
                data[key] = []
                stats[key] = {}

            data[key].append(trace['total_time'])
            cls._traces.pop(trace['id'])

        for key in data:
            times = data[key]
            stats[key] = dict(
                count=len(times),
                max=max(times),
                min=min(times),
                avg=sum(times)/len(times)
            )

        return stats


def trace(f):
    @wraps(f)
    @asyncio.coroutine
    def wrapper(*args, **kwargs):
        trace_id = TraceCollector.trace_start(f)
        try:
            response = f(*args, **kwargs)
            if asyncio.iscoroutine(response):
                response = yield from response
        except Exception as e:
            TraceCollector.trace_exception(e, f)
            raise e
        yield from TraceCollector.trace_end(trace_id)
        return response
    return wrapper


@asyncio.coroutine
def run():
    ct = crontab.CronTab('* * * * *')
    while True:
        # Sleep until next clock's minute
        yield from asyncio.sleep(ct.next())
        yield from TraceCollector.time_to_stream()
