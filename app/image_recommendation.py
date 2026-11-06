"""Cheap, explainable image diagnostics for vectorization presets.

This is a geometric/color heuristic, not a semantic classifier or a learned
quality score. It does not inspect filenames, choose a crop or enable SR.
All measurements run on at most 512 x 512 pixels after orientation correction.
"""
from pathlib import Path
import time

ANALYSIS_VERSION = 1
MAX_SIDE = 512


def _image_thumbnail(image_or_path):
    from PIL import Image, ImageOps
    if isinstance(image_or_path, Image.Image):
        image = ImageOps.exif_transpose(image_or_path)
        size = image.size
        # Pillow otherwise forces nearest-neighbor resizing for palette/bilevel
        # modes, giving the same artwork different diagnostics by file format.
        thumbnail = image.convert('RGBA') if image.mode in {'P', '1'} else image.copy()
        thumbnail.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        return thumbnail.convert('RGBA'), size
    with Image.open(Path(image_or_path)) as image:
        # Orientation must be resolved before width/height and layout analysis.
        return _image_thumbnail(image)


def _smooth_patch_fraction(rgb, visible, gradient):
    """Count color variation well explained by a local plane, excluding flat patches."""
    import numpy as np
    height, width = visible.shape
    block = max(6, min(8, min(height, width) // 4))
    good_pixels = 0
    valid_pixels = 0
    varying_pixels = 0
    import cv2
    interiors = cv2.erode((visible & (gradient < .025)).astype('uint8'), np.ones((3,3),np.uint8)) > 0
    yy, xx = np.mgrid[:block, :block]
    plane = np.column_stack((np.ones(block * block), xx.ravel(), yy.ravel()))
    for y in range(0, height - block + 1, block):
        for x in range(0, width - block + 1, block):
            mask = interiors[y:y + block, x:x + block].ravel()
            if mask.mean() < .5:
                continue
            values = rgb[y:y + block, x:x + block].reshape(-1, 3)[mask]
            spread = float(np.mean(np.var(values, axis=0)))
            valid_pixels += int(mask.sum())
            # A constant fill isn't evidence for gradients. Very large changes
            # are more likely a boundary than a smooth surface in a small patch.
            if not (.6 * block / 16 / 255) ** 2 <= spread <= (32 / 255) ** 2:
                continue
            varying_pixels += int(mask.sum())
            fitted = plane[mask] @ np.linalg.lstsq(plane[mask], values, rcond=None)[0]
            error = float(np.mean((values - fitted) ** 2))
            if error <= max(.20 * spread, (.35 / 255) ** 2) and error <= (3 / 255) ** 2:
                good_pixels += int(mask.sum())
    return good_pixels / max(1, valid_pixels), good_pixels / max(1, varying_pixels)


def _composition(rgb, alpha, visible, gradient, source_size):
    import numpy as np
    height, width = visible.shape
    aspect = source_size[0] / source_size[1]
    orientation = 'landscape' if aspect > 1.2 else 'portrait' if aspect < 1 / 1.2 else 'square'
    orientation_label = {'landscape':'横向','portrait':'纵向','square':'接近方形'}[orientation]
    tile = max(1, min(height, width) // 12)
    corners = [rgb[:tile,:tile], rgb[:tile,-tile:], rgb[-tile:,:tile], rgb[-tile:,-tile:]]
    corner_colors = np.asarray([np.median(c.reshape(-1, 3), axis=0) for c in corners])
    background = np.median(corner_colors, axis=0)
    uniform_background = float(np.max(np.linalg.norm(corner_colors - background, axis=1))) < .12
    if float(np.mean(alpha < .98)) > .05:
        weights = alpha.copy()
        basis = '透明度范围'
    elif uniform_background:
        weights = np.clip((np.linalg.norm(rgb - background, axis=2) - .06) / .12, 0, 1)
        basis = '与边角背景的色差'
    else:
        weights = np.minimum(1, gradient / .04) * visible
        basis = '边缘分布（背景不均匀）'
    total = float(weights.sum())
    if total < max(2, height * width * .0001):
        layout, centroid, fraction, central = 'uniform', None, 0., 0.
    else:
        yy, xx = np.mgrid[:height, :width]
        cx = float(np.sum(weights * (xx + .5)) / total / width)
        cy = float(np.sum(weights * (yy + .5)) / total / height)
        centroid = [round(cx, 3), round(cy, 3)]
        fraction = float(np.mean(weights > .15))
        central = float(weights[height//4:height-height//4, width//4:width-width//4].sum() / total)
        occupied = sum(float(p.mean()) > .06 for row in np.array_split(weights, 3, axis=0)
                       for p in np.array_split(row, 3, axis=1) if p.size)
        if max(abs(cx-.5), abs(cy-.5)) > .16:
            layout = 'offset'
        elif central > .65 and fraction < .65:
            layout = 'concentrated'
        elif occupied >= 7:
            layout = 'distributed'
        else:
            layout = 'mixed'
    labels = {'uniform':'未见明显主体分布','offset':'有效内容偏向一侧',
              'concentrated':'有效内容较集中','distributed':'有效内容分布较广','mixed':'有效内容分布适中'}
    return {'orientation':orientation, 'orientation_label':orientation_label,
            'aspect_ratio':round(aspect, 3), 'layout':layout, 'layout_label':labels[layout],
            'basis':basis, 'foreground_fraction':round(fraction, 4),
            'center_fraction':round(central, 4), 'centroid':centroid,
            'note':'仅描述颜色、边缘或透明度的空间分布，不代表人物或物体识别；不会自动裁剪。'}


def analyze_image(image_or_path):
    """Analyze a PIL image or local path and return JSON-serializable suggestions.

    The caller decides whether to apply a suggestion. Values are measured on
    the thumbnail and are not confidence percentages or guarantees of quality.
    """
    started = time.perf_counter()
    import cv2
    import numpy as np
    image, source_size = _image_thumbnail(image_or_path)
    rgba = np.asarray(image, dtype=np.float32) / 255.
    alpha = rgba[:, :, 3]
    visible = alpha > .05
    # A white matte prevents hidden RGB in transparent pixels from influencing
    # recommendations; resizing RGBA in Pillow also avoids colored edge halos.
    rgb = rgba[:, :, :3] * alpha[:, :, None] + 1 - alpha[:, :, None]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3, scale=.125)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3, scale=.125)
    grad = np.hypot(gx, gy)
    valid = int(visible.sum())
    def avg(values): return float(np.mean(values[visible])) if valid else 0.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturated_fraction = avg(hsv[:, :, 1] > .15)
    pale_fraction = avg(gray > .90)
    # Use one-pixel nonmaximum-suppressed edges for complexity. Gradient-band
    # coverage otherwise marks thick or soft outlines as spuriously complex.
    edge_density = avg(cv2.Canny(np.round(gray*255).astype('uint8'),40,120)>0)
    edge_band_fraction = avg(grad > .045)
    spread = float(np.mean(np.std(rgb[visible], axis=0))) if valid else 0.
    xx = cv2.GaussianBlur(gx*gx, (0,0), 1.2)
    yy = cv2.GaussianBlur(gy*gy, (0,0), 1.2)
    xy = cv2.GaussianBlur(gx*gy, (0,0), 1.2)
    coherence = np.sqrt((xx-yy)**2+4*xy**2)/(xx+yy+1e-9)
    detail = np.abs(gray-cv2.GaussianBlur(gray, (0,0), .8))
    texture_density = avg((grad>.02)&(coherence<.45)&(detail>.012))
    high_frequency = avg(detail)
    edge_pixels = visible & (grad>.025)
    edge_strength = float(np.percentile(grad[edge_pixels], 75)) if edge_pixels.any() else 0.
    # Quantized color entropy measures palette diversity without a full image
    # clustering pass. Dark/bright edge-only variation is identified separately.
    bins = np.minimum(7, (rgb*8).astype(np.int16))
    colors = bins[:,:,0]*64+bins[:,:,1]*8+bins[:,:,2]
    counts = np.bincount(colors[visible], minlength=512) if valid else np.zeros(512)
    probabilities = counts[counts>0]/max(1, valid)
    entropy = float(-np.sum(probabilities*np.log2(probabilities)))
    smooth_fraction, smooth_of_varying = _smooth_patch_fraction(rgb, visible, grad) if min(gray.shape)>=6 and valid else (0.,0.)
    composition = _composition(rgb, alpha, visible, grad, source_size)

    if not valid:
        kind, label = 'empty', '全透明图'
    elif spread < .003 and edge_density < .001:
        kind, label = 'solid', '近乎纯色'
    elif saturated_fraction < .12 and pale_fraction > .65 and .005 < edge_density < .12:
        kind, label = 'line_art', '线稿倾向'
    elif texture_density > .065 or (texture_density > .035 and edge_density > .06):
        kind, label = 'textured', '纹理或高频细节较多'
    elif smooth_fraction >= .12 and smooth_of_varying >= .3 and texture_density < .035:
        kind, label = 'smooth_shading', '平滑渐变较多'
    elif entropy < 3.5 and texture_density < .025 and smooth_fraction < .12:
        kind, label = 'flat_color', '平涂或有限配色倾向'
    else:
        kind, label = 'mixed_illustration', '混合上色插画倾向'

    if kind in {'empty','solid'}:
        complexity = 'low'
    elif edge_density > .10 or texture_density > .035 or entropy > 6.:
        complexity = 'high'
    elif edge_density > .025 or entropy > 3.5 or smooth_fraction > .2:
        complexity = 'medium'
    else:
        complexity = 'low'
    if valid == 0 or spread < .003 or edge_density < .001:
        clarity, clarity_label = 'undetermined', '缺少可判断清晰度的边缘'
    elif max(source_size) < 700:
        clarity, clarity_label = 'limited_resolution', '输入像素较少'
    elif edge_strength < .055:
        clarity, clarity_label = 'soft_edges', '缩略图上的边缘偏柔和'
    else:
        clarity, clarity_label = 'defined_edges', '缩略图上可辨识明显边缘'

    profile = 'edge_clean'
    reasons = ['边缘整理在本轮多风格盲评中表现较稳，优先作为通用方案。']
    if kind == 'smooth_shading' and complexity != 'high' and saturated_fraction > .15:
        profile = 'gradient_layers'
        reasons = ['检测到较多连续色彩变化、纹理负担较低，可尝试渐变色面方案。',
                   '渐变方案在盲评中的主要收益来自色彩过渡，仍需检查局部细节。']
    elif kind == 'line_art':
        reasons.append('画面低饱和、浅底和线结构较多，优先保留线稿，避免强行重建大色面。')
    elif kind == 'textured' or complexity == 'high':
        reasons.append('纹理或复杂边界较多，保守使用边缘整理，避免分层简化抹掉真实细节。')
    elif kind == 'flat_color':
        reasons.append('配色和色面较简单，额外渐变拟合通常没有必要。')
    elif kind in {'empty','solid'}:
        reasons = ['图片几乎没有可重建的颜色结构，使用简单色面即可。']
    if clarity == 'limited_resolution':
        reasons.append('较低像素数会限制可恢复细节；不自动开启超分辨率，也不把插值视为真实细节。')
    elif clarity == 'soft_edges':
        reasons.append('柔和边缘可能来自模糊、抗锯齿或画风，不能仅据此断定原图不清晰。')
    budget = 1200 if complexity == 'low' else 3000 if complexity == 'high' else 2000
    features = {'edge_density':edge_density,'edge_band_fraction':edge_band_fraction,'texture_density':texture_density,
                'color_entropy_bits':entropy,'smooth_shading_fraction':smooth_fraction,
                'smooth_fraction_of_varying_interiors':smooth_of_varying,
                'saturated_fraction':saturated_fraction,'pale_fraction':pale_fraction,
                'high_frequency_mean':high_frequency,'edge_strength_p75':edge_strength,
                'visible_fraction':float(visible.mean())}
    return {'version':ANALYSIS_VERSION,'source_size':list(source_size),'analysis_size':list(image.size),
            'type':kind,'type_label':label,
            'clarity':{'level':clarity,'label':clarity_label,
                       'note':'这是缩略图边缘和输入尺寸的相对信号，不是原图清晰度评分。'},
            'complexity':{'level':complexity,'label':{'low':'较低','medium':'中等','high':'较高'}[complexity]},
            'composition':composition,'features':{k:round(v,5) for k,v in features.items()},
            'recommended_profile':profile,'reasons':reasons,
            'suggested_params':{'path_limit':budget},
            'limitations':['推荐基于像素统计，不能可靠识别人物、眼睛或服饰图案。',
                           '构图分析不会自动裁剪，也不会只优化指定局部。',
                           '路径数量是可选起点；复杂图增加预算也会增加耗时，并不保证更好。'],
            'elapsed_ms':round((time.perf_counter()-started)*1000,2)}
