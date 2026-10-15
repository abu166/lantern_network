"""Read-only dnsmasq lease snapshots; a lease is not proof of online presence."""
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import re
import stat
import time

MAX_BYTES = 1024 * 1024
MAC = re.compile(r'^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')


def parse_leases(text, network, timestamp=None):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Lease snapshots must be text smaller than 1 MiB.')
    subnet = ipaddress.ip_network(network)
    timestamp = time.time() if timestamp is None else timestamp
    leases, skipped = {}, 0
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split()
        try:
            if len(parts) != 5 or not MAC.fullmatch(parts[1]):
                raise ValueError()
            expiry, mac, ip, hostname, _client = parts
            expiry = int(expiry)
            ip = ipaddress.IPv4Address(ip)
            if expiry < 0 or expiry > 253402300799 or int(mac[:2], 16) & 1 or mac == '00:00:00:00:00:00':
                raise ValueError()
            if ip not in subnet or ip in (subnet.network_address, subnet.broadcast_address):
                continue
            if expiry and expiry <= timestamp:
                continue
            leases[mac.lower()] = dict(mac=mac.lower(), ip=str(ip), hostname='' if hostname == '*' else hostname[:253],
                expires=datetime.fromtimestamp(expiry, timezone.utc).isoformat() if expiry else None)
        except (ValueError, OverflowError, OSError):
            skipped += 1
    if text.strip() and not leases and skipped:
        raise ValueError('No valid dnsmasq IPv4 lease rows found. Expected: expiry MAC IP hostname client-id.')
    return list(leases.values()), skipped


class RouterSource:
    def __init__(self, path=None, max_age=600):
        self.path = Path(path).expanduser().resolve() if path else None
        self.max_age = max_age
        self.view = dict(configured=bool(path), source='dnsmasq file' if path else 'none',
                         leases=[], checked=None, updated=None, stale=False, error=None, skipped=0, network=None)

    def refresh(self, network):
        if not self.path:
            return self.snapshot(network)
        try:
            # Non-blocking open plus regular-file validation avoids hangs on a FIFO/device.
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Lease source must be a regular file.')
                raw = source.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError('Lease file is larger than 1 MiB.')
            leases, skipped = parse_leases(raw.decode('utf-8'), network)
            self.view.update(leases=leases, updated=datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                             stale=time.time()-info.st_mtime > self.max_age, error=None, skipped=skipped, network=network)
        except (OSError, ValueError, UnicodeError):
            # Do not leak operator filesystem paths through the API.
            self.view.update(leases=[], stale=True, error='Could not read a valid lease file. Check its path, permissions, and format.', network=network)
        self.view['checked'] = datetime.now(timezone.utc).isoformat()
        return self.snapshot(network)

    def import_text(self, text, network):
        if self.path:
            raise ValueError('A lease file is configured. Update that file to refresh router data.')
        leases, skipped = parse_leases(text, network)
        timestamp = datetime.now(timezone.utc).isoformat()
        self.view.update(configured=True, source='manual snapshot', leases=leases, checked=timestamp,
                         updated=timestamp, stale=False, error=None, skipped=skipped, network=network)
        return self.snapshot(network)

    def snapshot(self, network):
        view = {**self.view, 'leases': list(self.view['leases'])}
        if view['network'] != network:
            view.update(leases=[], stale=bool(view['configured']))
        if view['updated'] and time.time()-datetime.fromisoformat(view['updated']).timestamp() > self.max_age:
            view['stale'] = True
        # Re-filter expirations even if no scan has run since the last refresh.
        view['leases'] = [l for l in view['leases'] if not l['expires'] or datetime.fromisoformat(l['expires']).timestamp() > time.time()]
        return view

    def enrich(self, observations, network):
        view = self.snapshot(network)
        if view['stale'] or view['error']:
            return observations
        leases = {l['mac']: l for l in view['leases']}
        return [{**item, 'hostname': item.get('hostname') or
                 (leases.get(item.get('mac'), {}).get('hostname', '')
                  if leases.get(item.get('mac'), {}).get('ip') == item['ip'] else '')}
                for item in observations]
