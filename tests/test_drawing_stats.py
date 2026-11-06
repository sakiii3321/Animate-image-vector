"""Geometry totals include open reconstruction lines without closing them."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from drawing_stats import drawing_counts


class DrawingStatsTests(unittest.TestCase):
    def counts(self, elements):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            svg = Path(directory)/'drawing.svg'
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg">'+elements+'</svg>',encoding='utf-8')
            return drawing_counts(svg)

    def test_fill_and_open_closed_strokes_have_correct_geometry_totals(self):
        result = self.counts('''
            <path fill="red" stroke="black" d="M0 0H10V10H0Z"/>
            <path fill="none" stroke="black" d="M0 20C3 20 7 25 10 25L20 25"/>
            <path fill="none" stroke="blue" d="M0 30L10 30L5 40Z"/>
        ''')
        self.assertEqual(result, dict(fill_paths=1,stroke_paths=2,drawing_paths=3,
            contours=3,total_segments=9,curve_segments=1,anchors=10,handles=2,
            nodes=12,embedded_images=0))

    def test_open_fill_is_implicitly_closed_but_open_stroke_is_not(self):
        result = self.counts('''
            <path fill="red" d="M0 0L10 0L5 10"/>
            <path fill="none" stroke="black" d="M20 0L30 0L25 10"/>
        ''')
        self.assertEqual(result['total_segments'],5)
        self.assertEqual(result['anchors'],6)
        self.assertEqual(result['contours'],2)

    def test_open_subpaths_get_separate_endpoints_and_unpainted_path_is_ignored(self):
        result = self.counts('''
            <path fill="none" stroke="black" d="M0 0L10 0 M20 0Q25 8 30 0"/>
            <path fill="none" stroke="none" d="M0 0L10 0"/>
        ''')
        self.assertEqual(result['drawing_paths'],1)
        self.assertEqual(result['stroke_paths'],1)
        self.assertEqual(result['contours'],2)
        self.assertEqual(result['total_segments'],2)
        self.assertEqual(result['anchors'],4)
        self.assertEqual(result['handles'],1)
        self.assertEqual(result['nodes'],5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
