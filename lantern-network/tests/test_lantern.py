import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from backend import scanner
from backend.server import Application, Handler
from backend.store import Store

INTERFACES = [dict(name='en0', ip='192.168.1.10', cidr='192.168.1.0/24')]
DEVICE = dict(ip='192.168.1.20', mac='02:00:00:00:00:01', hostname='', latency=2)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_survives_ip_change_and_persists_labels(self):
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        device = self.store.snapshot('live')['devices'][0]
        self.store.update_device(device['id'], dict(label='My phone', trusted=True))
        self.store.record_scan('live', '192.168.1.0/24', [{**DEVICE, 'ip': '192.168.1.21'}])
        devices = Store(self.path).snapshot('live')['devices']
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['label'], 'My phone')
        self.assertEqual(devices[0]['ip'], '192.168.1.21')
        self.assertEqual(devices[0]['trusted'], 1)

    def test_ip_identity_upgrades_to_mac_without_losing_label(self):
        self.store.record_scan('live', '192.168.1.0/24', [{**DEVICE, 'mac': None}])
        device = self.store.snapshot('live')['devices'][0]
        self.store.update_device(device['id'], dict(label='Laptop'))
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        devices = self.store.snapshot('live')['devices']
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]['identity'], DEVICE['mac'])
        self.assertEqual(devices[0]['label'], 'Laptop')
        self.assertEqual(devices[0]['online'], 1)

    def test_observation_events_and_demo_isolation(self):
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        self.store.record_scan('demo', '192.168.1.0/24', [DEVICE])
        self.store.record_scan('live', '192.168.1.0/24', [])
        self.store.record_scan('live', '192.168.1.0/24', [])
        self.assertEqual(self.store.snapshot('live')['devices'][0]['online'], 0)
        self.assertEqual(self.store.snapshot('demo')['devices'][0]['online'], 1)
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        kinds = [e['type'] for e in self.store.snapshot('live')['events']]
        self.assertEqual(kinds, ['returned', 'unseen', 'discovered'])

    def test_network_views_do_not_mix_devices_or_scan_history(self):
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        self.store.record_scan('live', '192.168.2.0/24', [{**DEVICE, 'ip':'192.168.2.9', 'mac':'02:00:00:00:00:02'}])
        view = self.store.snapshot('live', '192.168.2.0/24')
        self.assertEqual(len(view['devices']), 1)
        self.assertEqual(view['devices'][0]['ip'], '192.168.2.9')
        self.assertEqual(len(view['scans']), 1)
        self.assertEqual(len(view['events']), 1)

    def test_invalid_updates(self):
        self.store.record_scan('live', '192.168.1.0/24', [DEVICE])
        device = self.store.snapshot('live')['devices'][0]
        for value in ({'trusted': 'yes'}, {'label': 'x'*61}, {'kind': 'invalid'}, {'ip': '1.1.1.1'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.update_device(device['id'], value)


class ScannerTests(unittest.TestCase):
    def test_only_bounded_directly_attached_private_networks(self):
        self.assertEqual(str(scanner.validate_network('192.168.1.5/24', INTERFACES)), '192.168.1.0/24')
        for cidr in ['8.8.8.0/24','127.0.0.0/24','192.168.1.0/16','192.168.1.1/32','192.168.2.0/24','::1/128','; rm -rf /','bad']:
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                scanner.validate_network(cidr, INTERFACES)

    @patch('backend.scanner.platform.system', return_value='Darwin')
    @patch('backend.scanner.run')
    def test_macos_interface_and_neighbor_parsing(self, run, _system):
        run.return_value = 'en0: flags=8863\n\tinet 192.168.1.10 netmask 0xffffff00 broadcast 192.168.1.255\nutun0: flags=8051\n\tinet 10.0.0.1 netmask 0xffffff00\n'
        self.assertEqual(scanner.interfaces(), INTERFACES)
        run.return_value = '? (192.168.1.20) at 2:0:0:0:0:1 on en0 ifscope [ethernet]\n? (192.168.1.21) at (incomplete) on en0\n'
        self.assertEqual(scanner.arp_entries(), {'192.168.1.20':'02:00:00:00:00:01'})

    @patch('backend.scanner.interfaces', return_value=INTERFACES)
    @patch('backend.scanner.shutil.which', return_value='/sbin/ping')
    @patch('backend.scanner.arp_entries', return_value={'192.168.1.2':'02:00:00:00:00:02'})
    @patch('backend.scanner.ping', side_effect=lambda ip:(ip,None))
    def test_stale_arp_is_not_online(self, *_):
        self.assertEqual(scanner.scan('192.168.1.0/30'), [])


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with patch('backend.scanner.interfaces', return_value=INTERFACES):
            self.app = Application(Path(self.tmp.name)/'test.sqlite3')
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        h = {'X-Lantern':'1', 'Content-Type':'application/json'}
        h.update(headers or {})
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse()
        code, content, response_headers = r.status, r.read(), dict(r.headers)
        c.close()
        return code,content,response_headers

    def test_static_api_and_security_headers(self):
        status, content, headers = self.request('GET','/')
        self.assertEqual(status,200)
        self.assertIn(b'Lantern',content)
        self.assertIn('Content-Security-Policy',headers)
        status, content, _ = self.request('GET','/api/state')
        self.assertTrue(json.loads(content)['demo'])
        self.assertEqual(len(json.loads(content)['devices']),8)
        self.assertEqual(self.request('GET','/../backend/server.py')[0],404)
        self.assertEqual(self.request('GET','/api/state',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('PATCH','/api/settings',{}, {'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/scan',{}, {'X-Lantern':''})[0],403)

    def test_edit_export_and_validation(self):
        device=self.app.state()['devices'][0]
        status,_,_=self.request('PATCH',f"/api/devices/{device['id']}",{'label':'A renamed device','trusted':True})
        self.assertEqual(status,200)
        _,content,_=self.request('GET','/api/export')
        self.assertIn('A renamed device',[d['label'] for d in json.loads(content)['devices']])
        self.assertEqual(self.request('PATCH','/api/settings',{'interval':-1})[0],400)
        self.assertEqual(self.request('PATCH','/api/settings',{'mode':'other'})[0],400)
        self.assertEqual(self.request('PATCH','/api/devices/9999',{'label':'x'})[0],404)

    def test_single_scan_and_failed_scan_preserves_inventory(self):
        self.app.config.update(mode='live',network='192.168.1.0/24')
        self.app.store.record_scan('live','192.168.1.0/24',[DEVICE])
        device=self.app.state()['devices'][0]
        self.app.store.update_device(device['id'],dict(watched=True,miss_threshold=1))
        self.app.status['running']=True
        self.assertEqual(self.request('POST','/api/scan',{})[0],409)
        with self.assertLogs('lantern', level='ERROR'), patch('backend.scanner.scan',side_effect=RuntimeError('Network unavailable')):
            self.app.perform_scan('live','192.168.1.0/24')
        self.assertFalse(self.app.status['running'])
        self.assertEqual(self.app.state()['devices'][0]['online'],1)
        self.assertEqual(self.app.status['error'],'Network unavailable')
        self.assertEqual(self.app.state()['devices'][0]['misses'],0)
        self.assertEqual(self.app.state()['alerts'],[])

    def test_alert_inbox_claims_and_acknowledgments(self):
        from backend.server import DEMO, DEMO_NETWORK
        extra = {**DEVICE, 'ip':'192.168.1.99'}
        self.app.store.record_scan('demo',DEMO_NETWORK,DEMO+[extra])
        _,content,_ = self.request('GET','/api/state')
        alerts = json.loads(content)['alerts']
        self.assertEqual(len(alerts),1)
        _,content,_ = self.request('POST','/api/alerts/claim',{})
        self.assertEqual(len(json.loads(content)['alerts']),1)
        _,content,_ = self.request('POST','/api/alerts/claim',{})
        self.assertEqual(json.loads(content)['alerts'],[])
        self.assertEqual(self.request('POST','/api/alerts/ack',{'ids':['bad']})[0],400)
        self.assertEqual(self.request('POST','/api/alerts/ack',{'ids':[alerts[0]['id']]})[0],200)
        self.assertEqual(self.app.state()['alerts'][0]['read'],1)

    def test_router_import_and_device_metadata(self):
        self.assertEqual(self.request('POST','/api/router/import',{'text':''})[0],400)
        self.app.config.update(mode='live',network='192.168.1.0/24')
        self.app.store.record_scan('live','192.168.1.0/24',[DEVICE])
        text='0 02:00:00:00:00:01 192.168.1.20 printer *'
        code,content,_=self.request('POST','/api/router/import',{'text':text})
        self.assertEqual(code,200)
        self.assertEqual(json.loads(content)['leases'][0]['hostname'],'printer')
        self.assertEqual(self.request('POST','/api/router/import',{'text':text,'path':'/etc/passwd'})[0],400)
        self.assertEqual(self.request('POST','/api/router/import',{'text':'invalid'})[0],400)
        device=self.app.state()['devices'][0]
        self.assertEqual(self.request('PATCH',f"/api/devices/{device['id']}",
            {'room':'Office','notes':'Printer','watched':True,'miss_threshold':3})[0],200)
        device=self.app.state()['devices'][0]
        self.assertEqual(device['room'],'Office')
        self.assertEqual(device['notes'],'Printer')
        self.assertEqual(device['watched'],1)
        self.assertEqual(device['miss_threshold'],3)

    def test_settings_restart_resets_scheduler(self):
        self.app.configure({'interval':60})
        with patch('backend.scanner.interfaces',return_value=INTERFACES):
            restarted=Application(Path(self.tmp.name)/'test.sqlite3')
        self.assertEqual(restarted.config['interval'],0)


if __name__=='__main__':
    unittest.main()
