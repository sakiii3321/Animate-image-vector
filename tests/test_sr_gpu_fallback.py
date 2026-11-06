"""Real SR with CUDA fault injection; run in the configured enhancement Python."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'runtime/enhancement'
sys.path[:0] = [str(ROOT/'app'), str(RUNTIME/'sr'), str(RUNTIME/'diffvg'), str(RUNTIME/'pydeps')]
from PIL import Image, ImageDraw
import enhance_sr


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Run with the enhancement Python for real SR tests')
class GPUFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        cls.torch = torch
        cls.has_cuda = torch.cuda.is_available()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        # Crosses the 256 px tile boundary, with nontrivial colors and alpha.
        self.source = Image.new('RGBA', (270, 20), (24, 70, 140, 40))
        draw = ImageDraw.Draw(self.source)
        draw.rectangle((245, 2, 269, 17), fill=(210, 110, 45, 180))
        draw.ellipse((10, 2, 30, 18), fill=(80, 170, 200, 255))
        self.source.save(self.work/'input.png')
        self.events = []

    def run_sr(self, name='output', scale=2):
        report = enhance_sr.run({'input':str(self.work/'input.png'), 'output':str(self.work/f'{name}.png'),
                                 'config':{'sr_scale':scale}},
                                lambda stage, **kw:self.events.append((stage, kw)))
        with Image.open(self.work/f'{name}.png') as im:
            output = im.copy()
        self.assertEqual(output.size, (270*scale, 20*scale))
        self.assertEqual(output.mode, 'RGBA')
        self.assertEqual(output.getchannel('A').tobytes(),
                         self.source.getchannel('A').resize(output.size, Image.Resampling.LANCZOS).tobytes())
        self.assertEqual(report['tiles'], 2)
        return report, output

    def test_default_uses_real_cuda(self):
        if not self.has_cuda:self.skipTest('No real CUDA device')
        report, _ = self.run_sr()
        self.assertEqual(report['backend'], 'cuda')
        self.assertEqual(report['attempted_devices'], ['cuda'])
        self.assertEqual(report['precision'], 'torch.float16')
        self.assertEqual(report['fallback_reason'], '')
        self.assertTrue(all(d['device']=='cuda' for s,d in self.events if s=='sr_inference'))

    def test_no_cuda_runs_real_cpu_2x_and_4x(self):
        with patch.object(self.torch.cuda, 'is_available', return_value=False):
            for scale in (2,4):
                report, _ = self.run_sr(str(scale), scale)
                self.assertEqual(report['backend'], 'cpu')
                self.assertEqual(report['precision'], 'torch.float32')
                self.assertEqual(report['attempted_devices'], ['cpu'])
                self.assertTrue(report['fallback_reason'])

    def test_cuda_probe_error_keeps_sr_available_and_cpu_works(self):
        from enhance_worker import probe
        with patch.object(self.torch.cuda, 'is_available', return_value=True), \
             patch.object(self.torch.cuda, 'get_device_name', side_effect=RuntimeError('CUDA driver initialization failed')):
            caps = probe()
            self.assertTrue(caps['sr']['available'], caps)
            self.assertEqual(caps['sr']['backend'], 'cpu')
            self.assertIn('initialization failed', caps['sr']['fallback_reason'])
            report, _ = self.run_sr()
            self.assertEqual(report['backend'], 'cpu')

    def test_cuda_model_transfer_failure_retries_cpu(self):
        original_to = self.torch.nn.Module.to
        def fail_cuda(module, *args, **kwargs):
            if kwargs.get('device') == 'cuda':
                raise RuntimeError('CUDA: no kernel image is available for execution on the device')
            return original_to(module, *args, **kwargs)
        with patch.object(enhance_sr, 'preferred_device', return_value={'backend':'cuda','device':'test GPU','fallback_reason':''}), \
             patch.object(self.torch.nn.Module, 'to', fail_cuda):
            report, _ = self.run_sr()
        self.assertEqual(report['attempted_devices'], ['cuda','cpu'])
        self.assertEqual(report['backend'], 'cpu')
        self.assertTrue(any(s=='sr_cpu_fallback' for s,d in self.events))

    def test_mid_image_cuda_oom_restarts_exact_cpu_output(self):
        if not self.has_cuda:self.skipTest('No real CUDA device')
        from srvgg_arch import SRVGGNetCompact
        original_forward = SRVGGNetCompact.forward
        calls = {'cuda':0,'cpu':0}
        def fail_second_tile(module, x):
            backend = x.device.type;calls[backend] += 1
            if backend == 'cuda' and calls[backend] == 2:
                raise self.torch.cuda.OutOfMemoryError('Injected CUDA out of memory on second tile')
            return original_forward(module, x)
        with patch.object(SRVGGNetCompact, 'forward', fail_second_tile):
            report, retried = self.run_sr('retried')
        self.assertEqual(calls, {'cuda':2,'cpu':2})
        self.assertEqual(report['attempted_devices'], ['cuda','cpu'])
        self.assertIn('out of memory', report['fallback_reason'])
        progress = [(d['device'],d['current']) for s,d in self.events if s=='sr_inference']
        self.assertIn(('cuda',1),progress);self.assertIn(('cpu',0),progress);self.assertIn(('cpu',2),progress)
        with patch.object(self.torch.cuda, 'is_available', return_value=False):
            _, baseline = self.run_sr('cpu_baseline')
        # Catches mixing partial GPU tiles, or reusing FP16-rounded model weights.
        self.assertEqual(retried.tobytes(),baseline.tobytes())

    def test_corrupt_weights_do_not_trigger_cpu_retry(self):
        with patch.object(self.torch, 'load', return_value={'params':{}}), \
             patch.object(enhance_sr, '_infer') as infer:
            with self.assertRaises(RuntimeError):self.run_sr()
            infer.assert_not_called()
        self.assertFalse((self.work/'output.png').exists())

    def test_cpu_failure_is_reported_without_retry(self):
        with patch.object(self.torch.cuda, 'is_available', return_value=False), \
             patch.object(enhance_sr, '_infer', side_effect=RuntimeError('CPU inference failed')) as infer:
            with self.assertRaisesRegex(RuntimeError,'CPU inference failed'):self.run_sr()
            self.assertEqual(infer.call_count,1)
        self.assertFalse((self.work/'output.png').exists())

    def test_save_error_does_not_trigger_device_retry(self):
        with patch.object(self.torch.cuda, 'is_available', return_value=False), \
             patch.object(Image.Image, 'save', side_effect=PermissionError('output denied')), \
             patch.object(enhance_sr, '_infer', wraps=enhance_sr._infer) as infer:
            with self.assertRaisesRegex(PermissionError,'output denied'):self.run_sr()
            self.assertEqual(infer.call_count,1)


if __name__=='__main__':unittest.main(verbosity=2)
