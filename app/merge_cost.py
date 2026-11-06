"""Perceptual color costs with a tempered area weight and stable descriptors."""
import math


class MergeCosts:
    def __init__(self, mass, sums, areas, focus_ids=(), min_area=0, scale=1, feature_ids=None,
                 area_exponent=None):
        self.spatial_area = scale * scale
        self.features = list(map(int, feature_ids)) if feature_ids is not None else None
        # A per-conversion policy; the legacy merge cost is unchanged by default.
        self.area_exponent = area_exponent
        if area_exponent is not None and (not math.isfinite(area_exponent) or not 0 <= area_exponent <= 1):
            raise ValueError('Region merge area exponent must be between 0 and 1.')
        self.descriptors = [self.descriptor(m, row, area) for m, row, area in zip(mass, sums, areas)]
        self.threshold = min_area * scale * scale
        self.focus = set(focus_ids)
        self.small = [area < self.threshold * (.5 if i in self.focus else 1) for i, area in enumerate(areas)]

    def descriptor(self, mass, sums, area):
        if not mass:
            return (0., 0., 0., 0.), 0., 1.
        # Quarter-unit Lab precision is used only for merge ordering.
        # Exported RGBA means still use the exact accumulated pixel sums.
        factors = (2.55, 1., 1., 2.55)
        mean = tuple(round(float(v) / mass / factor * 4) / 4 for v, factor in zip(sums, factors))
        # Logarithmic area buckets make a stable background's priorities
        # reusable while preserving a cost for distorting large color fields.
        spatial_mass = float(mass) / self.spatial_area
        size = 2. ** math.floor(math.log2(spatial_mass))
        return mean, size, round(float(mass) / area, 2)

    def update(self, a, b, mass, sums, area):
        feature_changed = False
        if self.features is not None and self.features[a] != self.features[b]:
            feature_changed = self.features[a] != 0
            # If a very tight budget forces a protected boundary to merge,
            # do not let its feature ID spread over the entire background.
            self.features[a] = 0
        previous = self.descriptors[a], self.small[a]
        self.descriptors[a] = self.descriptor(mass, sums, area)
        if b in self.focus:
            self.focus.add(a)
        self.small[a] = area < self.threshold * (.5 if a in self.focus else 1)
        return feature_changed or previous != (self.descriptors[a], self.small[a])

    def feature_id(self, region):
        return self.features[region] if self.features is not None else 0

    def color_difference_squared(self, a, b):
        aa, bb = self.descriptors[a][0], self.descriptors[b][0]
        d0 = aa[0] - bb[0]
        d1 = aa[1] - bb[1]
        d2 = aa[2] - bb[2]
        d3 = aa[3] - bb[3]
        return d0*d0 + d1*d1 + d2*d2 + d3*d3

    def cost(self, a, b):
        # Ward's linear area term cheaply erases small contrasting details.
        # Its square root reduces that bias without letting all similar
        # large color fields collapse into one flat background.
        focus_weight = max(self.descriptors[a][2], self.descriptors[b][2])
        difference = self.color_difference_squared(a, b)
        ma, mb = self.descriptors[a][1], self.descriptors[b][1]
        area = ma * mb / (ma + mb)
        exponent = self.area_exponent
        if self.features is not None:
            # Explicit shape constraints free the color objective to retain
            # more shading. Lexicographic priority avoids a magic penalty.
            return (int(self.features[a] != self.features[b]),
                    area ** (.75 if exponent is None else exponent) * math.sqrt(focus_weight) * difference)
        if exponent is not None:
            return area ** exponent * math.sqrt(focus_weight) * difference
        return math.sqrt(area * focus_weight) * difference

    def clean_small(self, a, b):
        # Area alone never makes a high-contrast dot/line a cleanup candidate.
        return (self.feature_id(a) == self.feature_id(b) and
                (self.small[a] or self.small[b]) and self.color_difference_squared(a, b) <= 6 ** 2)
