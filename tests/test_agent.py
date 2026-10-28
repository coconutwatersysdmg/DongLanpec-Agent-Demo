import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from agent import AgentRunner, ScriptedProvider, BailianProvider
from engine import DesignEngine, EXAMPLE_TEXT
from ai_support.api_client import APIConfig


class AgentTests(unittest.TestCase):
    def test_agent_executes_tools_and_observations_return_to_model(self):
        engine=DesignEngine(); provider=ScriptedProvider(); events=[]
        result=AgentRunner(provider).run(EXAMPLE_TEXT,engine,events.append)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(engine.state['laid_out'])
        self.assertEqual(len(engine.state['components']),11)
        self.assertEqual([e['tool'] for e in events if e['type']=='tool_result'],
                         ['read_design','set_parameters','layout_tubes','place_components','inspect_design'])
        self.assertTrue(any(m['role']=='tool' for m in provider.seen[-1]))

    def test_malformed_or_unknown_call_cannot_execute_code(self):
        class BadProvider:
            def complete(self,messages,tools):
                return {'content':'', 'tool_calls':[{'id':'bad','type':'function','function':{
                    'name':'exec','arguments':'{"code":"raise Exception()"}'}}]}
        engine=DesignEngine()
        result=AgentRunner(BadProvider(),max_rounds=2).run('测试',engine)
        self.assertNotEqual(result['status'],'completed')
        self.assertFalse(engine.state['laid_out'])
        self.assertEqual(engine.state['parameters'],{})

    def test_false_success_text_does_not_mark_design_complete(self):
        class TextProvider:
            def complete(self,messages,tools):return {'content':'全部设计完成，校核合格！'}
        result=AgentRunner(TextProvider()).run('帮我布管',DesignEngine())
        self.assertNotEqual(result['status'],'completed')
        self.assertIn('尚未布管',result['summary'])
        self.assertNotIn('全部设计完成',result['reply'])
        self.assertNotIn('校核合格',result['reply'])

    def test_plain_claim_of_placed_rods_is_replaced_with_actual_facts(self):
        class TextProvider:
            def complete(self,messages,tools):return {'content':'8根拉杆已布置。'}
        result=AgentRunner(TextProvider()).run('帮我布管并放8根拉杆',DesignEngine())
        self.assertNotIn('拉杆已布置',result['reply'])
        self.assertIn('当前0',result['reply'])

    def test_omitted_requested_component_cannot_be_reported_complete(self):
        class SkipComponents(ScriptedProvider):
            def complete(self,messages,tools):
                if self.index==3:self.index+=1
                return super().complete(messages,tools)
        engine=DesignEngine()
        result=AgentRunner(SkipComponents()).run(EXAMPLE_TEXT,engine)
        self.assertNotEqual(result['status'],'completed')
        self.assertIn('拉杆',result['summary'])

    def test_increment_request_cannot_be_satisfied_by_existing_rods(self):
        engine=DesignEngine();AgentRunner(ScriptedProvider()).run(EXAMPLE_TEXT,engine)
        class OnlyInspect:
            first=True
            def complete(self,messages,tools):
                if not self.first:return {'content':'8根拉杆已增加。'}
                self.first=False
                return {'tool_calls':[{'id':'check','type':'function','function':{
                    'name':'inspect_design','arguments':'{}'}}]}
        result=AgentRunner(OnlyInspect()).run('再增加8根拉杆，直径16毫米',engine)
        self.assertNotEqual(result['status'],'completed')
        self.assertIn('16',result['summary'])

    def test_actual_increment_is_applied_and_verified(self):
        engine=DesignEngine();AgentRunner(ScriptedProvider()).run(EXAMPLE_TEXT,engine)
        instruction='再增加8根拉杆，直径16毫米，外围对称'
        class AddAndInspect:
            first=True
            def complete(self,messages,tools):
                if not self.first:return {'content':'完成'}
                self.first=False
                args={'components':[dict(kind='拉杆',quantity=8,region='外围对称',diameter=16,evidence=instruction)]}
                return {'tool_calls':[{'id':str(i),'type':'function','function':{'name':name,
                    'arguments':json.dumps(data,ensure_ascii=False)}} for i,(name,data) in enumerate([
                        ('place_components',args),('inspect_design',{})])]}
        result=AgentRunner(AddAndInspect()).run(instruction,engine)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(sum(c['kind']=='拉杆' for c in engine.state['components']),16)

    def test_cancellation_stops_before_tools(self):
        engine=DesignEngine()
        result=AgentRunner(ScriptedProvider()).run(EXAMPLE_TEXT,engine,cancelled=lambda:True)
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(engine.state['parameters'],{})


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider=BailianProvider(APIConfig('https://dashscope.aliyuncs.com/compatible-mode/v1',
                                              'dummy-test-key','qwen-plus'))

    def test_http_function_call_and_tool_observation_complete_a_real_protocol_loop(self):
        payloads=[]
        class Response:
            def __init__(self,msg):self.msg=msg
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,size):return json.dumps({'choices':[{'message':self.msg,'finish_reason':'stop'}]}).encode()
        def send(req,timeout):
            payloads.append(json.loads(req.data))
            return Response({'content':'请补充参数'} if len(payloads)>1 else {'tool_calls':[
                {'id':'state-1','type':'function','function':{'name':'read_design','arguments':'{}'}}]})
        with patch('urllib.request.urlopen',side_effect=send):
            AgentRunner(self.provider).run('先看看设计',DesignEngine())
        self.assertEqual(len(payloads),2)
        self.assertIn('tools',payloads[0])
        self.assertNotIn('response_format',payloads[0])
        observation=payloads[1]['messages'][-1]
        self.assertEqual(observation['role'],'tool')
        self.assertEqual(observation['tool_call_id'],'state-1')

    def test_http_failure_never_discloses_secret_or_server_body(self):
        with patch('urllib.request.urlopen',side_effect=HTTPError('https://x',401,'dummy-test-key',{},None)):
            with self.assertRaisesRegex(RuntimeError,'401') as caught:
                self.provider.complete([],[])
        self.assertNotIn('dummy-test-key',str(caught.exception))


if __name__=='__main__':unittest.main()
