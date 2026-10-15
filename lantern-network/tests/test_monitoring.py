import concurrent.futures
from datetime import datetime, timezone
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.router import RouterSource, parse_leases
from backend.server import Application
from backend.store import Store
from scripts.service import generate

NETWORK = '192.168.1.0/24'
DEVICE = dict(ip='192.168.1.20', mac='02:00:00:00:00:01', hostname='', latency=2)
SECOND = dict(ip='192.168.1.21', mac='02:00:00:00:00:02', hostname='', latency=4)
INTERFACES = [dict(name='en0', ip='192.168.1.10', cidr=NETWORK)]


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.db'
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_scan_is_baseline_and_new_alert_is_persistent(self):
        self.store.record_scan('live', NETWORK, [DEVICE])
        self.assertEqual(self.store.alert_list('live',NETWORK), [])
        self.store.record_scan('live', NETWORK, [DEVICE,SECOND])
        alerts = Store(self.path).alert_list('live',NETWORK)
        self.assertEqual([a['kind'] for a in alerts], ['new_device'])
        self.store.record_scan('live', NETWORK, [DEVICE,SECOND])
        self.assertEqual(len(self.store.alert_list('live',NETWORK)),1)
        self.assertEqual(self.store.alert_list('demo',NETWORK),[])
        self.assertEqual(self.store.alert_list('live','192.168.2.0/24'),[])

    def test_watched_threshold_and_recovery_do_not_repeat(self):
        self.store.record_scan('live', NETWORK, [DEVICE])
        device = self.store.snapshot('live')['devices'][0]
        self.store.update_device(device['id'],dict(watched=True, miss_threshold=2, room='Office', notes='Printer'))
        self.store.record_scan('live', NETWORK, [])
        self.assertEqual(self.store.alert_list('live',NETWORK),[])
        self.store.record_scan('live', NETWORK, [])
        self.store.record_scan('live', NETWORK, [])
        alerts = self.store.alert_list('live',NETWORK)
        self.assertEqual([a['kind'] for a in alerts],['watch_missing'])
        self.assertEqual(alerts[0]['room'],'Office')
        self.store.record_scan('live', NETWORK, [DEVICE])
        self.store.record_scan('live', NETWORK, [DEVICE])
        self.assertEqual([a['kind'] for a in self.store.alert_list('live',NETWORK)],['watch_returned','watch_missing'])
        device = self.store.snapshot('live')['devices'][0]
        self.assertEqual(device['misses'],0)
        self.assertEqual(device['notes'],'Printer')
        self.assertEqual(device['watch_alerted'],0)

    def test_turning_watch_off_resets_pending_loss(self):
        self.store.record_scan('live', NETWORK, [DEVICE])
        device = self.store.snapshot('live')['devices'][0]
        self.store.update_device(device['id'],dict(watched=True,miss_threshold=1))
        self.store.record_scan('live', NETWORK, [])
        self.store.update_device(device['id'],dict(watched=False))
        self.store.record_scan('live', NETWORK, [DEVICE])
        self.assertEqual(len(self.store.alert_list('live',NETWORK)),1)

    def test_disabled_new_discovery_alerts_and_atomic_claims(self):
        self.store.record_scan('live',NETWORK,[DEVICE])
        self.store.record_scan('live',NETWORK,[DEVICE,SECOND],alert_new=False)
        self.assertEqual(self.store.alert_list('live',NETWORK),[])
        device=self.store.snapshot('live')['devices'][0]
        self.store.update_device(device['id'],dict(watched=True,miss_threshold=1))
        self.store.record_scan('live',NETWORK,[SECOND])
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            claims=list(pool.map(lambda _:self.store.claim_notifications('live',NETWORK),range(6)))
        self.assertEqual(sum(map(len,claims)),1)
        self.store.acknowledge_alerts('demo',NETWORK)
        self.assertEqual(self.store.alert_list('live',NETWORK)[0]['read'],0)
        alert_id=self.store.alert_list('live',NETWORK)[0]['id']
        self.store.acknowledge_alerts('live',NETWORK,[alert_id])
        self.assertEqual(self.store.alert_list('live',NETWORK)[0]['read'],1)

    def test_new_fields_validation(self):
        self.store.record_scan('live',NETWORK,[DEVICE])
        device=self.store.snapshot('live')['devices'][0]
        for data in ({'watched':'yes'},{'miss_threshold':0},{'miss_threshold':True},{'notes':'x'*1001},{'room':None}):
            with self.subTest(data=data),self.assertRaises(ValueError):
                self.store.update_device(device['id'],data)

    def test_migration_preserves_v1_records(self):
        legacy=Path(self.tmp.name)/'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.executescript('''CREATE TABLE devices (
                id INTEGER PRIMARY KEY, mode TEXT NOT NULL, identity TEXT NOT NULL,
                ip TEXT NOT NULL, mac TEXT, hostname TEXT NOT NULL DEFAULT '',
                label TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'device',
                trusted INTEGER NOT NULL DEFAULT 0, online INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,latency REAL,
                network TEXT NOT NULL, UNIQUE(mode,identity));
                INSERT INTO devices(mode,identity,ip,label,trusted,first_seen,last_seen,network)
                VALUES('live','ip:192.168.1.20','192.168.1.20','My printer',1,'2026-01-01','2026-01-01','192.168.1.0/24');''')
        migrated=Store(legacy)
        device=migrated.snapshot('live')['devices'][0]
        self.assertEqual(device['label'],'My printer')
        self.assertEqual(device['trusted'],1)
        self.assertEqual(device['room'],'')
        self.assertEqual(device['miss_threshold'],2)
        self.assertEqual(Store(legacy).snapshot('live')['devices'][0]['label'],'My printer')

    def test_scheduler_runs_without_a_browser_and_retries_validation_failures(self):
        with patch('backend.scanner.interfaces',return_value=INTERFACES):
            app=Application(self.path)
        app.config['interval']=60
        app.last_attempt=time.monotonic()-61
        with patch.object(app.stop,'wait',side_effect=[False,True]), patch.object(app,'start_scan') as start:
            app.schedule()
            start.assert_called_once()
        app.last_attempt=time.monotonic()-61
        with patch.object(app.stop,'wait',side_effect=[False,True]), patch.object(app,'start_scan',side_effect=ValueError('Network unavailable')):
            app.schedule()
        self.assertEqual(app.status['error'],'Network unavailable')
        self.assertLess(time.monotonic()-app.last_attempt,1)

    def test_monitoring_schedule_requires_explicit_resume(self):
        with patch('backend.scanner.interfaces',return_value=INTERFACES):
            app=Application(self.path)
            app.configure(dict(interval=60,resume_schedule=True))
            self.assertEqual(Application(self.path).config['interval'],60)
            app.configure(dict(resume_schedule=False))
            self.assertEqual(Application(self.path).config['interval'],0)
            with self.assertRaises(ValueError):
                app.configure(dict(resume_schedule='true'))


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'dhcp.leases'
        self.expiry=int(time.time())+3600
        self.text=f'{self.expiry} {DEVICE["mac"]} {DEVICE["ip"]} printer *\n'

    def tearDown(self):
        self.tmp.cleanup()

    def test_scope_expiry_and_invalid_rows(self):
        leases,skipped=parse_leases(self.text+'1 02:00:00:00:00:02 192.168.1.21 old *\n'+
            f'{self.expiry} 02:00:00:00:00:03 10.0.0.2 other *\ninvalid\n',NETWORK)
        self.assertEqual(len(leases),1)
        self.assertEqual(leases[0]['hostname'],'printer')
        self.assertEqual(skipped,1)
        with self.assertRaises(ValueError):parse_leases('invalid',NETWORK)
        leases,_=parse_leases(f'0 {DEVICE["mac"]} {DEVICE["ip"]} * *',NETWORK)
        self.assertIsNone(leases[0]['expires'])
        self.assertEqual(leases[0]['hostname'],'')

    def test_live_file_enrichment_does_not_invent_ping_responses(self):
        self.path.write_text(self.text)
        source=RouterSource(self.path)
        view=source.refresh(NETWORK)
        self.assertFalse(view['stale'])
        self.assertEqual(source.enrich([DEVICE],NETWORK)[0]['hostname'],'printer')
        self.assertEqual(source.enrich([],NETWORK),[])
        mismatch={**DEVICE,'ip':'192.168.1.30'}
        self.assertEqual(source.enrich([mismatch],NETWORK)[0]['hostname'],'')
        os.utime(self.path,(time.time()-1000,time.time()-1000))
        self.assertTrue(source.refresh(NETWORK)['stale'])
        self.assertEqual(source.enrich([DEVICE],NETWORK)[0]['hostname'],'')
        self.assertEqual(source.snapshot('192.168.2.0/24')['leases'],[])

    def test_manual_import_is_validated_and_memory_only(self):
        source=RouterSource()
        self.assertEqual(source.import_text(self.text,NETWORK)['source'],'manual snapshot')
        self.assertEqual(len(source.snapshot(NETWORK)['leases']),1)
        self.assertEqual(RouterSource().snapshot(NETWORK)['leases'],[])
        with self.assertRaises(ValueError):source.import_text('not a lease',NETWORK)
        self.assertEqual(len(source.snapshot(NETWORK)['leases']),1)

    def test_missing_file_and_fifo_are_safe(self):
        source=RouterSource(self.path)
        self.assertIsNotNone(source.refresh(NETWORK)['error'])
        self.assertNotIn(self.tmp.name,source.view['error'])
        if hasattr(os,'mkfifo'):
            os.mkfifo(self.path)
            self.assertIsNotNone(source.refresh(NETWORK)['error'])


class ServiceTests(unittest.TestCase):
    def test_plist_is_valid_and_does_not_expose_server(self):
        name,content=generate('macos',root='/tmp/lantern folder',python='/usr/bin/python3')
        p=plistlib.loads(content)
        self.assertTrue(p['KeepAlive'])
        self.assertEqual(p['ProgramArguments'][1:3],['-m','backend.server'])
        self.assertNotIn('--host',p['ProgramArguments'])
        self.assertIn('/usr/sbin',p['EnvironmentVariables']['PATH'])

    def test_linux_unit_quotes_paths_and_includes_restart(self):
        name,content=generate('linux',root='/tmp/lantern folder %test',python='/usr/bin/python3')
        text=content.decode()
        self.assertIn('WorkingDirectory="'+str(Path('/tmp/lantern folder %%test').resolve())+'"',text)
        self.assertIn('Restart=on-failure',text)
        self.assertIn('NoNewPrivileges=true',text)
        self.assertNotIn('sudo',text)
