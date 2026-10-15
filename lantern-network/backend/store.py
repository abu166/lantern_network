"""SQLite persistence. Each operation gets its own connection and transaction."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, identity TEXT NOT NULL,
                    ip TEXT NOT NULL, mac TEXT, hostname TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'device',
                    trusted INTEGER NOT NULL DEFAULT 0, online INTEGER NOT NULL DEFAULT 1,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, latency REAL,
                    network TEXT NOT NULL, UNIQUE(mode, identity));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, device_id INTEGER,
                    type TEXT NOT NULL, at TEXT NOT NULL, message TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, at TEXT NOT NULL,
                    network TEXT NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY, mode TEXT NOT NULL, network TEXT NOT NULL,
                    device_id INTEGER NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL,
                    created TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0,
                    notified INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS alerts_scope ON alerts(mode,network,id);

            ''')
            # Additive migrations preserve existing inventories and recognition decisions.
            columns = {row['name'] for row in db.execute('PRAGMA table_info(devices)')}
            for name, definition in {
                'room': "TEXT NOT NULL DEFAULT ''", 'notes': "TEXT NOT NULL DEFAULT ''",
                'watched': 'INTEGER NOT NULL DEFAULT 0',
                'miss_threshold': 'INTEGER NOT NULL DEFAULT 2',
                'misses': 'INTEGER NOT NULL DEFAULT 0',
                'watch_alerted': 'INTEGER NOT NULL DEFAULT 0',
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE devices ADD COLUMN {name} {definition}')
            db.execute('PRAGMA user_version=2')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record_scan(self, mode, network, observations, alert_new=True):
        timestamp = now()
        with self.db() as db:
            baseline_exists = db.execute('SELECT 1 FROM scans WHERE mode=? AND network=? LIMIT 1',
                                         (mode, network)).fetchone() is not None
            previous = {r['identity']: dict(r) for r in db.execute(
                'SELECT * FROM devices WHERE mode=? AND network=?', (mode, network))}
            seen = set()
            for item in observations:
                identity = item.get('mac') or 'ip:' + item['ip']
                seen.add(identity)
                # Upgrade an IP-only identity when a MAC becomes available.
                old = previous.get(identity)
                if old is None:
                    old = db.execute('SELECT * FROM devices WHERE mode=? AND identity=?', (mode, identity)).fetchone()
                if old is None:
                    old = previous.get('ip:' + item['ip'])
                if old:
                    db.execute('''UPDATE devices SET identity=?, ip=?, mac=?, hostname=?, online=1,
                        last_seen=?, latency=?, network=?, misses=0, watch_alerted=0 WHERE id=?''',
                        (identity, item['ip'], item.get('mac'), item.get('hostname') or old['hostname'],
                         timestamp, item.get('latency'), network, old['id']))
                    if not old['online']:
                        self.event(db, mode, old['id'], 'returned', timestamp, 'Device seen again')
                    if old['watched'] and old['watch_alerted']:
                        self.alert(db, mode, network, old['id'], 'watch_returned', timestamp,
                                   'Watched device is responding again')
                    seen.add(old['identity'])
                else:
                    cursor = db.execute('''INSERT INTO devices
                        (mode,identity,ip,mac,hostname,kind,first_seen,last_seen,latency,network)
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (mode, identity, item['ip'], item.get('mac'), item.get('hostname', ''),
                         item.get('kind', 'device'), timestamp, timestamp, item.get('latency'), network))
                    self.event(db, mode, cursor.lastrowid, 'discovered', timestamp, 'New device discovered')
                    # The first scan establishes the baseline instead of flooding the inbox.
                    if baseline_exists and alert_new:
                        self.alert(db, mode, network, cursor.lastrowid, 'new_device', timestamp,
                                   'A new device responded on your network')
            for identity, old in previous.items():
                if identity not in seen:
                    misses = old['misses'] + 1
                    db.execute('UPDATE devices SET online=0, latency=NULL, misses=? WHERE id=?', (misses, old['id']))
                    if old['online']:
                        self.event(db, mode, old['id'], 'unseen', timestamp, 'Device did not respond to this scan')
                    if old['watched'] and not old['watch_alerted'] and misses >= old['miss_threshold']:
                        db.execute('UPDATE devices SET watch_alerted=1 WHERE id=?', (old['id'],))
                        self.alert(db, mode, network, old['id'], 'watch_missing', timestamp,
                                   f'Watched device did not respond to {misses} consecutive scans')
            db.execute('INSERT INTO scans(mode,at,network,count) VALUES (?,?,?,?)',
                       (mode, timestamp, network, len(observations)))
            db.execute('DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT 1000)')
            # Bounded history; device inventory and labels are retained.
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 5000)')
            db.execute('DELETE FROM scans WHERE id NOT IN (SELECT id FROM scans ORDER BY id DESC LIMIT 2000)')

    @staticmethod
    def event(db, mode, device, kind, at, message):
        db.execute('INSERT INTO events(mode,device_id,type,at,message) VALUES (?,?,?,?,?)',
                   (mode, device, kind, at, message))

    @staticmethod
    def alert(db, mode, network, device, kind, at, message):
        db.execute('''INSERT INTO alerts(mode,network,device_id,kind,created,message)
                      VALUES (?,?,?,?,?,?)''', (mode, network, device, kind, at, message))
        Store.event(db, mode, device, kind, at, message)

    def alert_list(self, mode, network):
        with self.db() as db:
            return self._alerts(db, mode, network)

    @staticmethod
    def _alerts(db, mode, network):
        return [dict(r) for r in db.execute('''SELECT a.*,d.label,d.hostname,d.ip,d.room
            FROM alerts a LEFT JOIN devices d ON a.device_id=d.id
            WHERE a.mode=? AND a.network=? ORDER BY a.id DESC LIMIT 1000''', (mode, network))]

    def acknowledge_alerts(self, mode, network, ids=None):
        if ids is not None and (not isinstance(ids, list) or len(ids) > 1000 or
                                any(type(i) is not int or i < 1 for i in ids)):
            raise ValueError('Expected a list of positive alert IDs.')
        with self.db() as db:
            if ids is None:
                db.execute('UPDATE alerts SET read=1,notified=1 WHERE mode=? AND network=?', (mode, network))
            else:
                for alert_id in ids:
                    db.execute('UPDATE alerts SET read=1,notified=1 WHERE id=? AND mode=? AND network=?',
                               (alert_id, mode, network))

    def claim_notifications(self, mode, network):
        # Transactional claim prevents duplicate desktop alerts across tabs.
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            alerts = [a for a in self._alerts(db, mode, network) if not a['notified'] and not a['read']]
            db.execute('UPDATE alerts SET notified=1 WHERE mode=? AND network=? AND notified=0', (mode, network))
            return alerts

    def snapshot(self, mode, network=None):
        with self.db() as db:
            devices = [dict(r) for r in db.execute('SELECT * FROM devices WHERE mode=? AND (? IS NULL OR network=?) ORDER BY online DESC,ip', (mode, network, network))]
            events = [dict(r) for r in db.execute('''SELECT e.*,d.label,d.hostname,d.ip FROM events e
                LEFT JOIN devices d ON e.device_id=d.id WHERE e.mode=? AND (? IS NULL OR d.network=?) ORDER BY e.id DESC LIMIT 100''', (mode, network, network))]
            scans = [dict(r) for r in db.execute('SELECT * FROM scans WHERE mode=? AND (? IS NULL OR network=?) ORDER BY id DESC LIMIT 48', (mode, network, network))]
        return dict(devices=devices, events=events, scans=list(reversed(scans)))

    def update_device(self, device_id, data):
        if set(data) - {'label', 'trusted', 'kind', 'room', 'notes', 'watched', 'miss_threshold'}:
            raise ValueError('Unsupported device field.')
        if 'label' in data and (not isinstance(data['label'], str) or len(data['label']) > 60):
            raise ValueError('Device names must be 60 characters or fewer.')
        if 'trusted' in data and not isinstance(data['trusted'], bool):
            raise ValueError('Trusted must be true or false.')
        if 'kind' in data and data['kind'] not in ('computer', 'phone', 'tv', 'router', 'device'):
            raise ValueError('Choose a supported device type.')
        for field, limit in (('room', 60), ('notes', 1000)):
            if field in data and (not isinstance(data[field], str) or len(data[field]) > limit):
                raise ValueError(f'{field.capitalize()} must be {limit} characters or fewer.')
        if 'watched' in data and type(data['watched']) is not bool:
            raise ValueError('Watched must be true or false.')
        if 'miss_threshold' in data and (type(data['miss_threshold']) is not int or not 1 <= data['miss_threshold'] <= 10):
            raise ValueError('Choose between 1 and 10 consecutive missed scans.')
        with self.db() as db:
            row = db.execute('SELECT * FROM devices WHERE id=?', (device_id,)).fetchone()
            if not row:
                raise LookupError('Device not found.')
            for field, value in data.items():
                db.execute(f'UPDATE devices SET {field}=? WHERE id=?', (value, device_id))
            if any(field in data and row[field] != data[field] for field in ('watched', 'miss_threshold')):
                db.execute('UPDATE devices SET misses=0,watch_alerted=0 WHERE id=?', (device_id,))
                self.event(db, row['mode'], device_id, 'watch_changed', now(),
                           'Device watch settings updated')
            if 'trusted' in data and bool(row['trusted']) != data['trusted']:
                self.event(db, row['mode'], device_id, 'trusted' if data['trusted'] else 'review', now(),
                           'Marked as trusted' if data['trusted'] else 'Marked for review')

    def settings(self):
        with self.db() as db:
            return {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}

    def save_settings(self, values):
        with self.db() as db:
            for key, value in values.items():
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
