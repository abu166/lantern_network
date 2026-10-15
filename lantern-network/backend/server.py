"""Lantern's loopback-only HTTP API and static application server."""
import argparse
import json
import logging
import mimetypes
from logging.handlers import RotatingFileHandler
import signal
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import scanner
from .store import Store
from .router import RouterSource

ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger('lantern')
DEMO_NETWORK = '192.168.1.0/24'
DEMO = [
    dict(ip='192.168.1.1', mac='02:10:20:30:40:01', hostname='Home gateway', kind='router', latency=1.2),
    dict(ip='192.168.1.12', mac='02:10:20:30:40:02', hostname='MacBook Pro', kind='computer', latency=2.4),
    dict(ip='192.168.1.18', mac='02:10:20:30:40:03', hostname='iPhone', kind='phone', latency=8.1),
    dict(ip='192.168.1.24', mac='02:10:20:30:40:04', hostname='Living room TV', kind='tv', latency=4.6),
    dict(ip='192.168.1.36', mac='02:10:20:30:40:05', hostname='Pixel 9', kind='phone', latency=12.3),
    dict(ip='192.168.1.42', mac='02:10:20:30:40:06', hostname='Desk speaker', kind='device', latency=6.8),
    dict(ip='192.168.1.57', mac='02:10:20:30:40:07', hostname='', kind='device', latency=18.5),
    dict(ip='192.168.1.61', mac='02:10:20:30:40:08', hostname='Work laptop', kind='computer', latency=3.2),
]


class Application:
    def __init__(self, db_path, leases_file=None):
        self.store = Store(db_path)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.router = RouterSource(leases_file)
        self.status = dict(running=False, error=None, started=None, finished=None)
        if not self.store.snapshot('demo')['devices']:
            self.store.record_scan('demo', DEMO_NETWORK, DEMO)
            for device in self.store.snapshot('demo')['devices']:
                if device['hostname'] and device['hostname'] != 'Desk speaker':
                    self.store.update_device(device['id'], dict(trusted=True))
            self.store.record_scan('demo', DEMO_NETWORK, DEMO[:-1])
        self.available = scanner.interfaces()
        saved = self.store.settings()
        self.config = dict(mode='demo', network=self.default_network(), interval=0,
                           alert_new=True, resume_schedule=False)
        self.config.update(saved)
        # Persistent monitoring requires the explicit resume switch in Settings.
        if not self.config['resume_schedule']:
            self.config['interval'] = 0
        self.last_attempt = time.monotonic()
        if self.config['mode'] == 'live' and leases_file:
            self.router.refresh(self.config['network'])

    def scope(self):
        return self.config['mode'], DEMO_NETWORK if self.config['mode'] == 'demo' else self.config['network']

    def default_network(self):
        if not self.available:
            return ''
        interface = self.available[0]
        n = scanner.ipaddress.ip_network(interface['cidr'])
        return str(n if n.prefixlen >= 24 else scanner.ipaddress.ip_network(interface['ip'] + '/24', strict=False))

    def state(self):
        with self.lock:
            mode = self.config['mode']
            return dict(**self.store.snapshot(mode, self.config['network'] if mode == 'live' else None), config=dict(self.config),
                        interfaces=self.available, scan=dict(self.status), demo=mode == 'demo',
                        alerts=self.store.alert_list(*self.scope()),
                        router=self.router.snapshot(self.config['network']) if mode == 'live' else
                        dict(configured=False, source='none', leases=[], stale=False, error=None),
                        monitoring=dict(resumes=self.config['resume_schedule'], scheduled=bool(self.config['interval'])))

    def configure(self, data):
        if set(data) - {'mode', 'network', 'interval', 'alert_new', 'resume_schedule'}:
            raise ValueError('Unsupported setting.')
        with self.lock:
            if self.status['running']:
                raise ValueError('Wait for the current scan to finish before changing settings.')
            config = {**self.config, **data}
            if config['mode'] not in ('demo', 'live'):
                raise ValueError('Choose demo or live mode.')
            if type(config['interval']) is not int or config['interval'] not in (0, 60, 300):
                raise ValueError('Choose manual, 1 minute, or 5 minutes.')
            for field in ('alert_new', 'resume_schedule'):
                if type(config[field]) is not bool:
                    raise ValueError(f'{field} must be true or false.')
            if config['mode'] == 'live':
                config['network'] = str(scanner.validate_network(config['network']))
            if config['mode'] != self.config['mode']:
                self.status = dict(running=False, error=None, started=None, finished=None)
            previous_network = self.config['network']
            self.config = config
            self.store.save_settings(config)
            if config['mode'] == 'live' and self.router.path and previous_network != config['network']:
                self.router.refresh(config['network'])
            self.last_attempt = time.monotonic()

    def start_scan(self):
        with self.lock:
            if self.status['running']:
                return False
            mode, network = self.config['mode'], self.config['network']
            if mode == 'live':
                scanner.validate_network(network)
            self.status.update(running=True, error=None, started=time.time())
            self.last_attempt = time.monotonic()
            self.worker = threading.Thread(target=self.perform_scan, args=(mode, network), daemon=True)
            self.worker.start()
            return True

    def perform_scan(self, mode, network):
        try:
            if mode == 'demo':
                time.sleep(0.8)
                observations, network = DEMO[:-1], DEMO_NETWORK
            else:
                self.router.refresh(network)
                observations = self.router.enrich(scanner.scan(network), network)
            self.store.record_scan(mode, network, observations, alert_new=self.config['alert_new'])
        except Exception as exc:
            LOG.exception('Scan failed')
            with self.lock:
                self.status['error'] = str(exc)
        finally:
            with self.lock:
                self.status.update(running=False, finished=time.time())

    def schedule(self):
        while not self.stop.wait(1):
            with self.lock:
                interval = self.config['interval']
                if interval and not self.status['running'] and time.monotonic() - self.last_attempt >= interval:
                    try:
                        self.start_scan()
                    except ValueError as exc:
                        self.status['error'] = str(exc)
                        self.last_attempt = time.monotonic()


class Handler(BaseHTTPRequestHandler):
    server_version = 'Lantern/1.1'

    def send(self, code, content, content_type='application/json; charset=utf-8'):
        body = json.dumps(content).encode() if not isinstance(content, bytes) else content
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, mutation=False):
        port = self.server.server_port
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            self.send(403, dict(error='Use the localhost address printed by Lantern.'))
            return False
        if mutation:
            origin = self.headers.get('Origin')
            if (origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')) or self.headers.get('X-Lantern') != '1':
                self.send(403, dict(error='Same-origin application requests only.'))
                return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        path = urlparse(self.path).path
        if path == '/api/state':
            return self.send(200, self.server.app.state())
        if path == '/api/export':
            return self.send(200, self.server.app.state())
        files = {'/': 'index.html', '/app.js': 'app.js', '/notifications.js': 'notifications.js', '/style.css': 'style.css', '/favicon.svg': 'favicon.svg'}
        if path not in files:
            return self.send(404, dict(error='Not found.'))
        file = ROOT / 'web' / files[path]
        self.send(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or 'application/octet-stream')

    def mutate(self):
        if not self.allowed(mutation=True):
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= 262144:
                raise ValueError('Request body is too large.')
            data = json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('Expected a JSON object.')
            path = urlparse(self.path).path
            if path == '/api/scan' and self.command == 'POST':
                started = self.server.app.start_scan()
                return self.send(202 if started else 409, dict(started=started))
            if path == '/api/settings' and self.command == 'PATCH':
                self.server.app.configure(data)
                return self.send(200, self.server.app.state())
            if path == '/api/alerts/ack' and self.command == 'POST':
                if set(data) - {'ids'}:
                    raise ValueError('Unsupported alert field.')
                with self.server.app.lock:
                    self.server.app.store.acknowledge_alerts(*self.server.app.scope(), data.get('ids'))
                return self.send(200, dict(ok=True))
            if path == '/api/alerts/claim' and self.command == 'POST':
                with self.server.app.lock:
                    alerts = self.server.app.store.claim_notifications(*self.server.app.scope())
                return self.send(200, dict(alerts=alerts))
            if path in ('/api/router/import', '/api/router/refresh') and self.command == 'POST':
                with self.server.app.lock:
                    if self.server.app.config['mode'] != 'live':
                        raise ValueError('Switch to live mode to connect router lease data.')
                    if self.server.app.status['running']:
                        raise ValueError('Wait for the current scan to finish.')
                    network = self.server.app.config['network']
                    if path.endswith('/import'):
                        if set(data) != {'text'}:
                            raise ValueError('Provide lease text only.')
                        router = self.server.app.router.import_text(data['text'], network)
                    else:
                        router = self.server.app.router.refresh(network)
                return self.send(200, router)
            if path.startswith('/api/devices/') and self.command == 'PATCH':
                device_id = int(path.rsplit('/', 1)[1])
                with self.server.app.lock:
                    if not any(d['id'] == device_id for d in self.server.app.state()['devices']):
                        raise LookupError('Device not found in this mode.')
                    self.server.app.store.update_device(device_id, data)
                return self.send(200, dict(ok=True))
            self.send(404, dict(error='Not found.'))
        except (ValueError, json.JSONDecodeError) as exc:
            self.send(400, dict(error=str(exc)))
        except LookupError as exc:
            self.send(404, dict(error=str(exc)))
        except Exception:
            LOG.exception('API error')
            self.send(500, dict(error='An internal error occurred. See the server log.'))

    do_POST = mutate
    do_PATCH = mutate

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        LOG.info(format, *args)


def main():
    parser = argparse.ArgumentParser(description='Lantern · local network visibility')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--log-file', help='Optional rotating log file (3 backups, 5 MiB each)')
    parser.add_argument('--leases-file', help='Read-only local or synced dnsmasq DHCP lease file')
    parser.add_argument('--db', default=os.environ.get('LANTERN_DB', str(ROOT / 'data' / 'lantern.sqlite3')))
    args = parser.parse_args()
    handlers = None
    if args.log_file:
        log_path = Path(args.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers = [RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3)]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', handlers=handlers)
    app = Application(args.db, args.leases_file)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.daemon_threads = True
    server.app = app
    threading.Thread(target=app.schedule, daemon=True).start()
    print(f'\n  Lantern is ready → http://localhost:{server.server_port}\n  Press Ctrl+C to stop.\n', flush=True)
    def terminate(_signum, _frame):
        app.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
        worker = getattr(app, 'worker', None)
        if worker:
            worker.join(timeout=25)


if __name__ == '__main__':
    main()
