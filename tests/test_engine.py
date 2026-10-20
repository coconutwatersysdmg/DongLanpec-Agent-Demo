import copy
import unittest

from engine import DesignEngine, EXAMPLE_TEXT, example_parameters, example_components


class EngineTests(unittest.TestCase):
    def filled(self):
        engine = DesignEngine()
        engine.call('set_parameters', {'parameters': example_parameters()}, EXAMPLE_TEXT)
        return engine

    def test_component_requires_layout_and_failure_is_atomic(self):
        engine = self.filled()
        before = engine.snapshot()
        result = engine.call('place_components', {'components': example_components()}, EXAMPLE_TEXT)
        self.assertFalse(result['ok'])
        self.assertIn('先布管', result['message'])
        self.assertEqual(engine.snapshot(), before)

    def test_complete_design_fills_real_layout_and_all_three_component_kinds(self):
        engine = self.filled()
        result = engine.call('layout_tubes', {}, EXAMPLE_TEXT)
        self.assertTrue(result['ok'], result)
        original = len(engine.state['tubes'])
        result = engine.call('place_components', {'components': example_components()}, EXAMPLE_TEXT)
        self.assertTrue(result['ok'], result)
        kinds = [c['kind'] for c in engine.state['components']]
        self.assertEqual(kinds.count('拉杆'), 8)
        self.assertEqual(kinds.count('旁路挡板'), 2)
        self.assertEqual(kinds.count('防冲板'), 1)
        self.assertLess(len(engine.state['tubes']), original)
        self.assertTrue(engine.call('inspect_design', {}, EXAMPLE_TEXT)['ok'])

    def test_relayout_clears_components_and_parameter_change_invalidates_layout(self):
        engine = self.filled()
        engine.call('layout_tubes', {}, EXAMPLE_TEXT)
        engine.call('place_components', {'components': example_components()}, EXAMPLE_TEXT)
        engine.call('layout_tubes', {}, EXAMPLE_TEXT)
        self.assertEqual(engine.state['components'], [])
        result = engine.call('set_parameters', {'parameters': [{
            'name':'换热管中心距 S','value':34,'unit':'mm','evidence':'中心距34毫米'}]}, '中心距34毫米')
        self.assertTrue(result['ok'])
        self.assertFalse(engine.state['laid_out'])

    def test_unknown_tools_missing_parameters_and_bad_evidence_are_rejected(self):
        engine = DesignEngine()
        for name, args in [('run_python', {}), ('layout_tubes', {}), ('set_parameters', {
                'parameters':[{'name':'公称直径 DN','value':1300,'unit':'mm','evidence':'假依据'}]})]:
            before = engine.snapshot()
            self.assertFalse(engine.call(name, args, '测试')['ok'])
            self.assertEqual(engine.snapshot(), before)

    def test_bad_plate_request_does_not_leave_partial_components(self):
        engine = self.filled()
        engine.call('layout_tubes', {}, EXAMPLE_TEXT)
        before = engine.snapshot()
        requests = example_components()
        requests[0]['width'] = 9000
        result = engine.call('place_components', {'components':requests}, EXAMPLE_TEXT)
        self.assertFalse(result['ok'])
        self.assertEqual(engine.snapshot(), before)

    def test_restore_snapshot_restores_all_state(self):
        engine = self.filled()
        before = engine.snapshot()
        engine.call('layout_tubes', {}, EXAMPLE_TEXT)
        engine.call('place_components', {'components':example_components()}, EXAMPLE_TEXT)
        engine.restore(before)
        self.assertEqual(engine.snapshot(), before)

    def test_u_tube_two_pass_positions_remain_paired_after_components(self):
        engine=self.filled();engine.call('layout_tubes',{},EXAMPLE_TEXT)
        result=engine.call('place_components',{'components':example_components()},EXAMPLE_TEXT)
        self.assertTrue(result['ok'],result)
        keys={(round(x,6),round(y,6)) for x,y in engine.state['tubes']}
        self.assertTrue(all((x,-y) in keys for x,y in keys))
        rods={(round(c['center'][0],6),round(c['center'][1],6))
              for c in engine.state['components'] if c['kind']=='拉杆'}
        self.assertTrue(all((x,-y) in rods for x,y in rods))


if __name__ == '__main__':
    unittest.main()
