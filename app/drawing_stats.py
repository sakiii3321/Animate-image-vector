"""Count all drawing geometry in the SVGs emitted by this application.

``svg_counts`` intentionally describes filled paths and applies SVG's implicit
fill closure. Centerlines need a separate pass: an open stroke has two distinct
endpoints and must not acquire an artificial closing line in its statistics.
Filled paths with an outline are counted once, not once for each paint.
"""
import xml.etree.ElementTree as ET

from vector_geometry import parse_d, svg_counts


def drawing_counts(file):
    """Preserve fill counts, adding stroke-only paths to geometry totals.

    Application output stores fill/stroke explicitly on each stroke-only path;
    this helper is not a CSS/style-aware statistics engine for arbitrary SVGs.
    """
    counts = svg_counts(file)
    counts['stroke_paths'] = 0
    for element in ET.parse(file).getroot().iter():
        if element.tag.rsplit('}', 1)[-1] != 'path':
            continue
        if element.get('fill') != 'none' or element.get('stroke', 'none') == 'none':
            continue
        counts['stroke_paths'] += 1
        for contour in parse_d(element.get('d', '')):
            segments = contour.segments
            if not segments:
                continue
            counts['contours'] += 1
            counts['total_segments'] += len(segments)
            counts['curve_segments'] += sum(len(segment) > 2 for segment in segments)
            counts['anchors'] += len(segments) + (0 if contour.closed else 1)
            counts['handles'] += sum(len(segment)-2 for segment in segments)
    counts['drawing_paths'] = counts['fill_paths'] + counts['stroke_paths']
    counts['nodes'] = counts['anchors'] + counts['handles']
    return counts
