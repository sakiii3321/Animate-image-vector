"""One real local-refinement HTTP cycle plus request/cancellation protection."""
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from main import AppServer


def sample():
    image = Image.new('RGB', (96, 64), '#edf1e5')
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 10, 80, 54), fill='#e6917d')
    draw.ellipse((35, 16, 66, 46), fill='#29567f')
    draw.line((20, 45, 72, 20), fill='#21242e', width=2)
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


class RefinementHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.server = AppServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)
        self.temporary.cleanup()

    def request(self, path, payload=None, *, token=True, origin=True, expected=200):
        headers = {}
        if token:
            headers['X-App-Token'] = self.server.token if token is True else token
        if payload is not None:
            headers['Content-Type'] = 'application/json'
            if origin:
                headers['Origin'] = self.server.origin if origin is True else origin
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(self.server.origin+path, data=body, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.assertEqual(response.status, expected, response.read().decode('utf-8', errors='replace') if response.status != expected else '')
            data = response.read()
            return json.loads(data) if response.headers.get_content_type() == 'application/json' else data

    def test_real_candidate_accept_undo_and_discard_keep_saved_versions(self):
        initial = self.request('/api/convert', {'name': 'refinement-http.png',
            'image': base64.b64encode(sample()).decode(),
            'config': {'illustration_profile': 'edge_clean', 'path_limit': 50,
                       'output_directory': str(self.folder)}})
        initial_svg = self.request('/api/svg')
        initial_files = {p.name for p in self.folder.iterdir()}
        polygon = [[16, 14], [76, 14], [76, 50], [16, 50]]
        request = {'result_id': initial['result_id'], 'polygon': polygon,
                   'options': {'path_limit': 50, 'detail': 'standard'}}
        self.request('/api/refine', {**request, 'result_id': 'old-result'}, expected=400)
        self.request('/api/refine-preview?candidate_id=missing', expected=400)
        candidate = self.request('/api/refine', request)
        candidate_svg = self.request('/api/refine-preview?candidate_id='+candidate['candidate_id'])
        self.assertIsNone(candidate['path'])
        self.assertEqual(candidate['original_result_id'], initial['result_id'])
        self.assertEqual(candidate['bytes'], len(candidate_svg))
        self.assertEqual(candidate['stats']['drawing_paths'], candidate['report']['after_paths'])
        self.assertNotEqual(candidate_svg, initial_svg)
        self.assertEqual(self.request('/api/svg'), initial_svg)
        self.assertEqual(self.server.result['result_id'], initial['result_id'])
        self.assertEqual({p.name for p in self.folder.iterdir()}, initial_files)
        preview_result = self.server.refinement.get_candidate(candidate['candidate_id'])

        # A failed new image conversion must not invalidate the current preview.
        self.request('/api/convert', {'name': 'broken.png', 'image': 'not base64', 'config': {}}, expected=400)
        self.assertEqual(self.request('/api/svg'), initial_svg)
        self.assertEqual(self.request('/api/refine-preview?candidate_id='+candidate['candidate_id']), candidate_svg)
        accepted = self.request('/api/refine-accept', {'result_id': initial['result_id'],
                                                      'candidate_id': candidate['candidate_id']})
        self.assertNotEqual(accepted['result_id'], initial['result_id'])
        self.assertNotEqual(accepted['path'], initial['path'])
        self.assertEqual(accepted['refinement_count'], 1)
        self.assertTrue(accepted['undo_available'])
        self.assertEqual(Path(accepted['path']).read_bytes(), candidate_svg)
        self.assertTrue(Path(accepted['path']).with_suffix('.pipeline.json').is_file())
        self.assertEqual(self.request('/api/svg'), candidate_svg)
        self.assertEqual(Path(initial['path']).read_bytes(), initial_svg)
        self.assertEqual(len(list(self.folder.glob('*.svg'))), 2)
        self.assertEqual(len(list(self.folder.glob('*.pipeline.json'))), 2)
        self.request('/api/refine-preview?candidate_id='+candidate['candidate_id'], expected=400)
        for result_id in (initial['result_id'], accepted['result_id']):
            self.request('/api/refine-accept', {'result_id': result_id,
                'candidate_id': candidate['candidate_id']}, expected=400)
        self.request('/api/refine-undo', {'result_id': initial['result_id']}, expected=400)
        restored = self.request('/api/refine-undo', {'result_id': accepted['result_id']})
        self.assertEqual(restored['path'], initial['path'])
        self.assertNotIn(restored['result_id'], (initial['result_id'], accepted['result_id']))
        self.assertEqual(restored['refinement_count'], 0)
        self.assertFalse(restored['undo_available'])
        self.assertEqual(self.request('/api/svg'), initial_svg)
        self.assertTrue(Path(accepted['path']).exists())

        # Reuse the real candidate bytes to test discard without rerunning tracing.
        with self.server.lock:
            discard = self.server.refinement.stage_candidate(restored['result_id'], preview_result)
        files_before_discard = {p.name for p in self.folder.iterdir()}
        self.request('/api/refine-discard', {'result_id': initial['result_id'],
            'candidate_id': discard['candidate_id']}, expected=400)
        discarded = self.request('/api/refine-discard', {'result_id': restored['result_id'],
                                                        'candidate_id': discard['candidate_id']})
        self.assertEqual(discarded['result_id'], restored['result_id'])
        self.assertEqual({p.name for p in self.folder.iterdir()}, files_before_discard)
        self.assertEqual(self.request('/api/svg'), initial_svg)
        self.request('/api/refine-preview?candidate_id='+discard['candidate_id'], expected=400)

    def test_refinement_requires_token_and_same_origin(self):
        self.request('/api/refine-preview?candidate_id=missing', token=False, expected=403)
        self.request('/api/refine-preview?candidate_id=missing', token='wrong', expected=403)
        for route in ('/api/refine', '/api/refine-accept', '/api/refine-discard', '/api/refine-undo'):
            with self.subTest(route=route):
                self.request(route, {}, token=False, expected=403)
                self.request(route, {}, origin=False, expected=403)
                self.request(route, {}, origin='https://example.com', expected=403)
        self.request('/api/refine', {}, expected=400)

    def test_cancel_keeps_current_and_previous_pending_preview(self):
        original_svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="64"><path d="M0 0H96V64H0Z" fill="red"/></svg>'
        path = self.folder/'initial.svg'
        path.write_bytes(original_svg)
        initial = {'path': str(path), 'svg': original_svg, 'original': sample(),
            'processed': None, 'processed_available': False, 'width': 96, 'height': 64,
            'config': {}, 'stats': {'drawing_paths': 1}, 'pipeline': {'stages': []}}
        with self.server.lock:
            self.server.result = self.server.refinement.set_result(initial)
            initial = self.server.result
            pending = self.server.refinement.stage_candidate(initial['result_id'],
                {'svg': original_svg.replace(b'red', b'blue'), 'refinement_report': {'after_paths': 1}})
        pending_svg = self.request('/api/refine-preview?candidate_id='+pending['candidate_id'])
        started = threading.Event()
        responses = []

        def waiting_worker(current, polygon, options, progress, control):
            started.set()
            if not control.cancelled.wait(10):
                raise RuntimeError('Cancellation test timed out')
            control.check()

        def request_refinement():
            try:
                responses.append(self.request('/api/refine', {'result_id': initial['result_id'],
                    'polygon': [[10, 10], [50, 10], [50, 40], [10, 40]], 'options': {}}))
            except BaseException as error:
                responses.append(error)

        with patch('refinement_jobs.run_refinement', side_effect=waiting_worker):
            request_thread = threading.Thread(target=request_refinement)
            request_thread.start()
            self.assertTrue(started.wait(10))
            self.assertEqual(self.request('/api/svg'), original_svg)
            self.request('/api/refine-preview?candidate_id='+pending['candidate_id'], expected=409)
            self.assertTrue(self.request('/api/cancel', {})['accepted'])
            request_thread.join(10)
            self.assertFalse(request_thread.is_alive())
        self.assertEqual(responses, [{'cancelled': True}])
        self.assertEqual(self.server.result['result_id'], initial['result_id'])
        self.assertEqual(self.request('/api/svg'), original_svg)
        self.assertEqual(self.request('/api/refine-preview?candidate_id='+pending['candidate_id']), pending_svg)
        self.assertEqual([p.name for p in self.folder.iterdir()], ['initial.svg'])
        self.assertIsNone(self.server.active_task)


if __name__ == '__main__':
    unittest.main(verbosity=2)
