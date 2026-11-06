"""Regression parity for the geometry-only performance changes.

The frozen reference is also used by the serial performance benchmark. These
checks protect sampled-fit decisions, paint/closure semantics and statistics.
"""
from pathlib import Path
import sys,tempfile,unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'experiments')]
import vector_geometry as current
import performance_geometry_baseline as reference


class GeometryPerformanceParity(unittest.TestCase):
    def test_levels_keep_identical_control_points(self):
        rng=np.random.default_rng(17)
        for closed in (False,True):
            points=np.column_stack((np.cos(np.linspace(0,2*np.pi,33)),np.sin(np.linspace(0,2*np.pi,33))))*40
            pieces=[]
            for a,b in zip(points[:-1],points[1:]):
                delta=b-a
                pieces.append(np.array([a,a+delta/3+rng.normal(0,.1,2),a+2*delta/3+rng.normal(0,.1,2),b]))
            levels=[0,.1,.3,1.,2.]
            expected=reference.simplify_contour_levels(reference.Contour(pieces,closed),levels)
            actual=current.simplify_contour_levels(current.Contour(pieces,closed),levels)
            for old,new in zip(expected,actual):
                self.assertEqual(len(old),len(new))
                for p,q in zip(old,new):np.testing.assert_array_equal(p,q)

    def test_serialized_outputs_reports_and_progress_match(self):
        svg='''<svg xmlns="http://www.w3.org/2000/svg" width="140" height="100">
<g opacity=".5"><path fill="#123456" fill-rule="evenodd" d="M0 0 l20 0 20 0 20 0 h40 v80 H0 z M20 20v20h20v-20z"/></g>
<path fill="#765432" stroke="#765432" d="M10 10Q20 10 30 15T50 20C60 20 70 25 80 35S100 50 110 70L10 10"/>
<path fill="none" stroke="red" d="M0 50C20 30 40 70 60 50"/>
<path fill="blue" stroke="blue" stroke-linecap="round" d="M0 10L10 10L20 10L30 10"/>
<path fill="red" d="M0 0L0 0Z"/></svg>'''
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'input.svg';source.write_text(svg,encoding='utf-8')
            for tolerance in (0,.1,.3,2.):
                old,new=folder/'old.svg',folder/'new.svg';old_events=[];new_events=[]
                old_report=reference.simplify_svg(source,old,tolerance,lambda *a,**k:old_events.append((a,k)))
                new_report=current.simplify_svg(source,new,tolerance,lambda *a,**k:new_events.append((a,k)))
                self.assertEqual(old.read_bytes(),new.read_bytes())
                self.assertEqual(old_report,new_report);self.assertEqual(old_events,new_events)
                self.assertEqual(current.svg_counts(new),new_report['after'])

    def test_normalization_keeps_serialized_geometry_opacity_and_statistics(self):
        svg='''<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 3 80 60">
<g opacity=".7" transform="translate(7,8) scale(2)"><path fill="red" stroke="red" stroke-width=".5" d="M0 0C10 0 20 0 30 0Q40 20 30 30L0 0Z M5 5H15V15H5Z"/></g>
<path fill="none" stroke="black" d="M0 0Q20 30 40 50"/></svg>'''
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'input.svg';source.write_text(svg,encoding='utf-8')
            old,new=folder/'old.svg',folder/'new.svg'
            old_report=reference.normalize_svg(source,old,160,120)
            new_report=current.normalize_svg(source,new,160,120)
            self.assertEqual(old_report,new_report);self.assertEqual(old.read_bytes(),new.read_bytes())

    def test_gradient_counts_and_unnamespaced_input_stay_compatible(self):
        docs=['''<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs><path fill="url(#g)" d="M0 0H20V20H0Z"/><path fill="none" stroke="blue" d="M0 10H20"/></svg>''',
              '''<svg><image href="sample.png"/><path fill="red" d="M0 0H20V20H0Z"/><path fill="none" d="M0 10H20"/></svg>''']
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for svg in docs:
                source=folder/'input.svg';source.write_text(svg,encoding='utf-8')
                self.assertEqual(current.svg_counts(source),reference.svg_counts(source))
                old,new=folder/'old.svg',folder/'new.svg'
                self.assertEqual(current.simplify_svg(source,new),reference.simplify_svg(source,old))
                self.assertEqual(old.read_bytes(),new.read_bytes())

if __name__=='__main__':unittest.main(verbosity=2)
