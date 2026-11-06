"""Versioned, explicit presets; importing an older config keeps its old route."""
PROFILE_LABELS = {
    'edge_clean': '边缘清理 · 通用',
    'gradient_layers': '渐变分层 · 柔和上色',
    'flat_layers': '平涂分层 · 实验',
    'legacy': '传统 Potrace · 兼容旧配置',
}

_BASE = dict(engine='potrace', path_limit=2000, curve_simplify=True,
             curve_tolerance=.3, simplify_target_paths=0,
             potrace_palette_colors=100, potrace_smoothing=0.,
             potrace_min_region_area=8, potrace_stroke_width=1.,
             potrace_turn_policy='black', potrace_turd_size=0,
             potrace_preserve_structure=False, potrace_alpha_max=1.,
             potrace_opt_curve=True, potrace_opt_tolerance=.4,
             diffvg_optimize=False, highres_refine=False)
PROFILE_PRESETS = {
    key: {**_BASE, 'illustration_profile':key,
          'potrace_palette_colors':100 if key == 'edge_clean' else 64}
    for key in ('edge_clean', 'gradient_layers', 'flat_layers')
}
PROFILE_PRESETS['legacy'] = {
    **_BASE, 'illustration_profile':'legacy', 'path_limit':2500,
    'curve_simplify':False, 'potrace_palette_colors':48,
    'potrace_min_region_area':16, 'potrace_turn_policy':'minority', 'potrace_smoothing':1.,
}

def is_illustration(config):
    return config['engine'] == 'potrace' and config.get('illustration_profile', 'legacy') != 'legacy'

def resize_illustration_canvas(source, destination, width, height):
    """Retain viewBox, gradients and strokes in processed-image coordinates."""
    import xml.etree.ElementTree as ET
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    root = ET.parse(source).getroot()
    if not root.get('viewBox'):
        raise ValueError('插画引擎输出缺少 viewBox。')
    root.set('width', str(width))
    root.set('height', str(height))
    ET.ElementTree(root).write(destination, encoding='utf-8', xml_declaration=True)
