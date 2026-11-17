"""Original Qt dialogs guided by recovered RT_DIALOG3599/3692 and children.

Resource label/layout evidence: outputs/statcraft-doe-ui-contract.md.
Defaults and unsupported choices are StatCraft decisions, not native-runtime parity.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,
    QGroupBox,QRadioButton,QComboBox,QSpinBox,QCheckBox,QLineEdit,QLabel,QPushButton,
    QTableWidget,QTableWidgetItem,QDialogButtonBox,QHeaderView,QListWidget,QListWidgetItem,
    QAbstractItemView,QMessageBox,QApplication)
from .model import finite_number
from .variable_dialogs import ProcedureDialog,resolve_variables


def buttons(dialog,layout,callback=None):
    row=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    row.accepted.connect(callback or dialog.accept); row.rejected.connect(dialog.reject); layout.addWidget(row)
    return row


class CreateFactorialDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle('Create Factorial Design'); self.setMinimumWidth(680)
        self.setSizeGripEnabled(True)
        self.parameters=None; self.replicates=2; self.centers=0; self.blocks=1; self.randomize=True; self.seed=1; self.summary=True
        self.generators={}; self.design_types=[]
        self.catalog_parameters={}
        self.default_runs_by_factor = {}
        from .fractional import _FACTOR_LETTERS
        self.factors=[{'name':_FACTOR_LETTERS[i],'low':-1.,'high':1.} for i in range(15)]
        self.hard_factors=[i==0 for i in range(15)]
        layout=QVBoxLayout(self); body=QHBoxLayout(); left=QVBoxLayout(); group=QGroupBox('Type of Design'); types=QVBoxLayout(group)
        choices=['2-level factorial (default generators)','2-level factorial (specify generators)',
                 '2-level split-plot (hard-to-change factors)','Plackett-Burman design','General full factorial design']
        for index,text in enumerate(choices):
            radio=QRadioButton(text); radio.setChecked(index==0)
            types.addWidget(radio); self.design_types.append(radio)
        left.addWidget(group); form=QFormLayout(); self.factor_count=QComboBox(); self.factor_count.addItems([str(i) for i in range(2,16)])
        form.addRow('Number of factors:',self.factor_count); left.addLayout(form); left.addStretch(); body.addLayout(left,3)
        right=QVBoxLayout()
        for title,callback in [('Display Available Designs…',self.available),('Designs…',self.designs),('Factors…',self.factor_settings),('Options…',self.options),('Results…',self.results)]:
            button=QPushButton(title); button.setAutoDefault(False); button.clicked.connect(lambda checked=False, action=callback:self.setup_design(action)); right.addWidget(button)
        right.addStretch(); body.addLayout(right,1); layout.addLayout(body)
        note=QLabel('Full or regular fractional 2-level designs, Plackett–Burman screening, or general factorial designs.\nFor screening and general factorial designs, setup opens the design planner with a calculated preview.'); note.setObjectName('secondary'); layout.addWidget(note)
        self.error=QLabel(); self.error.setObjectName('error'); self.error.setWordWrap(True); layout.addWidget(self.error)
        buttons(self,layout,self.validate)
        for radio in self.design_types:radio.toggled.connect(self.catalog_selection_changed)

    def catalog_selection_changed(self):
        kind=self.catalog_kind()
        self.factor_count.setEnabled(kind is None)
        if kind is None:
            count=min(int(self.factor_count.currentText()),15)
            self.factor_count.clear();self.factor_count.addItems([str(i) for i in range(2,16)])
            self.factor_count.setCurrentText(str(count))

    def catalog_kind(self):
        if self.design_types[3].isChecked(): return 'plackett_burman'
        if self.design_types[4].isChecked(): return 'general_factorial'
        return None

    def is_split_plot(self):
        return self.design_types[2].isChecked()

    def setup_design(self,action):
        if self.catalog_kind(): self.configure_catalog()
        else: action()

    def configure_catalog(self):
        import copy
        from .doe_planner_dialog import DOEPlannerDialog
        kind=self.catalog_kind()
        dialog=DOEPlannerDialog(self)
        dialog.family.setCurrentIndex(dialog.family.findData(kind))
        dialog.family.setEnabled(False); dialog.goal.setEnabled(False)
        dialog.create_button.setText('OK')
        previous=self.catalog_parameters.get(kind)
        factors=previous['factors'] if previous else [dict(name=f['name'],kind='number',levels=[f['low'],f['high']]) for f in self.factors[:int(self.factor_count.currentText())]]
        dialog.factor_count.setValue(len(factors))
        for row,factor in enumerate(factors):
            dialog.factor_table.item(row,0).setText(factor['name'])
            control=dialog.factor_table.cellWidget(row,1)
            control.setCurrentIndex(control.findData(factor['kind']))
            dialog.factor_table.item(row,2).setText(', '.join(map(str,factor['levels'])))
        if previous:
            for key in ('replicates','centers','blocks','seed'):getattr(dialog,key).setValue(previous[key])
            dialog.randomize.setChecked(previous['randomize']);dialog.name_edit.setText(previous['name'])
            dialog.pb_runs.setCurrentIndex(dialog.pb_runs.findData(previous['options'].get('runs',0)))
        dialog.refresh_preview()
        accepted=dialog.exec()==QDialog.DialogCode.Accepted
        if accepted:
            self.catalog_parameters[kind]=copy.deepcopy(dialog.parameters)
            count=str(len(dialog.parameters['factors']))
            if self.factor_count.findText(count)<0:self.factor_count.addItem(count)
            self.factor_count.setCurrentText(count)
        dialog.preview_timer.stop();dialog.deleteLater()
        return accepted

    def available(self):
        dialog=QDialog(self); dialog.setWindowTitle('Available Factorial Designs'); layout=QVBoxLayout(dialog)
        from .fractional import default_designs
        rows = [(k, runs, resolution) for k in range(2, 16)
                for runs, resolution, _ in default_designs(k)]
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(['Factors', 'Corner runs per replicate', 'Unblocked resolution'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, (factors, runs, resolution) in enumerate(rows):
            for col, value in enumerate((factors, runs, resolution or 'Full')):
                table.setItem(row, col, QTableWidgetItem(str(value)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table); buttons(dialog,layout); dialog.exec()

    def designs(self):
        dialog=QDialog(self); dialog.setWindowTitle('Create Factorial Design: Designs'); layout=QVBoxLayout(dialog)
        table=QTableWidget(1,4); table.setHorizontalHeaderLabels(['Design','Corner runs','Unblocked resolution','2^(k-p)'])
        k=int(self.factor_count.currentText())
        def summary():
            values=('Full factorial',str(2**k),'Full',f'2^{k}')
            if self.design_types[1].isChecked():
                try:
                    from .fractional import alias_structure
                    structure=alias_structure(self.generators,k); p=len(structure['generators'])
                    values=('Regular fraction',str(2**(k-p)),str(structure['resolution']),f'2^({k}-{p})')
                except (ValueError,TypeError):values=('Specify generators','—','—','—')
            for col,value in enumerate(values):table.setItem(0,col,QTableWidgetItem(value))
        from .fractional import default_designs
        choices = default_designs(k) if self.design_types[0].isChecked() else []
        if choices:
            table.setRowCount(len(choices))
            for row, (runs, resolution, generators) in enumerate(choices):
                p = len(generators)
                for col, value in enumerate(('Regular fraction' if p else 'Full factorial', runs,
                                             resolution or 'Full', f'2^({k}-{p})' if p else f'2^{k}')):
                    table.setItem(row, col, QTableWidgetItem(str(value)))
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setCurrentCell(next((i for i, design in enumerate(choices)
                                      if design[0] == self.default_runs_by_factor.get(k)), 0), 0)
        else:
            summary()
            table.selectRow(0)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setMaximumHeight(160)
        layout.addWidget(table); form=QFormLayout()
        if self.design_types[1].isChecked():
            generator_button=QPushButton('Generators…'); generator_button.setAutoDefault(False)
            generator_button.clicked.connect(lambda:(self.generator_settings(dialog),summary(),update_blocks())); layout.addWidget(generator_button)
        centers=QSpinBox(); centers.setRange(0,20); centers.setValue(self.centers)
        reps=QSpinBox(); reps.setRange(1,20); reps.setValue(self.replicates)
        block=QComboBox()
        def update_blocks():
            k_val=int(self.factor_count.currentText())
            r=reps.value()
            selected = choices[table.currentRow()] if choices else None
            corner_runs = (selected[0] if selected else 2**k_val) * r
            if self.design_types[1].isChecked():
                try:
                    from .fractional import alias_structure
                    structure=alias_structure(self.generators,k_val); p=len(structure['generators'])
                    corner_runs=2**(k_val-p) * r
                except Exception:
                    pass
            options=[1]
            if r>1:
                for d in range(2,r+1):
                    if r%d==0 and d not in options: options.append(d)
            for p2 in (() if selected and selected[2] else (2,4,8,16,32)):
                if corner_runs%p2==0 and (corner_runs//p2)>=2 and p2 not in options:
                    options.append(p2)
            options.sort()
            cur=block.currentText()
            block.clear()
            for opt in options: block.addItem(str(opt))
            if cur and cur in [str(o) for o in options]: block.setCurrentText(cur)
            elif str(self.blocks) in [str(o) for o in options]: block.setCurrentText(str(self.blocks))
            elif r>1 and str(r) in [str(o) for o in options]: block.setCurrentText(str(r))
            else: block.setCurrentIndex(0)
        reps.valueChanged.connect(lambda _:update_blocks())
        if choices: table.currentCellChanged.connect(lambda *_:update_blocks())
        update_blocks()
        form.addRow('Number of center points per block:',centers); form.addRow('Number of replicates for corner points:',reps); form.addRow('Number of blocks:',block)
        layout.addLayout(form); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.centers=centers.value(); self.replicates=reps.value(); self.blocks=int(block.currentText())
            if choices: self.default_runs_by_factor[k] = choices[table.currentRow()][0]

    def generator_settings(self,parent=None):
        dialog=QDialog(parent or self); dialog.setWindowTitle('Create Factorial Design: Generators'); dialog.setMinimumWidth(560)
        layout=QVBoxLayout(dialog); k=int(self.factor_count.currentText())
        layout.addWidget(QLabel('Enter products of base-factor letters, for example D = ABC.\nLeave base factors blank. Use a leading minus for the alternate fraction.'))
        table=QTableWidget(k,3); self.generator_table=table; table.setHorizontalHeaderLabels(['Factor','Name','Generator'])
        for row in range(k):
            letter=chr(65+row)
            for col,value in enumerate((letter,self.factors[row]['name'],self.generators.get(letter,''))):
                item=QTableWidgetItem(value)
                if col<2:item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row,col,item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(table)
        error=QLabel(); error.setObjectName('error'); error.setWordWrap(True); layout.addWidget(error)
        def accept():
            dialog.setFocus(); QApplication.processEvents()
            try:
                values={chr(65+r):table.item(r,2).text().strip() for r in range(k) if table.item(r,2).text().strip()}
                from .fractional import alias_structure
                structure=alias_structure(values,k)
            except (ValueError,TypeError) as exc:error.setText(str(exc)); return
            self.generators=structure['generators']; dialog.accept()
        buttons(dialog,layout,accept); dialog.exec()

    def factor_settings(self):
        dialog=QDialog(self); dialog.setWindowTitle('Create Factorial Design: Factors'); dialog.setMinimumWidth(640)
        split_plot=self.is_split_plot()
        layout=QVBoxLayout(dialog); count=int(self.factor_count.currentText()); self.factor_table=QTableWidget(count,5 if split_plot else 4)
        self.factor_table.setHorizontalHeaderLabels(['Name','Type','Low','High','Hard to change'] if split_plot else ['Name','Type','Low','High'])
        for row,factor in enumerate(self.factors[:count]):
            for col,value in enumerate((factor['name'],'Continuous',factor['low'],factor['high'])):
                item=QTableWidgetItem(str(value))
                if col==1: item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
                self.factor_table.setItem(row,col,item)
            if split_plot:
                combo=QComboBox(); combo.addItems(['Yes (Whole-Plot)','No (Subplot)'])
                combo.setCurrentIndex(0 if self.hard_factors[row] else 1)
                self.factor_table.setCellWidget(row,4,combo)
        self.factor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); layout.addWidget(self.factor_table)
        error=QLabel(); error.setObjectName('error'); layout.addWidget(error)
        def accept():
            dialog.setFocus(); QApplication.processEvents()
            try:
                factors=[dict(name=self.factor_table.item(r,0).text().strip(),low=finite_number(float(self.factor_table.item(r,2).text())),high=finite_number(float(self.factor_table.item(r,3).text()))) for r in range(count)]
                if split_plot:
                    hard_flags=[self.factor_table.cellWidget(r,4).currentIndex()==0 for r in range(count)]
                    hard=[f for f,flag in zip(factors,hard_flags) if flag]
                    easy=[f for f,flag in zip(factors,hard_flags) if not flag]
                    from .doe_split_plot import create_split_plot_design
                    create_split_plot_design(hard,easy,replicates=self.replicates,seed=self.seed,randomize=False)
                else:
                    from .doe import create_factorial
                    create_factorial(factors,randomize=False)
            except (ValueError,TypeError) as exc: error.setText(str(exc)); return
            self.factors[:count]=factors
            if split_plot: self.hard_factors[:count]=[self.factor_table.cellWidget(r,4).currentIndex()==0 for r in range(count)]
            dialog.accept()
        buttons(dialog,layout,accept); dialog.exec()

    def options(self):
        dialog=QDialog(self); dialog.setWindowTitle('Create Factorial Design: Options'); layout=QVBoxLayout(dialog)
        fold=QGroupBox('Fold Design'); group=QVBoxLayout(fold)
        for i,text in enumerate(('Do not fold','Fold on all factors','Fold just on factor:')):
            radio=QRadioButton(text); radio.setChecked(i==0); radio.setEnabled(i==0); group.addWidget(radio)
        layout.addWidget(fold)
        randomize=QCheckBox('Randomize runs'); randomize.setChecked(self.randomize); layout.addWidget(randomize)
        form=QFormLayout(); seed=QLineEdit(str(self.seed)); form.addRow('Base for random data generator:',seed); layout.addLayout(form)
        store=QCheckBox('Store design in worksheet'); store.setChecked(True); store.setEnabled(False); layout.addWidget(store)
        error=QLabel(); error.setObjectName('error'); layout.addWidget(error)
        def accept():
            try:
                value=int(seed.text())
                if not -(2**63)<=value<2**63: raise ValueError('Seed is outside the supported range.')
            except ValueError as exc: error.setText(str(exc)); return
            self.seed=value; self.randomize=randomize.isChecked(); dialog.accept()
        buttons(dialog,layout,accept); dialog.exec()

    def results(self):
        dialog=QDialog(self); dialog.setWindowTitle('Create Factorial Design: Results'); layout=QVBoxLayout(dialog)
        summary=QCheckBox('Design summary'); summary.setChecked(self.summary); layout.addWidget(summary); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted: self.summary=summary.isChecked()

    def validate(self):
        try:
            kind=self.catalog_kind()
            if kind:
                import copy
                if kind not in self.catalog_parameters and not self.configure_catalog():return
                self.parameters=copy.deepcopy(self.catalog_parameters[kind])
                from .doe_planner import build_plan
                build_plan(**self.parameters)
                self.accept();return
            if self.is_split_plot():
                count=int(self.factor_count.currentText())
                selected_factors=self.factors[:count]
                flags=self.hard_factors[:count]
                hard=[dict(f) for f,flag in zip(selected_factors,flags) if flag]
                easy=[dict(f) for f,flag in zip(selected_factors,flags) if not flag]
                from .doe_split_plot import create_split_plot_design
                create_split_plot_design(hard,easy,replicates=self.replicates,seed=self.seed,randomize=self.randomize)
                self.parameters=dict(hard_factors=hard,easy_factors=easy,replicates=self.replicates,seed=self.seed,randomize=self.randomize)
                self.accept(); return
            self.parameters=dict(factors=self.factors[:int(self.factor_count.currentText())],replicates=self.replicates,centers=self.centers,blocks=self.blocks,randomize=self.randomize,seed=self.seed)
            if self.design_types[1].isChecked():
                generators = self.generators
            else:
                from .fractional import default_designs
                count = len(self.parameters['factors'])
                choices = default_designs(count)
                selected_runs = self.default_runs_by_factor.get(count, choices[0][0])
                generators = next(g for runs, _, g in choices if runs == selected_runs)
                if generators and self.replicates % self.blocks:
                    raise ValueError('For a default fraction, choose a block count that divides the number of replicates.')
            if generators or self.design_types[1].isChecked():
                from .fractional import create_fractional
                self.parameters['generators'] = dict(generators)
                create_fractional(**self.parameters)
            else:
                from .doe import create_factorial
                create_factorial(**self.parameters)
        except (ValueError,TypeError) as exc: self.error.setText(str(exc)); return
        self.accept()


class AnalyzeFactorialDialog(QDialog):
    def __init__(self,parent,worksheet):
        super().__init__(parent); self.setWindowTitle('Analyze Factorial Design'); self.setMinimumWidth(760)
        self.setSizeGripEnabled(True)
        self.worksheet=worksheet; self.parameters=None; self.max_order=2; self.confidence=.95
        self.selected_terms=None; self.include_blocks=None
        if worksheet.metadata.get('doe',{}).get('schema')=='statcraft-regular-fractional-v1':self.max_order=1
        self.plot_residuals=True; self.show_factor_coding=True
        factors=worksheet.metadata.get('doe',{}).get('factors',[])
        self.factor_indices=[f['column_index'] for f in factors if isinstance(f,dict) and type(f.get('column_index')) is int]
        layout=QVBoxLayout(self); body=QHBoxLayout(); left=QVBoxLayout(); self.available=QListWidget()
        for i,column in enumerate(worksheet.columns):
            if column.kind=='number':
                item=QListWidgetItem('C'+str(i+1)+'   '+column.name); item.setData(Qt.ItemDataRole.UserRole,i); self.available.addItem(item)
        left.addWidget(self.available); select=QPushButton('Select'); select.setAutoDefault(False); select.clicked.connect(self.transfer)
        self.available.itemDoubleClicked.connect(lambda item:self.transfer()); left.addWidget(select); body.addLayout(left,1)
        right=QVBoxLayout(); right.addWidget(QLabel('Responses:')); self.response=QLineEdit(); right.addWidget(self.response)
        grid=QGridLayout()
        for i,(title,callback) in enumerate((('Terms…',self.terms),('Covariates…',None),('Options…',self.options),('Stepwise…',None),('Graphs…',self.graphs),('Results…',self.results),('Storage…',None))):
            button=QPushButton(title); button.setAutoDefault(False); button.setEnabled(callback is not None)
            if callback: button.clicked.connect(callback)
            grid.addWidget(button,i//4,i%4)
        right.addLayout(grid); self.terms_note=QLabel(); self.terms_note.setWordWrap(True); right.addWidget(self.terms_note); right.addStretch()
        body.addLayout(right,2); layout.addLayout(body); self.update_terms_note()
        self.error=QLabel(); self.error.setObjectName('error'); self.error.setWordWrap(True); layout.addWidget(self.error); buttons(self,layout,self.validate)

    def transfer(self):
        item=self.available.currentItem()
        if item: self.response.setText('C'+str(item.data(Qt.ItemDataRole.UserRole)+1)); self.response.setFocus()

    def update_terms_note(self):
        names=[self.worksheet.columns[i].name for i in self.factor_indices if 0<=i<len(self.worksheet.columns)]
        model=('Hierarchical terms through order '+str(self.max_order)) if self.selected_terms is None else str(len(self.selected_terms))+' selected model terms'
        if self.include_blocks: model+=' + Blocks'
        self.terms_note.setText('Factors: '+(', '.join(names) or 'Select factors in Terms…')+'\n'+model)

    def terms(self):
        from .doe_terms_dialog import FactorialTermsDialog
        dialog=FactorialTermsDialog(self,self.worksheet,self.factor_indices,self.max_order,self.selected_terms,self.include_blocks)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.factor_indices=dialog.factor_indices; self.max_order=dialog.max_order; self.selected_terms=dialog.selected_terms
            self.include_blocks=dialog.include_blocks.isChecked()
            self.update_terms_note()

    def options(self):
        dialog=ProcedureDialog(self,'Analyze Factorial Design: Options',self.worksheet,[],
            [{'key':'confidence','label':'Confidence level (0–1)','numeric':True,'default':self.confidence}],
            'Coded-unit least squares with an intercept. No weighting, stepwise selection or Box-Cox transformation.')
        if dialog.exec()==QDialog.DialogCode.Accepted: self.confidence=dialog.parameters['confidence']

    def graphs(self):
        dialog=QDialog(self); dialog.setWindowTitle('Analyze Factorial Design: Graphs'); layout=QVBoxLayout(dialog)
        plot=QCheckBox('Residuals versus fits'); plot.setChecked(self.plot_residuals); layout.addWidget(plot); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted: self.plot_residuals=plot.isChecked()

    def results(self):
        dialog=QDialog(self); dialog.setWindowTitle('Analyze Factorial Design: Results'); layout=QVBoxLayout(dialog)
        coding=QCheckBox('Factor coding table'); coding.setChecked(self.show_factor_coding); layout.addWidget(coding)
        layout.addWidget(QLabel('Model summary, ANOVA, coefficients and effects are included.')); buttons(dialog,layout)
        if dialog.exec()==QDialog.DialogCode.Accepted: self.show_factor_coding=coding.isChecked()

    def validate(self):
        try:
            responses=resolve_variables(self.response.text(),self.worksheet)
            if len(responses)!=1: raise ValueError('Select one response column.')
            parameters=dict(response_index=responses[0],factor_indices=self.factor_indices,max_order=self.max_order,confidence=self.confidence)
            if self.include_blocks is not None: parameters['include_blocks']=self.include_blocks
            if self.selected_terms is not None:parameters['selected_terms']=self.selected_terms
            from .doe import analyze_factorial
            analyze_factorial(self.worksheet,**parameters)
            self.parameters=dict(**parameters,plot_residuals=self.plot_residuals,show_factor_coding=self.show_factor_coding)
        except (ValueError,TypeError) as exc: self.error.setText(str(exc)); return
        self.accept()
