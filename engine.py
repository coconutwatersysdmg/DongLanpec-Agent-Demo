"""Database-free engineering tools. Mutations are atomic and follow layout dependencies."""
from __future__ import annotations
import copy
import math
import bootstrap
from modules.buguan.buguan_ziyong.ai_assistant.extraction import (
    FIELDS, SAMPLE_TEXT, SAMPLE_RESPONSE, validate_extraction, preview_layout,
)

EXAMPLE_TEXT = SAMPLE_TEXT + (
    '先布管，再左右布置2块旁路挡板，宽40毫米、厚3毫米；'
    '上部距中心500毫米布置1块防冲板，宽300毫米、厚6毫米；'
    '最后外围对称布置8根拉杆，直径16毫米。'
)


def example_parameters():
    return copy.deepcopy(SAMPLE_RESPONSE['parameters'])


def example_components():
    return [
        dict(kind='防冲板', quantity=1, region='上部', width=300, thickness=6,
             offset=500, evidence='上部距中心500毫米布置1块防冲板，宽300毫米、厚6毫米'),
        dict(kind='旁路挡板', quantity=2, region='左右', width=40, thickness=3,
             evidence='左右布置2块旁路挡板，宽40毫米、厚3毫米'),
        dict(kind='拉杆', quantity=8, region='外围对称', diameter=16,
             evidence='外围对称布置8根拉杆，直径16毫米'),
    ]


def number(value, label, maximum=10000):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f'{label}必须为大于0且不超过{maximum}的数值')
    return float(value)


def rect_circle(rect, point, radius):
    x, y, w, h = rect
    dx = point[0] - max(x, min(point[0], x + w))
    dy = point[1] - max(y, min(point[1], y + h))
    return dx*dx + dy*dy < radius*radius - 1e-6


def overlap(a, b):
    if a['kind'] == '拉杆' and b['kind'] == '拉杆':
        return math.dist(a['center'], b['center']) < (a['diameter']+b['diameter'])/2-1e-6
    if a['kind'] == '拉杆':
        return rect_circle(b['rect'], a['center'], a['diameter']/2)
    if b['kind'] == '拉杆':
        return rect_circle(a['rect'], b['center'], b['diameter']/2)
    x,y,w,h = a['rect']; xx,yy,ww,hh = b['rect']
    return x < xx+ww-1e-6 and xx < x+w-1e-6 and y < yy+hh-1e-6 and yy < y+h-1e-6


class DesignEngine:
    def __init__(self):
        self.state = dict(parameters={}, evidence=[], tubes=[], initial_holes=[], components=[],
                          laid_out=False, revision=0)

    def snapshot(self):
        return copy.deepcopy(self.state)

    def restore(self, state):
        self.state = copy.deepcopy(state)

    def summary(self):
        components = self.state['components']
        return dict(parameters=self.state['parameters'], laid_out=self.state['laid_out'],
                    heat_tube_holes=len(self.state['tubes']),
                    initial_holes=len(self.state['initial_holes']),
                    components=[{k:v for k,v in c.items() if k not in ('rect','center')} for c in components],
                    supported='内径基准、1/2管程；拉杆、左右2/4块旁路挡板、上/下1块平板防冲板')

    def call(self, name, args, source=''):
        before = self.snapshot()
        try:
            if not isinstance(args, dict):
                raise ValueError('工具参数格式不正确')
            if name == 'read_design':
                if args: raise ValueError('读取设计不需要参数')
                message = '已读取当前参数和布管状态'
            elif name == 'set_parameters':
                if set(args) != {'parameters'}: raise ValueError('填参工具只接受parameters')
                message = self.set_parameters(args['parameters'], source)
            elif name == 'layout_tubes':
                if args: raise ValueError('布管使用当前参数，不接受坐标')
                message = self.layout()
            elif name == 'place_components':
                if set(args) != {'components'}: raise ValueError('元件工具只接受components')
                message = self.place(args['components'], source)
            elif name == 'inspect_design':
                if args: raise ValueError('检查设计不需要参数')
                message = self.inspect()
            else:
                raise ValueError('这个操作尚未开放，请使用填参、布管或三类元件布置工具')
            return dict(ok=True, message=message, design=self.summary())
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            self.restore(before)
            return dict(ok=False, message=str(exc), design=self.summary())
        except Exception:
            self.restore(before)
            return dict(ok=False, message='工程工具执行失败，已恢复该步骤之前的设计', design=self.summary())

    def set_parameters(self, rows, source):
        parsed = validate_extraction({'parameters':rows, 'unresolved':[]}, source)
        if not rows: raise ValueError('没有识别出需要填写的参数，请补充设计要求')
        merged = dict(self.state['parameters'], **parsed['parameters'])
        self.check_parameters(merged)
        if merged != self.state['parameters']:
            self.state.update(parameters=merged, laid_out=False, tubes=[], initial_holes=[], components=[])
            records = {r['name']:r for r in self.state['evidence']}
            records.update({r['name']:r for r in rows})
            self.state['evidence'] = list(records.values())
            self.state['revision'] += 1
        return f'已填写{len(rows)}项参数；参数有变化时，原布管和元件已清除，需要重新布管'

    @staticmethod
    def check_parameters(params):
        if params.get('是否以外径为基准') not in (None, '否'):
            raise ValueError('此Demo先支持内径基准；外径基准需接入原工程直径计算接口')
        if params.get('管程程数') not in (None, 1, 2):
            raise ValueError('此Demo先支持1/2管程，更多管程需要指定具体分程型式')
        d, s, dl = (params.get(k) for k in ('换热管外径 do','换热管中心距 S','布管限定圆 DL'))
        if d is not None and s is not None and s < d: raise ValueError('中心距小于管外径，请增大中心距')
        if dl is not None and '公称直径 DN' in params and dl > params['公称直径 DN']:
            raise ValueError('布管限定圆大于壳体内径，请检查DL与DN')
        if d is not None and dl is not None and dl <= d: raise ValueError('布管限定圆必须大于管外径')
        t = params.get('换热管壁厚 δ')
        if d is not None and t is not None and 2*t >= d: raise ValueError('壁厚的两倍必须小于管外径')
        gap = params.get('分程隔板两侧相邻管中心距（竖直）')
        if gap is not None and d is not None and gap < d: raise ValueError('分程间距小于管外径，管孔会重叠')

    def layout(self):
        p = self.state['parameters']
        missing = [n for n in ('公称直径 DN','是否以外径为基准') if n not in p]
        if missing: raise ValueError('请先补充：'+'、'.join(missing))
        self.check_parameters(p)
        raw = {'parameters':p,'issues':[], 'unresolved':[]}
        packed = preview_layout(raw)
        if not packed['centers']: raise ValueError('当前参数没有生成管孔，请调整尺寸与间距')
        self.state.update(tubes=list(packed['centers']), initial_holes=list(packed['centers']),
                          components=[], laid_out=True, revision=self.state['revision']+1)
        return f'已按原工程算法布管，共{len(packed["centers"])}个管孔；旧元件已清除'

    def place(self, requests, source):
        if not self.state['laid_out']: raise ValueError('请先布管，再布置元件')
        if not isinstance(requests, list) or not 1 <= len(requests) <= 12:
            raise ValueError('请给出1到12项元件布置要求')
        rank = {'防冲板':0,'旁路挡板':1,'拉杆':2}
        for req in requests:
            if not isinstance(req, dict) or req.get('kind') not in rank: raise ValueError('目前支持拉杆、旁路挡板、防冲板')
            evidence = req.get('evidence')
            if not isinstance(evidence, str) or not evidence.strip() or evidence not in source:
                raise ValueError('元件要求缺少原文依据，请明确元件数量、位置及尺寸')
            if type(req.get('quantity')) is not int or not 1 <= req['quantity'] <= 64:
                raise ValueError('元件数量应为1到64的整数')
            allowed = {'kind','quantity','region','diameter','width','thickness','offset','evidence'}
            if set(req)-allowed: raise ValueError('元件请求含未知选项，不接受模型生成的坐标或代码')
        before = len(self.state['tubes'])
        for req in sorted(requests, key=lambda r:rank[r['kind']]):
            if req['kind'] == '拉杆': self.add_rods(req)
            else: self.add_plates(req)
        self.inspect()
        self.state['revision'] += 1
        count = sum(r['quantity'] for r in requests)
        return f'已布置{count}个元件；为元件占位/预留空间共移除{before-len(self.state["tubes"])}个换热管位置'

    def add_component(self, component):
        if any(overlap(component,c) for c in self.state['components']):
            raise ValueError('新元件与已有元件干涉；可撤销或重布管后先放板件、最后放拉杆')
        component['id'] = len(self.state['components'])+1
        self.state['components'].append(component)

    def paired_u(self):
        p=self.state['parameters']
        return p.get('产品型式') in ('AEU','BEU','AKU','BKU') and p.get('管程程数')==2

    def add_plates(self, req):
        width = number(req.get('width'), '板件宽度')
        thickness = number(req.get('thickness'), '板件厚度', 100)
        p = self.state['parameters']; radius = p['公称直径 DN']/2
        if req['kind'] == '防冲板':
            if req['quantity'] != 1 or req['region'] not in ('上部','下部'):
                raise ValueError('防冲板先支持上部或下部各1块平板，请明确位置')
            offset = number(req.get('offset'), '防冲板距中心距离')
            y = -offset if req['region'] == '上部' else offset
            rects = [[-width/2,y-thickness/2,width,thickness]]
        else:
            if req['quantity'] not in (2,4) or req['region'] != '左右':
                raise ValueError('旁路挡板先支持左右2块或上下成对的左右4块')
            rects = []
            for y in ([0] if req['quantity']==2 else [-radius*.32,radius*.32]):
                edge = math.sqrt(max(0,radius**2-(abs(y)+thickness/2)**2))
                rects += [[-edge,y-thickness/2,width,thickness], [edge-width,y-thickness/2,width,thickness]]
        for rect in rects:
            x,y,w,h = rect
            if any(math.hypot(xx,yy) > radius+1e-5 for xx in (x,x+w) for yy in (y,y+h)):
                raise ValueError('板件超出壳体内边界，请减小宽度或距中心距离')
            component = dict(kind=req['kind'],rect=rect,width=width,thickness=thickness,region=req['region'])
            self.add_component(component)
            def reserved(point):
                collision = rect_circle(rect,point,p['换热管外径 do']/2)
                cap = req['kind']=='防冲板' and (
                    point[1] < y+h+p['换热管外径 do']/2 if req['region']=='上部'
                    else point[1] > y-p['换热管外径 do']/2)
                return collision or cap
            def removed(point):
                return reserved(point) or (self.paired_u() and reserved((point[0],-point[1])))
            if any(removed(c['center']) for c in self.state['components'] if c['kind']=='拉杆'):
                raise ValueError('板件预留区域包含已有拉杆，请先撤销拉杆或重新布管后先放板件')
            self.state['tubes'] = [point for point in self.state['tubes'] if not removed(point)]
        if not self.state['tubes']: raise ValueError('板件预留空间删除了全部管孔，请减小尺寸或移动位置')

    def add_rods(self, req):
        p = self.state['parameters']; d = p['换热管外径 do']
        # 与主程序_get_default_lg_diameter相同的推荐档位，仅在未给直径时使用。
        default = 10 if d<=14 else 12 if d<25 else 16 if d<=32 else 20
        diameter = number(req.get('diameter',default), '拉杆直径', 57)
        if diameter > d: raise ValueError('此Demo的拉杆占用已有管孔，直径不得大于换热管外径')
        region = req.get('region'); quantity = req['quantity']
        selectors = {'外围对称':lambda x,y:True,'上部':lambda x,y:y<0,'下部':lambda x,y:y>0,
                     '左侧':lambda x,y:x<0,'右侧':lambda x,y:x>0}
        if region not in selectors: raise ValueError('拉杆位置可选外围对称、上部、下部、左侧、右侧')
        if self.paired_u() and region!='外围对称':
            raise ValueError('U形管2管程需保持上下配对，请将拉杆位置设为外围对称')
        pool = [tuple(pt) for pt in self.state['tubes'] if selectors[region](*pt)]
        if region=='外围对称' and quantity%2: raise ValueError('外围对称的拉杆数量应为偶数')
        selected=[]; available=set(pool)
        i=0
        while len(selected)<quantity:
            angle = i*math.pi/max(1,quantity//2) if region=='外围对称' else i*math.tau/quantity
            def score(pt):
                r=math.hypot(*pt)
                return math.cos(math.atan2(pt[1],pt[0])-angle)*.6 + r/(p['布管限定圆 DL']/2)*.4
            def group_for(pt):
                if region!='外围对称':return {pt}
                if self.paired_u():return {pt,(-pt[0],pt[1]),(pt[0],-pt[1]),(-pt[0],-pt[1])}
                return {pt,(-pt[0],-pt[1])}
            options = [pt for pt in available if group_for(pt)<=available
                       and len(group_for(pt))<=quantity-len(selected)]
            if not options: raise ValueError('剩余管孔不足以满足拉杆数量/对称要求，请调整位置或减少数量')
            chosen=max(options,key=score)
            group=sorted(group_for(chosen))
            if len(set(group))!=len(group): raise ValueError('当前孔位不能满足外围对称，请重新选择')
            selected.extend(group)
            available.difference_update(group)
            i+=1
        for point in selected:
            self.add_component(dict(kind='拉杆',center=point,diameter=diameter,region=region,
                                    diameter_source='用户指定' if 'diameter' in req else '沿用原程序推荐档位'))
        used=set(selected)
        self.state['tubes']=[pt for pt in self.state['tubes'] if tuple(pt) not in used]

    def inspect(self):
        if not self.state['laid_out']: raise ValueError('尚未布管，不能完成设计检查')
        components = self.state['components']; d=self.state['parameters']['换热管外径 do']
        if self.paired_u():
            heat_keys={(round(x,6),round(y,6)) for x,y in self.state['tubes']}
            rod_keys={(round(c['center'][0],6),round(c['center'][1],6)) for c in components if c['kind']=='拉杆'}
            if any((x,-y) not in heat_keys for x,y in heat_keys) or any((x,-y) not in rod_keys for x,y in rod_keys):
                raise ValueError('U形管上下孔位未配对，请重新布管并采用对称元件布置')
        for i,a in enumerate(components):
            if any(overlap(a,b) for b in components[i+1:]): raise ValueError('发现元件之间干涉，请调整布置')
            for point in self.state['tubes']:
                if a['kind']=='拉杆':
                    conflict=math.dist(a['center'],point)<(a['diameter']+d)/2-1e-6
                else: conflict=rect_circle(a['rect'],point,d/2)
                if conflict: raise ValueError('发现元件与换热管干涉，请调整布置')
        return '已完成Demo覆盖的几何检查：元件与剩余换热管、元件之间未发现干涉；未执行完整制造与强度校核'
