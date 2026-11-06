"""Closed illustration details from multi-threshold connected components.

This is a geometric heuristic, not an eye or clothing semantic model. It uses
OpenCV contours on Lab threshold sets; no learned weights or network calls.
"""
import math


def _threshold_regions(plane, min_area, max_area):
    import cv2
    import numpy as np

    for threshold in range(int(plane.min()) + 2, int(plane.max()), 4):
        binary = (plane >= threshold).astype('uint8')
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            signed_area = cv2.contourArea(contour, oriented=True)
            area = abs(signed_area)
            if not min_area <= area <= max_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if max(w/h, h/w) > 7 or area/(w*h) < .25:
                continue
            perimeter = cv2.arcLength(contour, True)
            if 4*math.pi*area/max(1, perimeter*perimeter) < .15:
                continue
            mask = np.zeros((h, w), np.uint8)
            cv2.drawContours(mask, [contour-[x, y]], -1, 1, -1)
            # Positive winding denotes a hole (dark extremal component).
            # Intersect with its actual threshold pixels, retaining holes.
            mask &= (binary[y:y+h, x:x+w] == (signed_area < 0)).astype('uint8')
            yy, xx = np.nonzero(mask)
            if len(xx) >= min_area:
                yield np.column_stack((xx+x, yy+y)), (x, y, w, h)


def detect_structure(rgba, max_features=512, record=None):
    """Return non-semantic feature IDs at the supplied (pre-SR) resolution."""
    import cv2
    import numpy as np

    height, width = rgba.shape[:2]
    analysis_scale = min(1., math.sqrt(8_000_000/(height*width)))
    if analysis_scale < 1:
        rgba = cv2.resize(rgba, (max(1, round(width*analysis_scale)),
                                max(1, round(height*analysis_scale))), interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(rgba[:, :, :3])
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    labels = np.zeros(rgb.shape[:2], np.uint16)
    candidates = []
    min_area = max(12, 20*analysis_scale**2)
    max_area = max(min_area, 10000*analysis_scale**2)
    for channel in range(3):
        plane = cv2.GaussianBlur(lab[:, :, channel], (3, 3), .6)
        for points, (x, y, w, h) in _threshold_regions(plane, min_area, max_area):
            if x < 5 or y < 5 or x+w+5 > rgb.shape[1] or y+h+5 > rgb.shape[0]:
                continue
            area = len(points)
            mask = np.zeros((h+10, w+10), np.uint8)
            mask[points[:, 1]-y+5, points[:, 0]-x+5] = 1
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contour = max(contours, key=cv2.contourArea)
            hull = cv2.contourArea(cv2.convexHull(contour))
            solidity = cv2.contourArea(contour)/max(1, hull)
            perimeter = cv2.arcLength(contour, True)
            compact = min(1, 4*math.pi*area/max(1, perimeter*perimeter))
            if solidity < .75 or compact < .15:
                continue
            if not (rgba[points[:, 1], points[:, 0], 3] > 0).all():
                continue
            local = lab[y-5:y+h+5, x-5:x+w+5].astype(float)
            local[:, :, 0] /= 2.55
            core = cv2.erode(mask, np.ones((3, 3), np.uint8)) > 0
            ring = (cv2.dilate(mask, np.ones((7, 7), np.uint8)) -
                    cv2.dilate(mask, np.ones((3, 3), np.uint8))) > 0
            if not core.any() or not ring.any():
                continue
            inner, outer = np.median(local[core], axis=0), np.median(local[ring], axis=0)
            contrast = float(np.linalg.norm(inner-outer))
            spread = float(np.linalg.norm(np.std(local[core], axis=0)))
            if contrast < 2 or spread > max(6, contrast*.8):
                continue
            # Saturate contrast so a weak but coherent dot can compete with
            # a bright texture speck. Shape and support matter as well.
            score = min(contrast, 12)*compact**2*solidity*math.sqrt(min(area/analysis_scale**2, 1024))
            candidates.append((score, points))
        if record:
            record('potrace_structure', current=channel+1, total=3)
    count = 0
    for score, points in sorted(candidates, key=lambda item:item[0], reverse=True):
        xx, yy = points[:, 0], points[:, 1]
        if (labels[yy, xx] > 0).mean() > .15:
            continue
        count += 1
        labels[yy, xx] = count
        if count >= max_features:
            break
    if labels.shape != (height, width):
        labels = cv2.resize(labels, (width, height), interpolation=cv2.INTER_NEAREST)
    return labels
