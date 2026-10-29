"""Explicit LAN binding and request boundaries, with temporary synthetic records."""
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import review as r
from webapp import listen_host, make_server, serve


class LANTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = r.curriculum()

    def start(self, host=None):
        kwargs = {} if host is None else {'host': host}
        server = make_server(self.root, self.data, port=0, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def stop():
            server.shutdown(); server.server_close(); thread.join()
        self.addCleanup(stop)
        return server

    def request(self, server, address='127.0.0.1', method='GET', headers=None, body=None):
        client = http.client.HTTPConnection(address, server.server_port, timeout=3)
        try:
            client.request(method, '/api/state' if method == 'GET' else '/api/assign', body, headers or {})
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def test_default_stays_loopback_and_localhost_is_supported(self):
        server = self.start()
        self.assertEqual(server.server_address[0], '127.0.0.1')
        self.assertEqual(self.request(server)[0], 200)
        self.assertEqual(self.request(server, headers={'Host':f'localhost:{server.server_port}'})[0], 200)
        self.assertEqual(self.request(server, headers={'Host':f'192.0.2.1:{server.server_port}'})[0], 400)
        self.assertEqual(listen_host('localhost'), '127.0.0.1')
        self.assertFalse((self.root/'practice.csv').exists())

    def test_wildcard_accepts_actual_destination_and_same_origin_writes(self):
        server = self.start('0.0.0.0')
        self.assertEqual(server.server_address[0], '0.0.0.0')
        # A second loopback destination tests wildcard handling without depending on
        # a CI machine's interface names, LAN IP, or access to another computer.
        address = '127.0.0.2'
        code, state = self.request(server, address)
        self.assertEqual(code, 200)
        headers = {'Content-Type':'application/json', 'X-Jazz-Token':state['csrf_token'],
                   'Origin':f'http://{address}:{server.server_port}'}
        code, task = self.request(server, address, 'POST', headers, json.dumps({'exercise_id':'E01'}))
        self.assertEqual(code, 200)
        self.assertRegex(task['task_id'], '^T-')
        self.assertEqual(len(r.records(r.read_events(self.root))), 1)

    def test_explicit_address_is_honored(self):
        server = self.start('127.0.0.2')
        self.assertEqual(server.server_address[0], '127.0.0.2')
        self.assertEqual(self.request(server, '127.0.0.2')[0], 200)
        self.assertEqual(self.request(server, '127.0.0.2', headers={'Host':f'127.0.0.1:{server.server_port}'})[0], 400)

    def test_wildcard_does_not_allow_arbitrary_hosts_origins_or_missing_tokens(self):
        server = self.start('0.0.0.0')
        port = server.server_port
        _, state = self.request(server)
        good = {'Content-Type':'application/json', 'X-Jazz-Token':state['csrf_token']}
        bad = [good | {'Host':f'attacker.example:{port}'},
               good | {'Host':f'192.0.2.1:{port}'},
               good | {'Host':f'0.0.0.0:{port}'},
               good | {'Origin':f'http://127.0.0.1:{port+1}'},
               good | {'Origin':f'http://localhost:{port}'},
               good | {'Origin':f'https://127.0.0.1:{port}'},
               good | {'Origin':'null'},
               good | {'Origin':'http://attacker.example'},
               good | {'X-Jazz-Token':''}]
        for headers in bad:
            with self.subTest(headers=headers):
                self.assertEqual(self.request(server, method='POST', headers=headers,
                                              body=json.dumps({'exercise_id':'E01'}))[0], 400)
        self.assertFalse((self.root/'practice.csv').exists())

    def test_duplicate_host_or_origin_headers_are_rejected(self):
        server = self.start('0.0.0.0')
        for duplicate in ('Host','Origin'):
            client = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            try:
                client.putrequest('GET','/api/state',skip_host=True)
                client.putheader('Host',f'127.0.0.1:{server.server_port}')
                if duplicate == 'Host':
                    client.putheader('Host','attacker.example')
                else:
                    client.putheader('Origin',f'http://127.0.0.1:{server.server_port}')
                    client.putheader('Origin','http://attacker.example')
                client.endheaders()
                response = client.getresponse(); response.read()
                self.assertEqual(response.status,400)
            finally:
                client.close()

    def test_invalid_host_rejected_before_starting_or_creating_data(self):
        for host in ('',None,0,'example.com','http://127.0.0.1','127.0.0.1:8768','::1','224.0.0.1','255.255.255.255'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                make_server(self.root,self.data,port=0,host=host)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_forwards_host_and_wildcard_open_uses_a_valid_loopback_url(self):
        with patch('webapp.serve') as mocked:
            self.assertEqual(r.main(['--practice-root',str(self.root),'serve','--host','0.0.0.0','--port','8768','--open']),0)
            self.assertEqual(mocked.call_args.kwargs,{'host':'0.0.0.0'})
            self.assertEqual(mocked.call_args.args[2:],(8768,True))
        with patch('webapp.ThreadingHTTPServer.serve_forever'), patch('webapp.webbrowser.open') as opened, redirect_stdout(io.StringIO()) as output:
            serve(self.root,self.data,port=0,open_browser=True,host='0.0.0.0')
        self.assertRegex(opened.call_args.args[0],r'^http://127\.0\.0\.1:\d+$')
        self.assertIn('Listening on 0.0.0.0:',output.getvalue())
