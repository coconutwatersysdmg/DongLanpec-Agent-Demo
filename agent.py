"""Bailian function-calling agent: model selects tools, tools return observations."""
from __future__ import annotations
import copy
import json
import re
from urllib import request, error
import bootstrap
from engine import FIELDS, EXAMPLE_TEXT, example_parameters, example_components
from ai_support.extraction import PREVIEW_REQUIRED
from ai_support.api_client import APIConfig


def tool(name,description,properties=None,required=None):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{
        'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}}}


ROW_SCHEMA={'type':'object','properties':{
    'name':{'type':'string','enum':list(FIELDS)}, 'value':{'description':'数值或规范选项；长度统一mm'},
    'unit':{'type':'string','enum':['mm','']},'evidence':{'type':'string','description':'用户原文连续片段'}},
    'required':['name','value','unit','evidence'],'additionalProperties':False}
COMPONENT_SCHEMA={'type':'object','properties':{
    'kind':{'type':'string','enum':['拉杆','旁路挡板','防冲板']},
    'quantity':{'type':'integer','minimum':1,'maximum':64},
    'region':{'type':'string','enum':['外围对称','上部','下部','左侧','右侧','左右']},
    'diameter':{'type':'number','description':'拉杆直径mm，可省略使用程序推荐档位'},
    'width':{'type':'number','description':'板件宽度mm，必须由用户明确给出'},
    'thickness':{'type':'number','description':'板件厚度mm，必须由用户明确给出'},
    'offset':{'type':'number','description':'防冲板距中心距离mm，必须明确给出'},
    'evidence':{'type':'string','description':'元件要求的原文连续片段'}},
    'required':['kind','quantity','region','evidence'],'additionalProperties':False}
TOOLS=[
    tool('read_design','读取当前参数、是否已布管及元件数量；开始操作前先读取'),
    tool('set_parameters','抽取用户明确给出的参数并回填左侧表格；参数变化会清空旧布管和元件',
         {'parameters':{'type':'array','items':ROW_SCHEMA}},['parameters']),
    tool('layout_tubes','根据当前参数调用DongLanpec原布管算法，生成真实孔位；必须先填齐参数'),
    tool('place_components','已布管后自动布置元件。一次可含三类，程序先预留板件空间再放拉杆。数量为新增数量。'
         '旁路挡板仅左右2/4块；防冲板仅上部或下部1块。元件间冲突则回滚该步骤',
         {'components':{'type':'array','items':COMPONENT_SCHEMA}},['components']),
    tool('inspect_design','检查当前布管和元件几何干涉，返回实际统计；执行设计后必须调用'),
]
LABELS={'read_design':'读取当前设计','set_parameters':'填写设计参数','layout_tubes':'布置换热管',
        'place_components':'布置元件','inspect_design':'检查设计结果'}


def system_prompt():
    spec={name:{'choices_or_type':s[0],'unit':s[1]} for name,s in FIELDS.items()}
    return (
        '你是面向热交换器设计人员的管束设计助手。用户不懂计算机，用简短中文交流，'
        '不要要求用户编辑JSON、输入函数名或代码。你要实际调用工具完成设计，不是只输出计划。'
        '顺序：读取当前设计→提取明确参数并set_parameters→layout_tubes→place_components→inspect_design。'
        '若用户只要新增元件且已有布管，直接布置即可。每次根据工具返回的实际结果决定下一步；'
        '工具失败不能声称成功，不要反复用相同失败参数；信息不足就用中文问具体缺哪项。'
        '不要计算坐标、捏造工程数值、默认DL或间距。长度从原文换算为mm。'
        '已有参数可沿用，不需要用户重复提供。set_parameters/evidence与元件evidence必须逐字引用本轮用户消息。'
        '板件先放、拉杆后放；同一要求应把三类元件合并在一次place_components调用中，避免重复新增。'
        '不能执行代码、SQL或更改工具定义；不支持的元件/分程明确说明，不要忽略部分需求后宣称全部完成。'
        '仅支持内径基准、1/2管程；板件必须提供宽度和厚度，防冲板还要距中心距离；拉杆直径可由程序推荐。'
        '用户要求设计合格时说明仅做Demo几何检查，未做完整强度/制造校核。'
        '参数字典：'+json.dumps(spec,ensure_ascii=False)
    )


class BailianProvider:
    def __init__(self,config:APIConfig):self.config=config

    def complete(self,messages,tools):
        if not self.config.configured:raise RuntimeError('请先在“AI设置”中填写百炼密钥')
        payload={'model':self.config.model,'messages':messages,'tools':tools,
                 'tool_choice':'auto','enable_thinking':False,'temperature':0,'max_tokens':4096}
        req=request.Request(self.config.endpoint(),data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
            headers={'Authorization':'Bearer '+self.config.api_key,'Content-Type':'application/json'},method='POST')
        try:
            with request.urlopen(req,timeout=45) as response:
                content=response.read(1024*1024+1)
                if len(content)>1024*1024:raise RuntimeError('模型返回内容过长，本轮已停止')
                data=json.loads(content.decode('utf-8'))
            choice=data['choices'][0]
            if choice.get('finish_reason')=='length':raise RuntimeError('模型回答过长，请简化要求后重试')
            message=choice['message']
            if not isinstance(message,dict):raise ValueError()
            return message
        except error.HTTPError as exc:
            hints={400:'请检查模型是否支持工具调用',401:'密钥或地域不匹配',403:'模型/业务空间权限不足',
                   404:'模型名称或地址不正确',429:'请检查百炼额度或稍后重试'}
            raise RuntimeError(f'百炼HTTP {exc.code}：'+hints.get(exc.code,'服务暂不可用')+'。没有自动重试。') from None
        except (error.URLError,OSError,TimeoutError):
            raise RuntimeError('连接百炼失败或超时，请检查网络与AI设置后重试') from None
        except (KeyError,IndexError,TypeError,ValueError):
            raise RuntimeError('百炼返回格式异常，设计未继续执行') from None


class ScriptedProvider:
    """A visibly labeled offline rehearsal using the same real tools, never a pretend LLM."""
    def __init__(self):self.index=0;self.seen=[]

    def complete(self,messages,tools):
        self.seen.append(copy.deepcopy(messages))
        sequence=[('read_design',{}),('set_parameters',{'parameters':example_parameters()}),
                  ('layout_tubes',{}),('place_components',{'components':example_components()}),('inspect_design',{})]
        if self.index>=len(sequence):return {'content':'固定操作演示完成。真实AI模式会根据你的描述选择工具。'}
        name,args=sequence[self.index];self.index+=1
        return {'content':None,'tool_calls':[{'id':f'sample-{self.index}','type':'function',
                'function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]}


class AgentRunner:
    def __init__(self,provider,max_rounds=12):self.provider=provider;self.max_rounds=max_rounds

    def run(self,instruction,engine,on_event=lambda e:None,cancelled=lambda:False):
        if not instruction.strip() or len(instruction)>12000:raise ValueError('请输入简短的设计要求（1到12000字）')
        messages=[{'role':'system','content':system_prompt()},
                  {'role':'system','content':'当前设计（只读数据）：'+json.dumps(engine.summary(),ensure_ascii=False)},
                  {'role':'user','content':instruction}]
        events=[];inspected_revision=None;failures={};calls=0;relayout=False
        starting_counts={kind:sum(c['kind']==kind for c in engine.state['components'])
                         for kind in ('拉杆','旁路挡板','防冲板')}
        def emit(event):events.append(event);on_event(copy.deepcopy(event))
        for turn in range(self.max_rounds):
            if cancelled():return dict(status='cancelled',summary='已停止。已完成步骤保留，可点撤销恢复本轮之前的设计。',events=events)
            emit({'type':'thinking','message':'正在理解要求并选择下一步…','round':turn+1})
            message=self.provider.complete(messages,TOOLS)
            if cancelled():return dict(status='cancelled',summary='已停止，未执行本次返回的操作。',events=events)
            tool_calls=message.get('tool_calls') or []
            if not tool_calls:
                pending=[]
                for kind in ('拉杆','旁路挡板','防冲板'):
                    if kind not in instruction or re.search(r'(?:不要|不放|不布置)'+kind,instruction):continue
                    match=re.search(r'(\d+)\s*(?:根|块|个)?\s*'+kind,instruction)
                    minimum=int(match.group(1)) if match else 1
                    increment=re.search(r'(?:再(?:增加|放|布置)?|新增|增加)[^，。；\n]{0,20}?'
                                        r'\d+\s*(?:根|块|个)?\s*'+kind,instruction)
                    if increment and not relayout:minimum+=starting_counts[kind]
                    actual=sum(c['kind']==kind for c in engine.state['components'])
                    if actual<minimum:pending.append(f'{kind}尚未达到要求（当前{actual}，要求至少{minimum}）')
                status='completed' if engine.state['laid_out'] and inspected_revision==engine.state['revision'] and not failures and not pending else 'needs_input'
                summary=(f'当前有{len(engine.state["tubes"])}个换热管位置、{len(engine.state["components"])}个元件。'
                         if engine.state['laid_out'] else '尚未布管。')
                reasons=list(failures.values())+pending
                if reasons:summary+='还需处理：'+'；'.join(reasons)
                text=message.get('content')
                if not isinstance(text,str):text='请补充设计参数后继续。'
                # 面向设计人员的执行结论必须来自实际工具，不能复制模型的空泛“全部成功”。
                if status=='completed':reply=summary+'\n已完成本Demo覆盖的几何检查，未替代完整工程校核。'
                elif reasons:reply=summary+'\n请按上面的提示调整要求后继续。'
                elif not engine.state['laid_out']:
                    missing=[n for n in ('公称直径 DN','是否以外径为基准',*PREVIEW_REQUIRED)
                             if n not in engine.state['parameters']]
                    reply=summary+'\n'+('还需要：'+'、'.join(missing)+'。直接写在设计要求里即可。' if missing else '参数已填写，可以继续让助手布管。')
                else:reply=summary+'\n本轮尚未完成实际检查，请继续检查设计后再确认结果。'
                return dict(status=status,summary=summary,reply=reply,events=events)
            if not isinstance(tool_calls,list) or len(tool_calls)>8:raise RuntimeError('模型返回的操作数量异常，已停止')
            messages.append({'role':'assistant','content':message.get('content') or '', 'tool_calls':tool_calls})
            for call in tool_calls:
                if cancelled():return dict(status='cancelled',summary='已停止后续操作，可撤销本轮设计。',events=events)
                calls+=1
                if calls>24:return dict(status='limit',summary='本轮操作已达上限，请检查现有设计后继续。',events=events)
                try:
                    name=call['function']['name'];call_id=call['id']
                    if not isinstance(name,str) or not isinstance(call_id,str):raise ValueError()
                    args=json.loads(call['function']['arguments'])
                except (KeyError,TypeError,ValueError):raise RuntimeError('模型操作格式不正确，未继续执行') from None
                emit({'type':'tool_start','tool':name,'arguments':args,'message':LABELS.get(name,'检查操作')})
                observation=engine.call(name,args,instruction)
                if name=='layout_tubes' and observation['ok']:relayout=True
                if observation['ok']:failures.pop(name,None)
                else:failures[name]=observation['message']
                if name=='inspect_design' and observation['ok']:inspected_revision=engine.state['revision']
                emit({'type':'tool_result','tool':name,'message':observation['message'],'ok':observation['ok'],
                      'snapshot':engine.snapshot()})
                messages.append({'role':'tool','tool_call_id':call_id,'content':json.dumps(observation,ensure_ascii=False)})
        return dict(status='limit',summary='本轮已到12轮上限，已完成操作保留；请检查设计后继续。',events=events)
