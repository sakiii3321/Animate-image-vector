"""Version tokens, failure atomicity and image-buffer sharing for local refinement."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from refinement_session import RefinementSession


def result(path='original.svg', svg=b'<svg id="original"/>'):
    return {'path': path, 'svg': svg, 'original': b'original image bytes',
            'processed': b'processed image bytes', 'processed_available': True,
            'width': 100, 'height': 80, 'config': {'path_limit': 2000},
            'stats': {'drawing_paths': 100}, 'pipeline': {'stages': [{'stage': 'vectorize'}]}}


class RefinementSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = RefinementSession()
        self.original = result()
        self.base = self.session.set_result(self.original)

    def stage(self, svg=b'<svg id="candidate"/>', **extra):
        return self.session.stage_candidate(self.session.current['result_id'],
            {'svg': svg, 'stats': {'drawing_paths': 2100},
             'refinement_report': {'after_paths': 2100}, **extra})

    def accept(self, name):
        candidate = self.stage(('<svg id="'+name+'"/>').encode())
        return self.session.accept(candidate['result_id'], candidate['candidate_id'],
                                   lambda proposed: {**proposed, 'path': name+'.svg'})

    def test_candidate_is_memory_only_and_preserves_image_references(self):
        candidate = self.stage()
        preview = self.session.get_candidate(candidate['candidate_id'])
        self.assertIsNone(candidate['path'])
        self.assertEqual(preview['path'], self.base['path'])
        self.assertEqual(candidate['original_result_id'], self.base['result_id'])
        self.assertEqual(candidate['result_id'], self.base['result_id'])
        self.assertEqual(candidate['report']['after_paths'], 2100)
        self.assertEqual(self.session.current, self.base)
        for key in ('original', 'processed'):
            self.assertIs(preview[key], self.original[key])
            self.assertIs(self.session.current[key], self.original[key])
        self.assertFalse(self.session.metadata()['undo_available'])

    def test_accept_saves_new_svg_and_report_before_changing_current(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = result(str(folder/'original.svg'))
            Path(source['path']).write_bytes(source['svg'])
            base = self.session.set_result(source)
            candidate = self.stage()
            self.assertEqual([p.name for p in folder.iterdir()], ['original.svg'])

            def save(proposed):
                self.assertEqual(self.session.current, base)
                target = folder/'refined.svg'
                target.write_bytes(proposed['svg'])
                target.with_suffix('.pipeline.json').write_text(json.dumps(proposed['pipeline']))
                return {**proposed, 'path': str(target)}

            accepted = self.session.accept(base['result_id'], candidate['candidate_id'], save)
            self.assertEqual(Path(accepted['path']).read_bytes(), accepted['svg'])
            self.assertTrue(Path(accepted['path']).with_suffix('.pipeline.json').is_file())
            self.assertEqual(accepted['refinement_count'], 1)
            self.assertEqual(accepted['stats']['drawing_paths'], 2100)
            self.assertNotEqual(accepted['result_id'], base['result_id'])
            restored = self.session.undo(accepted['result_id'])
            self.assertEqual(restored['path'], base['path'])
            self.assertEqual(restored['refinement_count'], 0)
            self.assertTrue(Path(accepted['path']).exists())
            self.assertTrue(Path(accepted['path']).with_suffix('.pipeline.json').exists())

    def test_save_failure_preserves_current_candidate_and_history(self):
        accepted = self.accept('first')
        candidate = self.stage()
        before = self.session.metadata()

        def failed_save(proposed):
            proposed['config']['path_limit'] = 1
            proposed['pipeline']['stages'].clear()
            proposed['stats']['drawing_paths'] = 0
            raise OSError('report write failed')

        with self.assertRaisesRegex(OSError, 'report write failed'):
            self.session.accept(accepted['result_id'], candidate['candidate_id'], failed_save)
        self.assertEqual(self.session.current, accepted)
        self.assertEqual(self.session.metadata(), before)
        preview = self.session.get_candidate(candidate['candidate_id'])
        self.assertEqual(preview['stats']['drawing_paths'], 2100)
        self.assertEqual(preview['config']['path_limit'], 2000)
        self.assertTrue(preview['pipeline']['stages'])
        restored = self.session.undo(accepted['result_id'])
        self.assertEqual(restored['svg'], self.base['svg'])

    def test_invalid_save_result_does_not_commit(self):
        for saved in (None, {'path': ''}, {'path': self.base['path']}):
            with self.subTest(saved=saved):
                candidate = self.stage()
                with self.assertRaises(ValueError):
                    self.session.accept(self.base['result_id'], candidate['candidate_id'], lambda value: saved)
                self.assertEqual(self.session.current, self.base)
                self.assertEqual(self.session.get_candidate(candidate['candidate_id'])['svg'], b'<svg id="candidate"/>')

    def test_duplicate_accept_and_old_result_ids_are_rejected(self):
        candidate = self.stage()
        accepted = self.session.accept(self.base['result_id'], candidate['candidate_id'],
                                       lambda value: {'path': 'next.svg'})
        saver = Mock()
        for token in (self.base['result_id'], accepted['result_id']):
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.session.accept(token, candidate['candidate_id'], saver)
        saver.assert_not_called()
        with self.assertRaises(ValueError):
            self.session.stage_candidate(self.base['result_id'], {'svg': b'<svg/>'})
        with self.assertRaises(ValueError):
            self.session.undo(self.base['result_id'])
        restored = self.session.undo(accepted['result_id'])
        self.assertNotIn(restored['result_id'], (self.base['result_id'], accepted['result_id']))
        with self.assertRaises(ValueError):
            self.session.stage_candidate(self.base['result_id'], {'svg': b'<svg/>'})

    def test_invalid_token_types_and_unicode_raise_chinese_errors(self):
        candidate = self.stage()
        for supplied in (None, 1, [], '过期结果'):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(ValueError, '当前结果'):
                    self.session.discard(supplied, candidate['candidate_id'])
                with self.assertRaisesRegex(ValueError, '精修候选'):
                    self.session.get_candidate(supplied)
        self.session.get_candidate(candidate['candidate_id'])

    def test_replacing_discarding_and_undo_release_pending_candidate(self):
        first = self.stage()
        second_svg = ('<svg>'+('x'*10000)+'</svg>').encode()
        reference_count = sys.getrefcount(second_svg)
        second = self.stage(second_svg)
        with self.assertRaises(ValueError):
            self.session.get_candidate(first['candidate_id'])
        self.assertGreater(sys.getrefcount(second_svg), reference_count)
        with self.assertRaises(ValueError):
            self.session.discard(self.base['result_id'], first['candidate_id'])
        self.session.discard(self.base['result_id'], second['candidate_id'])
        self.assertEqual(sys.getrefcount(second_svg), reference_count)
        with self.assertRaises(ValueError):
            self.session.get_candidate(second['candidate_id'])
        accepted = self.accept('accepted')
        pending = self.stage()
        self.session.undo(accepted['result_id'])
        with self.assertRaises(ValueError):
            self.session.get_candidate(pending['candidate_id'])

    def test_failed_or_cancelled_work_keeps_existing_candidate(self):
        candidate = self.stage()
        for invalid in ({}, {'svg': bytearray(b'<svg/>')}, {'svg': b''}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.session.stage_candidate(self.base['result_id'], invalid)
        # Starting/cancelling an external worker performs no session mutation.
        self.assertEqual(self.session.get_candidate(candidate['candidate_id'])['original_result_id'], self.base['result_id'])
        self.assertEqual(self.session.current, self.base)

    def test_full_conversion_reset_is_success_only(self):
        accepted = self.accept('accepted')
        pending = self.stage()
        with self.assertRaises(ValueError):
            self.session.set_result({'svg': b''})
        self.assertEqual(self.session.current, accepted)
        self.session.get_candidate(pending['candidate_id'])
        replacement = self.session.set_result(result('new-image.svg', b'<svg id="new"/>'))
        self.assertFalse(self.session.metadata()['undo_available'])
        self.assertEqual(replacement['refinement_count'], 0)
        with self.assertRaises(ValueError):
            self.session.get_candidate(pending['candidate_id'])
        with self.assertRaises(ValueError):
            self.session.stage_candidate(accepted['result_id'], {'svg': b'<svg/>'})

    def test_three_step_history_and_refinement_counts(self):
        versions = [self.base]
        for number in range(1, 7):
            current = self.accept('version-'+str(number))
            self.assertEqual(current['refinement_count'], number)
            for key in ('original', 'processed'):
                self.assertIs(current[key], self.original[key])
            versions.append(current)
        for number in (5, 4, 3):
            current = self.session.undo(self.session.current['result_id'])
            self.assertEqual(current['path'], versions[number]['path'])
            self.assertEqual(current['refinement_count'], number)
        self.assertFalse(self.session.metadata()['undo_available'])
        with self.assertRaises(ValueError):
            self.session.undo(current['result_id'])
        next_result = self.accept('after-undo')
        self.assertEqual(next_result['refinement_count'], 4)
        self.assertEqual(self.session.undo(next_result['result_id'])['path'], versions[3]['path'])

    def test_metadata_is_json_safe_and_snapshots_are_isolated(self):
        current = result()
        current['config']['hidden'] = b'never publish source bytes'
        current['pipeline']['nested'] = [b'never publish raster', {'safe': 1, 'raw': b'no'}]
        base = self.session.set_result(current)
        metadata = self.session.metadata()
        encoded = json.dumps(metadata, allow_nan=False)
        self.assertNotIn('never publish', encoded)
        self.assertEqual(metadata['bytes'], len(base['svg']))
        self.assertNotIn('original', metadata)
        self.assertNotIn('processed', metadata)
        self.assertNotIn('svg', metadata)
        metadata['stats']['drawing_paths'] = 0
        base['pipeline']['stages'].clear()
        self.assertEqual(self.session.current['stats']['drawing_paths'], 100)
        self.assertTrue(self.session.current['pipeline']['stages'])
        pending = self.stage(refinement_report={'after_paths': 2100, 'mask': b'no'})
        self.assertEqual(pending['report'], {'after_paths': 2100})
        json.dumps(pending, allow_nan=False)

    def test_empty_session_and_invalid_history_limit(self):
        empty = RefinementSession()
        self.assertIsNone(empty.current)
        self.assertIsNone(empty.metadata()['result_id'])
        self.assertFalse(empty.metadata()['undo_available'])
        for supplied in ('stale', None, 1):
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                empty.undo(supplied)
        for limit in (0, 4, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                RefinementSession(limit)


if __name__ == '__main__':
    unittest.main(verbosity=2)
