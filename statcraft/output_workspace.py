"""Result-document tabs, non-destructive close/reopen and project ReportPad."""
import copy
from PySide6.QtCore import Qt,QSignalBlocker,QTimer
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTabBar, QComboBox, QMenu,
    QPlainTextEdit, QSplitter, QLabel, QToolButton, QFrame,
)
from . import workspace_state as ws


class OutputWorkspace:
    def __init__(self,window,layout):
        self.window=window;self.layout=layout;self.history=window.presenter.history;self.state=ws.empty();self.busy=False
        self._split_splitter=None;self._secondary_pane=None;self._secondary_key=None
        self.row=QWidget();box=QHBoxLayout(self.row);box.setContentsMargins(0,0,4,0);box.setSpacing(4)
        self.tabs=QTabBar();self.tabs.setExpanding(False);self.tabs.setMovable(True);self.tabs.setTabsClosable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight);self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self.select_index);self.tabs.tabCloseRequested.connect(self.close_index)
        self.tabs.tabMoved.connect(self.moved);self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.context_menu)
        self.views=QComboBox();self.views.setFixedWidth(124);self.views.setToolTip('Output view')
        self.views.currentTextChanged.connect(self.choose_view)
        box.addWidget(self.tabs,1);box.addWidget(self.views);layout.insertWidget(0,self.row)
        window.result_tabs.currentChanged.connect(self.sync_views)
        self.pad=QPlainTextEdit(window);self.pad.hide();self.pad.setPlaceholderText('Send results to this report, or type notes here.')
        self.pad.textChanged.connect(self.pad_edited);window._report_pad_editor=self.pad
        for sequence,callback in [('Ctrl+W',self.close_current),('Ctrl+Shift+T',self.reopen),('Ctrl+Tab',lambda:self.cycle(1)),('Ctrl+Shift+Tab',lambda:self.cycle(-1))]:
            shortcut=QShortcut(QKeySequence(sequence),window);shortcut.activated.connect(callback)

    def key(self,entry):return entry.get('entry_id') or 'native:'+str(id(entry))

    def entries(self):return {self.key(e):e for e in self.window.presenter.history}

    def sync_document(self):
        if self.history is self.window.presenter.history:return
        self.unsplit_view()
        self.history=self.window.presenter.history;self.state=ws.empty()
        self.window._output_zoom_levels.clear()
        with QSignalBlocker(self.pad):self.pad.clear()
        self.rebuild()

    def rebuild(self):
        entries=self.entries();self.state=ws.prune(self.state,entries,strict=False)
        with QSignalBlocker(self.tabs):
            while self.tabs.count():self.tabs.removeTab(0)
            for key in self.state['open_ids']:
                title='ReportPad' if key==ws.REPORT else entries[key].get('title','Result')
                i=self.tabs.addTab(title);self.tabs.setTabData(i,key);self.tabs.setTabToolTip(i,title)
            if self.state['active'] in self.state['open_ids']:self.tabs.setCurrentIndex(self.state['open_ids'].index(self.state['active']))
        self.row.setVisible(bool(self.state['open_ids']));self.sync_views()
        if self.is_split():
            if len(self.state['open_ids'])<2:
                self.unsplit_view()
            else:
                if self._secondary_key not in self.state['open_ids'] or self._secondary_key==self.state['active']:
                    self._secondary_key=next((k for k in self.state['open_ids'] if k!=self.state['active']),None)
                self._refresh_secondary_pane()

    def remember(self):
        if self.busy:return
        key=self.state['active'];w=self.window
        if key is None:return
        curr_text = w.result_tabs.tabText(w.result_tabs.currentIndex())
        v_name = curr_text if curr_text in ws.VIEWS else 'Graph'
        record={'view':v_name,'zoom':{},'scroll':{},'editor':not w.graph_options_pane.isHidden()}
        for i in range(w.result_tabs.count()):
            page=w.result_tabs.widget(i);name=w.result_tabs.tabText(i)
            target_name = name if name in ws.VIEWS else 'Graph'
            zoom=getattr(page,'percent',w._output_zoom_levels.get((key,name),100))
            record['zoom'][target_name]=max(10,min(500,int(zoom)))
            if hasattr(page,'horizontalScrollBar'):record['scroll'][target_name]=[page.horizontalScrollBar().value(),page.verticalScrollBar().value()]
        if record['view'] not in ws.VIEWS:record['view']='Report'
        self.state['views'][key]=record;self.state['report_pad']=self.pad.toPlainText()

    def before_show(self,entry):
        self.sync_document();self.remember();key=self.key(entry)
        if key not in self.state['open_ids']:self.state['open_ids'].append(key)
        self.state['closed_ids']=[k for k in self.state['closed_ids'] if k!=key]
        self.state['active']=key;self.busy=True
        for name,zoom in self.state['views'].get(key,{}).get('zoom',{}).items():self.window._output_zoom_levels[(key,name)]=zoom

    def after_show(self, target_index=None):
        self.busy=False;self.rebuild();w=self.window
        key=self.state['active'];record=copy.deepcopy(self.state['views'].get(key,{}))
        view=record.get('view')
        if target_index is not None and 0 <= target_index < w.result_tabs.count():
            w.result_tabs.setCurrentIndex(target_index)
        elif view:
            i=next((i for i in range(w.result_tabs.count()) if w.result_tabs.tabText(i)==view),-1)
            if i>=0:w.result_tabs.setCurrentIndex(i)
        w.result_tabs.tabBar().show();w.tab_corner_widget.show();self.sync_views()
        if record.get('editor') and w.selected_entry is not None and w._active_graph_frame is not None:w.edit_graph_dialog(w.selected_entry)
        elif record:w.graph_options_pane.hide()
        def restore_scroll():
            if self.state['active']!=key:return
            for i in range(w.result_tabs.count()):
                page=w.result_tabs.widget(i);values=record.get('scroll',{}).get(w.result_tabs.tabText(i))
                if values and hasattr(page,'horizontalScrollBar'):
                    page.horizontalScrollBar().setValue(values[0]);page.verticalScrollBar().setValue(values[1])
        timer=QTimer(w);timer.setSingleShot(True)
        timer.timeout.connect(restore_scroll);timer.timeout.connect(timer.deleteLater);timer.start(0)

    def sync_views(self,*unused):
        if self.busy:return
        w=self.window
        with QSignalBlocker(self.views):
            self.views.clear();self.views.addItems([w.result_tabs.tabText(i) for i in range(w.result_tabs.count())])
            self.views.setCurrentIndex(w.result_tabs.currentIndex())

    def choose_view(self,name):
        if self.busy:return
        w=self.window
        for i in range(w.result_tabs.count()):
            if w.result_tabs.tabText(i)==name:w.result_tabs.setCurrentIndex(i);break

    def select_index(self,index):
        if self.busy or index<0:return
        key=self.tabs.tabData(index)
        if key==self.state['active']:return
        self.activate(key)

    def activate(self,key):
        w=self.window
        if not w.graph_options_pane.flush():self.rebuild();return
        if key==ws.REPORT:
            self.remember();self.state['active']=key
            if key not in self.state['open_ids']:self.state['open_ids'].append(key)
            w.selected_entry=None;w._clear_result_tabs();self.attach_pad();w.result_tabs.setCurrentWidget(self.pad)
            w.graph_options_pane.load_entry(None);w.graph_options_pane.hide();self.rebuild()
            record=self.state['views'].get(ws.REPORT,{})
            w.set_zoom(record.get('zoom',{}).get('ReportPad',100))
            scroll=record.get('scroll',{}).get('ReportPad',[0,0])
            self.pad.horizontalScrollBar().setValue(scroll[0]);self.pad.verticalScrollBar().setValue(scroll[1])
            return
        entry=self.entries().get(key)
        if entry is not None:w.show_result(entry)

    def close_index(self,index):
        if not 0<=index<len(self.state['open_ids']):return
        w=self.window
        if not w.graph_options_pane.flush():return
        self.remember();key=self.state['open_ids'].pop(index)
        self.state['closed_ids']=[x for x in self.state['closed_ids'] if x!=key]+[key]
        self.state['closed_ids']=self.state['closed_ids'][-101:]
        if key==self.state['active']:
            self.state['active']=None
            if self.state['open_ids']:self.activate(self.state['open_ids'][min(index,len(self.state['open_ids'])-1)])
            else:w._show_welcome()
        self.rebuild()

    def close_current(self):
        if self.state['active'] in self.state['open_ids']:self.close_index(self.state['open_ids'].index(self.state['active']))

    def close_all(self,except_key=None):
        for key in list(self.state['open_ids']):
            if key!=except_key:self.close_index(self.state['open_ids'].index(key))

    def reopen(self):
        self.state=ws.prune(self.state,self.entries(),strict=False)
        if self.state['closed_ids']:
            key=self.state['closed_ids'].pop()
            if key not in self.state['open_ids']:self.state['open_ids'].append(key)
            self.activate(key)

    def moved(self,old,new):
        if self.busy:return
        key=self.state['open_ids'].pop(old);self.state['open_ids'].insert(new,key)

    def cycle(self,step):
        count=self.tabs.count()
        if count:self.tabs.setCurrentIndex((self.tabs.currentIndex()+step)%count)

    def context_menu(self,point):
        index=self.tabs.tabAt(point)
        if index<0:return
        key=self.tabs.tabData(index);menu=QMenu(self.window)
        menu.addAction('Close',lambda:self.close_index(self.state['open_ids'].index(key)))
        menu.addAction('Close Other Tabs',lambda:self.close_all(key));menu.addAction('Close All Tabs',self.close_all)
        menu.addAction('Reopen Closed Tab',self.reopen).setEnabled(bool(self.state['closed_ids']))
        menu.addSeparator()
        if self.tabs.count()>=2:
            menu.addAction('Split View',lambda idx=index:self.split_view(idx))
        if self.is_split():
            menu.addAction('Unsplit View',self.unsplit_view)
        menu.exec(self.tabs.mapToGlobal(point))

    def is_split(self) -> bool:
        return self._split_splitter is not None

    def split_view(self, secondary_index=None) -> bool:
        """Show a second open output tab side-by-side with the active result pane."""
        count = self.tabs.count()
        if count < 2:
            return False
        active_idx = self.tabs.currentIndex()
        if active_idx < 0:
            active_idx = 0
        if secondary_index is None:
            secondary_index = (active_idx + 1) % count
        else:
            if not (0 <= secondary_index < count):
                return False
            if secondary_index == active_idx:
                secondary_index = (active_idx + 1) % count
        sec_key = self.tabs.tabData(secondary_index)
        if sec_key is None:
            return False
        self._secondary_key = sec_key
        if self._split_splitter is None:
            w = self.window
            idx = self.layout.indexOf(w.result_tabs)
            if idx < 0:
                return False
            self._split_splitter = QSplitter(Qt.Orientation.Horizontal)
            self._secondary_pane = self._build_secondary_pane()
            self.layout.removeWidget(w.result_tabs)
            self._split_splitter.addWidget(w.result_tabs)
            self._split_splitter.addWidget(self._secondary_pane)
            self.layout.insertWidget(idx, self._split_splitter, 1)
            self._split_splitter.setSizes([500, 500])
            w.result_tabs.show()
            self._secondary_pane.show()
        self._refresh_secondary_pane()
        return True

    def unsplit_view(self) -> bool:
        """Restore single-pane output view."""
        if self._split_splitter is None:
            return False
        w = self.window
        idx = self.layout.indexOf(self._split_splitter)
        if idx < 0:
            idx = self.layout.count()
        w.result_tabs.setParent(None)
        self.layout.insertWidget(idx, w.result_tabs, 1)
        w.result_tabs.show()
        self._split_splitter.hide()
        self._split_splitter.deleteLater()
        self._split_splitter = None
        self._secondary_pane = None
        self._secondary_key = None
        return True

    def _build_secondary_pane(self):
        pane = QFrame()
        pane.setObjectName("splitSecondaryPane")
        vbox = QVBoxLayout(pane)
        vbox.setContentsMargins(6, 4, 6, 6)
        vbox.setSpacing(4)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._secondary_title = QLabel("Secondary View")
        self._secondary_title.setStyleSheet("font-weight: 600;")
        close_btn = QToolButton()
        close_btn.setText("×")
        close_btn.setToolTip("Unsplit View")
        close_btn.clicked.connect(self.unsplit_view)
        header.addWidget(self._secondary_title, 1)
        header.addWidget(close_btn)
        vbox.addLayout(header)
        self._secondary_body = QPlainTextEdit()
        self._secondary_body.setReadOnly(True)
        vbox.addWidget(self._secondary_body, 1)
        return pane

    def _refresh_secondary_pane(self):
        if self._secondary_pane is None:
            return
        key = self._secondary_key
        if key == ws.REPORT:
            self._secondary_title.setText("ReportPad")
            self._secondary_body.setPlainText(self.pad.toPlainText())
            return
        entry = self.entries().get(key)
        if entry is None:
            self._secondary_title.setText("Result")
            self._secondary_body.setPlainText("")
            return
        self._secondary_title.setText(entry.get("title", "Result"))
        from .office_export import report_text
        self._secondary_body.setPlainText(report_text(entry))

    def attach_pad(self):
        w=self.window
        if w.result_tabs.indexOf(self.pad)<0:w.result_tabs.addTab(self.pad,'ReportPad')

    def show_pad(self):self.activate(ws.REPORT)

    def pad_edited(self):
        if self.busy:return
        self.state['report_pad']=self.pad.toPlainText();self.window.presenter._results_dirty=True

    def append(self,entry):
        from .office_export import report_text
        text=self.pad.toPlainText();addition=report_text(entry)
        from PySide6.QtGui import QTextCursor
        cursor=self.pad.textCursor();cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock();cursor.insertText(('\n\n'+'─'*60+'\n\n' if text else '')+addition);cursor.endEditBlock()
        self.pad.setTextCursor(cursor)
        self.show_pad()

    def snapshot(self):
        self.remember();known=[self.key(e) for e in self.window.presenter.history if e.get('origin')=='statcraft']
        return ws.prune(self.state,known)

    def restore(self,state):
        self.history=self.window.presenter.history
        self.busy=True
        self.state=ws.prune(state or ws.empty(),self.entries())
        with QSignalBlocker(self.pad):self.pad.setPlainText(self.state['report_pad'])
        key=self.state['active'];self.state['active']=None;self.rebuild()
        if key:self.activate(key)
        self.busy=False;self.sync_views()
