"""Real isolated refinement plus failure-safe candidate saving."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from PIL import Image, ImageDraw
from core import validate
from refinement_jobs import run_refinement, save_refinement
from task_control import TaskControl, ConversionCancelled


class RefinementJobsTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder=Path(self.directory.name)
        im=Image.new('RGB',(120,80),'#e8cbbc')
        draw=ImageDraw.Draw(im)
        draw.ellipse((53,29,64,38),fill='#faf4eb')
        draw.line((51,49,68,49),fill='#b57b72',width=2)
        stream=io.BytesIO();im.save(stream,'PNG')
        svg=b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80" viewBox="0 0 120 80"><path d="M0 0H120V80H0Z" fill="#e8cbbc"/></svg>'
        path=self.folder/'base.svg';path.write_bytes(svg)
        self.current={'path':str(path),'svg':svg,'original':stream.getvalue(),
            'processed':None,'processed_available':False,'width':120,'height':80,
            'config':validate({'engine':'potrace','path_limit':1,'output_directory':str(self.folder)}),
            'stats':{'engine':'potrace','paths':1,'drawing_paths':1},'pipeline':None}
        self.polygon=[[40,20],[78,20],[80,58],[39,60]]

    def test_real_worker_returns_unsaved_candidate_and_cleans_job_files(self):
        factory=tempfile.TemporaryDirectory;created=[]
        def local_job(**kwargs):
            manager=factory(dir=self.folder,**kwargs);created.append(Path(manager.name));return manager
        before=self.current['svg']
        with patch('refinement_jobs.tempfile.TemporaryDirectory',side_effect=local_job):
            candidate=run_refinement(self.current,self.polygon,{'path_limit':50,'detail':'fine'},control=TaskControl())
        self.assertEqual(list(self.folder.iterdir()),[Path(self.current['path'])])
        self.assertTrue(all(not p.exists() for p in created))
        self.assertEqual(Path(self.current['path']).read_bytes(),before)
        self.assertNotEqual(candidate['svg'],before)
        report=candidate['refinement_report']
        self.assertLessEqual(report['added_paths'],50)
        self.assertEqual(candidate['stats']['drawing_paths'],report['after_paths'])
        self.assertEqual(candidate['pipeline']['stages'][-1]['stage'],'local_refine')
        self.assertEqual(candidate['refinement_count'],1)

    def test_invalid_selection_worker_error_and_cancel_preserve_saved_result(self):
        with self.assertRaisesRegex(ValueError,'圈选'):
            run_refinement(self.current,[[1,1]],{},control=TaskControl())
        cancelled=TaskControl();cancelled.cancel()
        with self.assertRaises(ConversionCancelled):
            run_refinement(self.current,self.polygon,{},control=cancelled)
        self.assertEqual(list(self.folder.iterdir()),[Path(self.current['path'])])
        self.assertEqual(Path(self.current['path']).read_bytes(),self.current['svg'])

    def test_sidecar_failure_removes_only_new_files(self):
        candidate={**self.current,'svg':self.current['svg']+b'\n','pipeline':{'stages':[]}}
        with patch('refinement_jobs.json.dump',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):save_refinement(candidate)
        self.assertEqual(list(self.folder.iterdir()),[Path(self.current['path'])])
        self.assertEqual(Path(self.current['path']).read_bytes(),self.current['svg'])

    def test_saved_versions_are_independent_and_have_report(self):
        candidate={**self.current,'svg':self.current['svg']+b'\n','pipeline':{'stages':[{'stage':'local_refine'}]}}
        first=save_refinement(candidate);second=save_refinement(candidate)
        self.assertNotEqual(first['path'],second['path'])
        for result in (first,second):
            self.assertEqual(Path(result['path']).read_bytes(),candidate['svg'])
            self.assertEqual(json.loads(Path(result['path']).with_suffix('.pipeline.json').read_text(encoding='utf-8')),candidate['pipeline'])
        self.assertEqual(Path(self.current['path']).read_bytes(),self.current['svg'])


if __name__=='__main__':unittest.main(verbosity=2)
