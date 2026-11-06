"""Removed-engine rejection and migration of saved Potrace configurations."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from core import DEFAULTS, LEGACY_DEFAULTS, SCHEMA, convert, runtime_info, self_test, validate

RETIRED_FIELDS={'colormode','hierarchical','mode','filter_speckle','color_precision',
    'layer_difference','corner_threshold','length_threshold','max_iterations',
    'splice_threshold','path_precision'}


class PotraceOnlyCompatibilityTests(unittest.TestCase):
    def test_schema_defaults_and_runtime_exclude_retired_engine(self):
        self.assertEqual(SCHEMA['engine']['choices'],['potrace'])
        for config in (DEFAULTS,LEGACY_DEFAULTS):
            self.assertEqual(config['engine'],'potrace')
            self.assertFalse(RETIRED_FIELDS & config.keys())
        self.assertFalse(RETIRED_FIELDS & SCHEMA.keys())
        self.assertNotIn('vtracer',runtime_info()['packages'])

    def test_explicit_retired_engine_is_rejected_even_with_potrace_profile(self):
        for extra in ({},{'illustration_profile':'edge_clean'},
                      {'illustration_profile':'legacy','path_limit':300}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                validate({'engine':'vtracer',**extra})

    def test_unidentified_retired_configs_are_not_silently_converted(self):
        for key in RETIRED_FIELDS:
            for extra in ({},{'path_limit':300}):
                with self.subTest(key=key,extra=extra),self.assertRaises(ValueError):
                    validate({key:None,**extra})

    def test_explicit_potrace_discards_retired_fields_and_keeps_settings(self):
        config={key:None for key in RETIRED_FIELDS}
        config.update(engine='potrace',path_limit=321,potrace_palette_colors=18,
                      crop_ratio='3:4',potrace_turn_policy='white')
        original=copy.deepcopy(config)
        actual=validate(config)
        self.assertEqual(config,original)
        self.assertEqual(actual,validate({k:v for k,v in config.items() if k not in RETIRED_FIELDS}))
        self.assertEqual(actual['illustration_profile'],'legacy')
        self.assertEqual(actual['path_limit'],321)
        self.assertEqual(actual['potrace_palette_colors'],18)
        self.assertFalse(RETIRED_FIELDS & actual.keys())

    def test_explicit_profile_discards_old_fields_without_resetting_overrides(self):
        config={key:None for key in RETIRED_FIELDS}
        config.update(illustration_profile='gradient_layers',path_limit=400,
                      potrace_palette_colors=80,curve_tolerance=.5)
        original=copy.deepcopy(config)
        actual=validate(config)
        self.assertEqual(config,original)
        self.assertEqual(actual,validate({k:v for k,v in config.items() if k not in RETIRED_FIELDS}))
        self.assertEqual(actual['engine'],'potrace')
        self.assertEqual(actual['potrace_palette_colors'],80)
        self.assertFalse(RETIRED_FIELDS & actual.keys())

    def test_unrelated_unknown_settings_remain_errors(self):
        for config in ({'engine':'potrace','mode':'polygon','unknown_setting':1},
                       {'illustration_profile':'edge_clean','unknown_setting':1}):
            with self.subTest(config=config),self.assertRaises(ValueError):
                validate(config)

    def test_retired_requests_fail_before_worker_launch(self):
        for config in ({'engine':'vtracer'},{'color_precision':8}):
            with self.subTest(config=config),patch('core.subprocess.run') as worker:
                with self.assertRaises(ValueError):
                    convert(b'not decoded for an unsupported configuration','input.png',config)
                worker.assert_not_called()

    def test_selftest_exercises_each_supported_profile_once(self):
        with patch('core.convert',return_value={'svg':b'<svg/>','stats':{'paths':1,'drawing_paths':1}}) as conversion:
            result=self_test()
        self.assertTrue(result['ok'],result)
        self.assertEqual(len(result['checks']),4)
        configs=[validate(call.args[2]) for call in conversion.call_args_list]
        self.assertEqual(len(configs),4)
        self.assertEqual({cfg['illustration_profile'] for cfg in configs},
                         {'legacy','edge_clean','flat_layers','gradient_layers'})
        self.assertTrue(all(cfg['engine']=='potrace' for cfg in configs))


if __name__=='__main__':unittest.main(verbosity=2)
