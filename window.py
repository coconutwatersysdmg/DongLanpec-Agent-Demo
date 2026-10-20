"""A familiar tube-design workspace with a plain-language assistant on the right."""
from __future__ import annotations
import copy
from collections import Counter, defaultdict
import json
from pathlib import Path
import time
from PyQt5.QtCore import Qt,QThread,pyqtSignal,QSignalBlocker,QTimer
from PyQt5.QtGui import QColor,QPen,QBrush,QPainter
from PyQt5.QtWidgets import (
    QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QSplitter,QLabel,
    QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QComboBox,
    QPlainTextEdit,QTextBrowser,QToolButton,QGraphicsView,QGraphicsScene,QDialog,
    QFormLayout,QCheckBox,QSpinBox,QDoubleSpinBox,QDialogButtonBox,QFileDialog,
)
from engine import DesignEngine,FIELDS,EXAMPLE_TEXT
from agent import AgentRunner,BailianProvider,ScriptedProvider,LABELS
from settings import load_settings,settings_dialog


TUBE_COLOR = '#000050'
CENTER_CONNECTION_COLOR = '#0000ff'
SIDE_BAFFLE_COLOR = '#0000ff'
IMPINGEMENT_PLATE_COLOR = '#00008b'
BAFFLE_PLATE_COLOR = '#cccc00'


def neighboring_tube_pairs(centers,pitch):
    """Match the production editor: connect centers whose distance is S +/- 1 mm."""
    if pitch<=0:return []
    grid_size=pitch*1.2;grid={}
    for index,(x,y) in enumerate(centers):
        key=(round(x/grid_size),round(y/grid_size))
        grid.setdefault(key,[]).append((index,x,y))
    pairs=[];connected=set()
    for index,(x,y) in enumerate(centers):
        base=(round(x/grid_size),round(y/grid_size))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for other,xx,yy in grid.get((base[0]+dx,base[1]+dy),()):
                    if other==index:continue
                    key=tuple(sorted((index,other)))
                    if key in connected:continue
                    if pitch-1<=((xx-x)**2+(yy-y)**2)**.5<=pitch+1:
                        connected.add(key);pairs.append(((x,y),(xx,yy)))
    return pairs


class Canvas(QGraphicsView):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QColor('white'))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setMinimumWidth(360)
    def wheelEvent(self,event):
        self.scale(1.12 if event.angleDelta().y()>0 else 1/1.12,1.12 if event.angleDelta().y()>0 else 1/1.12)
    def fit(self):
        if self.scene():self.fitInView(self.scene().sceneRect(),Qt.KeepAspectRatio)
    def resizeEvent(self,event):super().resizeEvent(event);self.fit()
    def mouseDoubleClickEvent(self,event):self.fit();event.accept()


class AgentWorker(QThread):
    progress=pyqtSignal(object)
    done=pyqtSignal(object,object)
    failed=pyqtSignal(str,object)
    def __init__(self,provider,engine,instruction,offline=False,parent=None):
        super().__init__(parent);self.provider=provider;self.engine=engine;self.instruction=instruction;self.offline=offline
    def run(self):
        def event(item):
            self.progress.emit(item)
            if self.offline and item['type']=='tool_result':time.sleep(.15)
        try:
            result=AgentRunner(self.provider).run(self.instruction,self.engine,event,self.isInterruptionRequested)
            self.done.emit(result,self.engine.snapshot())
        except (ValueError,RuntimeError) as exc:self.failed.emit(str(exc),self.engine.snapshot())
        except Exception:self.failed.emit('本轮执行遇到问题，已完成步骤保留，可撤销后重试。',self.engine.snapshot())


class DesignWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.engine=DesignEngine();self.config=load_settings();self.worker=None
        self.history=[];self.trace=[];self.before_run=None;self._refreshing=False
        self.setWindowTitle('管束设计 · 智能设计助手 Demo')
        self.resize(1680,950)
        self.setStyleSheet('QMainWindow,QWidget{font-size:13px;} QMainWindow{background:white;}'
            'QPushButton{padding:7px 12px;border:1px solid #bdcadd;border-radius:3px;background:#f5f8fc;color:#1d527e;}'
            'QPushButton:hover{background:#e7f0fa;} QPushButton:disabled{color:#9ca7b1;background:#f2f3f5;}'
            'QTableWidget{gridline-color:#dce1e7;background:white;selection-background-color:#edf5fc;}'
            'QHeaderView::section{background:#f0f2f5;padding:6px;border:1px solid #d8dde4;}'
            'QPlainTextEdit,QTextBrowser{border:1px solid #ccd7e2;border-radius:4px;background:white;}')
        root_widget=QWidget();root=QVBoxLayout(root_widget);root.setContentsMargins(12,8,12,8)
        self.setCentralWidget(root_widget)
        header=QHBoxLayout();title=QLabel('管束设计')
        title.setStyleSheet('color:#175a91;font-size:24px;font-weight:600;');header.addWidget(title)
        header.addStretch()
        self.settings_button=QPushButton('⚙ AI设置');self.settings_button.clicked.connect(self.open_settings);header.addWidget(self.settings_button)
        help_button=QPushButton('使用说明');help_button.clicked.connect(self.show_help);header.addWidget(help_button)
        root.addLayout(header)
        workspace=QWidget();work=QHBoxLayout(workspace);work.setContentsMargins(0,10,0,0)
        root.addWidget(workspace,1)
        main_split=QSplitter(Qt.Horizontal);work.addWidget(main_split)
        left=QWidget();left_layout=QVBoxLayout(left);left_layout.setContentsMargins(0,0,6,0)
        self.param_table=QTableWidget(len(FIELDS),4)
        self.param_table.setHorizontalHeaderLabels(['序号','参数名','参数值','单位'])
        self.param_table.verticalHeader().hide();self.param_table.setColumnWidth(0,38)
        self.param_table.horizontalHeader().setMinimumSectionSize(28)
        self.param_table.setColumnWidth(1,165);self.param_table.setColumnWidth(2,90)
        self.param_table.setColumnWidth(3,36)
        self.param_table.horizontalHeader().setStretchLastSection(True)
        self.param_table.setMinimumWidth(345);self.param_table.setMaximumWidth(440)
        self.field_names=list(FIELDS);self.combo_fields={}
        for row,name in enumerate(self.field_names):
            for col,value in [(0,str(row+1)),(1,name),(3,FIELDS[name][1])]:
                item=QTableWidgetItem(value);item.setFlags(item.flags()&~Qt.ItemIsEditable)
                self.param_table.setItem(row,col,item)
            self.param_table.setRowHeight(row,38)
            kind=FIELDS[name][0]
            if isinstance(kind,tuple):
                combo=QComboBox();combo.addItem('');combo.addItems([str(x) for x in kind])
                self.param_table.setCellWidget(row,2,combo);self.combo_fields[name]=combo
                combo.currentTextChanged.connect(self.form_changed)
            else:self.param_table.setItem(row,2,QTableWidgetItem(''))
        self.param_table.itemChanged.connect(self.form_changed)
        left_layout.addWidget(self.param_table,1)
        main_split.addWidget(left)
        drawing=QWidget();draw_layout=QVBoxLayout(drawing);draw_layout.setContentsMargins(0,0,0,0)
        legend=QLabel('○ 换热管    <span style="color:#c52727">● 拉杆</span>    '
                      '<span style="color:#0000ff">▬ 旁路挡板</span>    '
                      '<span style="color:#00008b">▬ 防冲板</span>    '
                      '<span style="color:#cccc00">▬ 折流板</span>')
        legend.setStyleSheet('padding:8px;color:#435c75;');draw_layout.addWidget(legend)
        self.canvas=Canvas();draw_layout.addWidget(self.canvas,1)
        controls=QHBoxLayout()
        self.layout_button=QPushButton('布管');self.layout_button.clicked.connect(self.manual_layout)
        self.component_button=QPushButton('自动布置元件');self.component_button.clicked.connect(self.manual_components)
        self.undo_button=QPushButton('撤销本次操作');self.undo_button.clicked.connect(self.undo)
        fit_button=QPushButton('适应窗口');fit_button.clicked.connect(self.canvas.fit)
        for button in (self.layout_button,self.component_button,self.undo_button,fit_button):controls.addWidget(button)
        draw_layout.addLayout(controls);main_split.addWidget(drawing)
        stats=QWidget();stats_layout=QVBoxLayout(stats);stats_layout.setContentsMargins(5,0,5,0)
        self.count_label=QLabel('管孔数量分布');self.count_label.setWordWrap(True);stats_layout.addWidget(self.count_label)
        self.row_table=QTableWidget(0,3);self.row_table.setHorizontalHeaderLabels(['行号','上半部','下半部'])
        self.row_table.verticalHeader().hide();self.row_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.row_table.setEditTriggers(QAbstractItemView.NoEditTriggers);stats.setMinimumWidth(185);stats.setMaximumWidth(240)
        stats_layout.addWidget(self.row_table,1);main_split.addWidget(stats)
        assistant=QWidget();assistant.setMinimumWidth(320);assistant.setMaximumWidth(420)
        ai=QVBoxLayout(assistant);ai.setContentsMargins(10,0,0,0)
        label=QLabel('设计助手');label.setStyleSheet('font-size:19px;font-weight:600;color:#175a91;');ai.addWidget(label)
        self.mode=QComboBox();self.mode.addItems(['百炼AI · 按你的要求设计','离线操作演示 · 固定示例'])
        ai.addWidget(self.mode)
        self.prompt=QPlainTextEdit();self.prompt.setMinimumHeight(180);self.prompt.setMaximumHeight(260)
        self.prompt.setPlaceholderText('例如：按左侧参数布管，再左右放2块旁路挡板……\n\n尚未填参时，请把DN、管径、间距、DL等写在要求里。')
        ai.addWidget(self.prompt)
        self.example_button=QPushButton('填入完整设计示例')
        self.example_button.clicked.connect(lambda:self.prompt.setPlainText(EXAMPLE_TEXT));ai.addWidget(self.example_button)
        run_row=QHBoxLayout();self.run_button=QPushButton('开始设计');self.run_button.setStyleSheet('background:#2268a0;color:white;padding:10px;font-weight:600;')
        self.run_button.clicked.connect(self.start_agent);run_row.addWidget(self.run_button,1)
        self.stop_button=QPushButton('停止');self.stop_button.setEnabled(False);self.stop_button.clicked.connect(self.stop_agent);run_row.addWidget(self.stop_button)
        ai.addLayout(run_row)
        self.progress=QLabel('等待设计要求');self.progress.setWordWrap(True);self.progress.setStyleSheet('padding:10px;background:#edf4fb;color:#1c5a89;');ai.addWidget(self.progress)
        self.conversation=QTextBrowser();self.conversation.setOpenExternalLinks(False);ai.addWidget(self.conversation,1)
        detail_toggle=QToolButton();detail_toggle.setText('执行详情');detail_toggle.setCheckable(True)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(180);self.details.hide()
        detail_toggle.toggled.connect(self.details.setVisible);ai.addWidget(detail_toggle);ai.addWidget(self.details)
        save=QPushButton('保存设计方案');save.clicked.connect(self.export_design);ai.addWidget(save)
        main_split.addWidget(assistant);main_split.setSizes([375,650,195,345])
        main_split.setStretchFactor(1,1)
        self.status=QLabel('尚未布管。右侧助手可自动填参、布管，再布置元件。')
        self.status.setStyleSheet('color:#4f6b83;padding:8px;');self.status.setWordWrap(True);root.addWidget(self.status)
        self.refresh()
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def refresh(self):
        self._refreshing=True
        try:
            p=self.engine.state['parameters']
            for row,name in enumerate(self.field_names):
                value=p.get(name,'');text=str(value)
                if type(value) is float and value.is_integer():text=str(int(value))
                if name in self.combo_fields:self.combo_fields[name].setCurrentText(text)
                else:self.param_table.item(row,2).setText(text)
            self.component_button.setEnabled(self.engine.state['laid_out'] and self.worker is None)
            self.undo_button.setEnabled(bool(self.history) and self.worker is None)
            self.draw();self.update_stats()
        finally:self._refreshing=False

    def form_changed(self,*args):
        if self._refreshing or self.worker is not None:return
        rows=[];source=[]
        try:
            for row,name in enumerate(self.field_names):
                kind=FIELDS[name][0]
                text=self.combo_fields[name].currentText() if name in self.combo_fields else self.param_table.item(row,2).text().strip()
                if not text:continue
                value=float(text) if not isinstance(kind,tuple) or type(kind[0]) is int else text
                if type(value) is float and value.is_integer():value=int(value)
                evidence=name+'='+text;source.append(evidence)
                rows.append(dict(name=name,value=value,unit=FIELDS[name][1],evidence=evidence))
            fresh=DesignEngine()
            if rows:
                result=fresh.call('set_parameters',{'parameters':rows},'；'.join(source))
                if not result['ok']:raise ValueError(result['message'])
            if fresh.state['parameters']!=self.engine.state['parameters']:
                self.history.append(self.engine.snapshot());self.engine.restore(fresh.snapshot())
                self.status.setText('参数已更新。点击“布管”，或让助手继续设计。')
        except (ValueError,TypeError):self.status.setText('参数未保存：请填写有效数值，并检查直径、间距与壁厚关系。')
        self.refresh()

    def draw(self):
        state=self.engine.state;p=state['parameters'];dn=float(p.get('公称直径 DN') or 1300)
        scene=QGraphicsScene(self.canvas);r=dn/2
        border=QPen(QColor('#33404c'));border.setCosmetic(True)
        scene.addEllipse(-r,-r,dn,dn,border)
        dl=float(p.get('布管限定圆 DL') or dn*.95)
        thin=QPen(QColor('#aab5c2'));thin.setCosmetic(True)
        scene.addEllipse(-dl/2,-dl/2,dl,dl,thin)
        axis_length=r*1.1;arrow=max(dn*.008,7)
        for color,a,b in [('#ff0000',(-axis_length,0),(axis_length,0)),('#00ff00',(0,-axis_length),(0,axis_length))]:
            axis_color=QColor(color);axis_color.setAlpha(128)
            pen=QPen(axis_color);pen.setWidthF(3)
            scene.addLine(*a,*b,pen)
            if a[1]==b[1]:
                scene.addLine(b[0],b[1],b[0]-arrow,b[1]-arrow/2,pen);scene.addLine(b[0],b[1],b[0]-arrow,b[1]+arrow/2,pen)
                scene.addLine(a[0],a[1],a[0]+arrow,a[1]-arrow/2,pen);scene.addLine(a[0],a[1],a[0]+arrow,a[1]+arrow/2,pen)
            else:
                scene.addLine(b[0],b[1],b[0]-arrow/2,b[1]-arrow,pen);scene.addLine(b[0],b[1],b[0]+arrow/2,b[1]-arrow,pen)
                scene.addLine(a[0],a[1],a[0]-arrow/2,a[1]+arrow,pen);scene.addLine(a[0],a[1],a[0]+arrow/2,a[1]+arrow,pen)
        for x,y,label in [(0,-r*1.17,'0°'),(r*1.1,0,'90°'),(0,r*1.10,'180°'),(-r*1.23,0,'270°')]:
            text=scene.addText(label);text.setPos(x,y);text.setScale(dn/900)
        d=float(p.get('换热管外径 do') or 25)
        rods=[tuple(comp['center']) for comp in state['components'] if comp['kind']=='拉杆']
        connection_pen=QPen(QColor(CENTER_CONNECTION_COLOR));connection_pen.setCosmetic(True)
        pitch=float(p.get('换热管中心距 S') or 0)
        for (x1,y1),(x2,y2) in neighboring_tube_pairs([*state['tubes'],*rods],pitch):
            scene.addLine(x1,y1,x2,y2,connection_pen)
        tube_pen=QPen(QColor(TUBE_COLOR));tube_pen.setCosmetic(True)
        for x,y in state['tubes']:scene.addEllipse(x-d/2,y-d/2,d,d,tube_pen)
        for comp in state['components']:
            if comp['kind']=='拉杆':
                x,y=comp['center'];dd=comp['diameter']
                scene.addEllipse(x-d/2,y-d/2,d,d,QPen(QColor('#cb352f')))
                scene.addEllipse(x-dd/2,y-dd/2,dd,dd,QPen(QColor('#cb352f')),QBrush(QColor('#cb352f')))
            else:
                color=QColor(SIDE_BAFFLE_COLOR if comp['kind']=='旁路挡板'
                             else BAFFLE_PLATE_COLOR if comp['kind']=='折流板'
                             else IMPINGEMENT_PLATE_COLOR)
                scene.addRect(*comp['rect'],QPen(color),QBrush(color))
        if not state['laid_out']:
            hint=scene.addText('填写参数后布管\n也可以让右侧助手自动完成')
            hint.setDefaultTextColor(QColor('#72869c'));hint.setScale(dn/850);hint.setPos(-dn*.22,-dn*.08)
        scene.setSceneRect(-r*1.3,-r*1.3,dn*1.3,dn*1.3)
        old=self.canvas.scene();self.canvas.setScene(scene)
        if old:old.deleteLater()
        self.canvas.fit()

    def update_stats(self):
        groups=defaultdict(lambda:[0,0])
        for x,y in self.engine.state['tubes']:groups[round(abs(y),5)][0 if y<0 else 1]+=1
        self.row_table.setRowCount(len(groups))
        for row,(_y,counts) in enumerate(sorted(groups.items())):
            for col,value in enumerate([row+1,*counts]):self.row_table.setItem(row,col,QTableWidgetItem(str(value)))
        counts=Counter(c['kind'] for c in self.engine.state['components'])
        self.count_label.setText(f'管孔数量分布\n换热管位置：{len(self.engine.state["tubes"])}\n拉杆：{counts["拉杆"]}\n旁路挡板：{counts["旁路挡板"]}  防冲板：{counts["防冲板"]}')

    def manual_layout(self):
        before=self.engine.snapshot();result=self.engine.call('layout_tubes',{})
        if result['ok']:self.history.append(before)
        self.status.setText(result['message']);self.refresh()

    def manual_components(self):
        if not self.engine.state['laid_out']:self.status.setText('请先布管，再布置元件。');return
        dialog=QDialog(self);dialog.setWindowTitle('自动布置元件');root=QVBoxLayout(dialog)
        root.addWidget(QLabel('选择元件并填写尺寸，程序自动选位。板件先放，拉杆后放。'))
        options=[]
        for kind in ('拉杆','旁路挡板','防冲板'):
            check=QCheckBox(kind);check.setChecked(kind=='拉杆');root.addWidget(check)
            form=QFormLayout();quantity=QSpinBox();quantity.setRange(1,64);quantity.setValue(8 if kind=='拉杆' else 2 if kind=='旁路挡板' else 1)
            form.addRow('数量',quantity);region=QComboBox()
            region.addItems(['外围对称','上部','下部','左侧','右侧'] if kind=='拉杆' else ['左右'] if kind=='旁路挡板' else ['上部','下部'])
            form.addRow('位置',region);fields={}
            specs=[('diameter','直径',16)] if kind=='拉杆' else [('width','宽度',40 if kind=='旁路挡板' else 300),('thickness','厚度',3 if kind=='旁路挡板' else 6)]
            if kind=='防冲板':specs.append(('offset','距中心',500))
            for key,label,value in specs:
                box=QDoubleSpinBox();box.setRange(.1,10000);box.setSuffix(' mm');box.setValue(value)
                form.addRow(label,box);fields[key]=box
            root.addLayout(form);options.append((kind,check,quantity,region,fields))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('开始布置');buttons.button(QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);root.addWidget(buttons)
        if dialog.exec_()!=QDialog.Accepted:return
        requests=[]
        for kind,check,quantity,region,fields in options:
            if check.isChecked():
                req=dict(kind=kind,quantity=quantity.value(),region=region.currentText(),**{k:b.value() for k,b in fields.items()})
                req['evidence']='手动选择'+json.dumps(req,ensure_ascii=False);requests.append(req)
        before=self.engine.snapshot();source='；'.join(r['evidence'] for r in requests)
        result=self.engine.call('place_components',{'components':requests},source)
        if result['ok']:self.history.append(before)
        self.status.setText(result['message']);self.refresh()

    def start_agent(self):
        if self.worker is not None:return
        text=self.prompt.toPlainText().strip()
        if not text:self.progress.setText('先写下设计要求，或点击“填入完整设计示例”。');return
        offline=self.mode.currentIndex()==1
        if offline and text!=EXAMPLE_TEXT:
            self.progress.setText('离线演示只演示固定示例。请填入完整示例；自己的描述请选择百炼AI。');return
        if not offline and not self.config.configured:
            self.progress.setText('首次使用请点击右上角“AI设置”，输入百炼密钥。');self.open_settings();return
        before=self.engine.snapshot();self.before_run=before
        model_engine=DesignEngine();model_engine.restore(before)
        self.trace=[];self.details.clear();self.conversation.setPlainText('正在处理你的设计要求…')
        if offline:self.conversation.setPlainText('当前为固定操作演示，不调用AI；布管与元件工具是真实执行。')
        provider=ScriptedProvider() if offline else BailianProvider(self.config)
        self.worker=AgentWorker(provider,model_engine,text,offline,QApplication.instance())
        self.worker.progress.connect(self.on_event);self.worker.done.connect(self.finished_result)
        self.worker.failed.connect(self.failed_result);self.worker.finished.connect(self.worker_finished)
        self.set_busy(True);self.worker.start()

    def set_busy(self,busy):
        self.prompt.setReadOnly(busy);self.param_table.setEnabled(not busy)
        for widget in (self.run_button,self.settings_button,self.mode,self.example_button,self.layout_button,self.component_button,self.undo_button):widget.setEnabled(not busy)
        self.stop_button.setEnabled(busy)

    def on_event(self,event):
        clean={k:v for k,v in event.items() if k!='snapshot'};self.trace.append(clean)
        if event['type']=='tool_result':
            self.engine.restore(event['snapshot']);self.refresh()
            self.progress.setText(('✓ ' if event['ok'] else '需要调整：')+event['message'])
            self.details.appendPlainText(json.dumps(clean,ensure_ascii=False))
        elif event['type']=='tool_start':
            self.progress.setText(event['message']+'…');self.details.appendPlainText(json.dumps(clean,ensure_ascii=False))
        else:self.progress.setText(event['message'])

    def finished_result(self,result,state):
        self.engine.restore(state)
        prefix='本轮操作完成。' if result['status']=='completed' else '请继续补充或调整。' if result['status']=='needs_input' else ''
        self.status.setText(prefix+result['summary'])
        self.conversation.setPlainText(result.get('reply') or result['summary'])
        self.progress.setText('已完成本轮设计' if result['status']=='completed' else result['summary'])
        self.record_run();self.refresh()

    def failed_result(self,message,state):
        self.engine.restore(state);self.progress.setText(message);self.status.setText(message)
        self.conversation.setPlainText('可以修改要求后重试，或撤销本轮已完成的步骤。');self.record_run();self.refresh()

    def record_run(self):
        if self.before_run is not None and self.before_run!=self.engine.state:self.history.append(self.before_run)
        self.before_run=None;self.history=self.history[-20:]

    def worker_finished(self):
        worker,self.worker=self.worker,None;worker.deleteLater();self.set_busy(False);self.refresh()

    def stop_agent(self):
        if self.worker:self.worker.requestInterruption();self.progress.setText('正在停止后续操作；当前网络请求返回后停止。')

    def undo(self):
        if self.worker is not None or not self.history:return
        self.engine.restore(self.history.pop());self.status.setText('已撤销，恢复到本次操作之前的设计。');self.refresh()

    def open_settings(self):self.config=settings_dialog(self,self.config)

    def export_design(self):
        if self.worker is not None:self.status.setText('请等本轮设计完成后再保存。');return
        path,_=QFileDialog.getSaveFileName(self,'保存设计方案','管束设计方案.json','管束设计方案 (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps({'version':1,'design':self.engine.snapshot(),'execution':self.trace,
                    'mode':self.mode.currentText()},ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
                self.status.setText('设计方案已保存，包含参数、孔位和元件，不包含密钥。')
            except OSError:self.status.setText('保存失败，请换一个可写目录。')

    def show_help(self):
        dialog=QDialog(self);dialog.setWindowTitle('如何使用');dialog.resize(580,400);layout=QVBoxLayout(dialog)
        text=QTextBrowser();text.setPlainText('1. 首次使用，点右上角“AI设置”，粘贴百炼密钥。\n\n'
            '2. 写下设计要求，点“开始设计”。助手会填参、布管，再布置元件。\n\n'
            '3. 没想好怎么说？点“填入完整设计示例”试一次。离线操作演示不联网。\n\n'
            '4. 参数也能手改；手改后重新布管。元件按钮会自动选位，无需逐个点孔。\n\n'
            '5. 不满意可撤销本轮，满意可保存设计方案。\n\n'
            '第一版支持内径基准、1/2管程及三类元件。板件按Demo几何策略布置，尚未替代完整制造/强度校核。')
        layout.addWidget(text);dialog.exec_()

    def shutdown(self):
        if self.worker:self.worker.requestInterruption();self.worker.wait()

    def closeEvent(self,event):
        if self.worker is not None:
            self.stop_agent();self.status.setText('正在停止，请等待当前请求结束后再关闭。');event.ignore()
        else:super().closeEvent(event)
