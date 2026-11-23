import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('STATCRAFT_TESTING', '1')

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from scipy.stats import norm

from statcraft.app import Presenter
from statcraft.model import Column, Worksheet
from statcraft.modern_app import ModernWindow
from statcraft.r_verification import build_script as build_r_script
from statcraft.xlsx_verification import supports, write_verification


class _NAValue:
    pass


_NA = _NAValue()


class ExcelFormulaEvaluator:
    """Lightweight recursive Excel formula evaluator for independent workbook verification."""

    def __init__(self, workbook):
        self.wb = workbook
        self.cache = {}

    def invalidate(self):
        self.cache.clear()

    def _split_args(self, text):
        args, buf, depth, in_str = [], [], 0, False
        i = 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                in_str = not in_str
                buf.append(ch)
            elif not in_str:
                if ch == '(':
                    depth += 1
                    buf.append(ch)
                elif ch == ')':
                    depth -= 1
                    buf.append(ch)
                elif ch == ',' and depth == 0:
                    args.append(''.join(buf).strip())
                    buf = []
                else:
                    buf.append(ch)
            else:
                buf.append(ch)
            i += 1
        tail = ''.join(buf).strip()
        if tail or args:
            args.append(tail)
        return args

    def _parse_ref(self, default_sheet, ref_str):
        ref_str = ref_str.strip()
        if '!' in ref_str:
            sname, coord = ref_str.split('!', 1)
            sname = sname.strip("'")
        else:
            sname, coord = default_sheet, ref_str
        coord = coord.replace('$', '')
        m = re.fullmatch(r'([A-Z]+)(\d+)', coord)
        if not m:
            raise ValueError(f'Bad ref: {ref_str}')
        return sname, column_index_from_string(m.group(1)), int(m.group(2))

    def _expand_range(self, default_sheet, rng_str):
        left, right = rng_str.split(':', 1)
        s1, c1, r1 = self._parse_ref(default_sheet, left)
        _, c2, r2 = self._parse_ref(default_sheet, right)
        vals = []
        for r in range(min(r1, r2), max(r1, r2) + 1):
            for c in range(min(c1, c2), max(c1, c2) + 1):
                vals.append(self.cell(s1, f'{get_column_letter(c)}{r}'))
        return vals

    def _expand_range_2d(self, default_sheet, rng_str):
        left, right = rng_str.split(':', 1)
        s1, c1, r1 = self._parse_ref(default_sheet, left)
        _, c2, r2 = self._parse_ref(default_sheet, right)
        rows = []
        for r in range(min(r1, r2), max(r1, r2) + 1):
            rows.append([self.cell(s1, f'{get_column_letter(c)}{r}') for c in range(min(c1, c2), max(c1, c2) + 1)])
        return rows

    def _is_num(self, v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

    def _nums(self, vals):
        out = []
        for v in vals:
            if v is _NA:
                return None
            if self._is_num(v):
                out.append(float(v))
        return out

    def _matches_crit(self, val, crit):
        if isinstance(crit, str):
            for op in ('<=', '>=', '<>', '<', '>'):
                if crit.startswith(op):
                    rhs_raw = crit[len(op):]
                    try:
                        rhs = float(rhs_raw)
                    except ValueError:
                        rhs = rhs_raw
                    if val is None or val == '' or isinstance(val, bool) or val is _NA:
                        return op == '<>' and rhs == ''
                    if isinstance(rhs, float) and self._is_num(val):
                        v = float(val)
                        return {'<=': v <= rhs, '>=': v >= rhs, '<>': v != rhs, '<': v < rhs, '>': v > rhs}[op]
                    return str(val) != str(rhs) if op == '<>' else False
        if isinstance(crit, bool):
            return val is crit
        if self._is_num(crit) and self._is_num(val):
            return float(val) == float(crit)
        return val == crit

    def cell(self, sheet_name, coord):
        coord = coord.replace('$', '')
        key = (sheet_name, coord)
        if key in self.cache:
            return self.cache[key]
        raw = self.wb[sheet_name][coord].value
        if isinstance(raw, str) and raw.startswith('='):
            val = self._eval_expr(sheet_name, raw[1:])
        else:
            val = raw
        self.cache[key] = val
        return val

    def _eval_expr(self, sheet, expr):
        tokens = self._tokenize(expr.strip())
        pos = [0]

        def peek():
            return tokens[pos[0]] if pos[0] < len(tokens) else None

        def consume():
            tok = tokens[pos[0]]
            pos[0] += 1
            return tok

        def parse_cmp():
            left = parse_add()
            while peek() in ('=', '<>', '<', '>', '<=', '>='):
                op = consume()
                right = parse_add()
                if left is _NA or right is _NA:
                    left = _NA
                else:
                    if op == '=':
                        left = (float(left) == float(right)) if (self._is_num(left) and self._is_num(right)) else (left == right)
                    elif op == '<>':
                        left = (float(left) != float(right)) if (self._is_num(left) and self._is_num(right)) else (left != right)
                    elif op == '<':
                        left = float(left) < float(right)
                    elif op == '>':
                        left = float(left) > float(right)
                    elif op == '<=':
                        left = float(left) <= float(right)
                    elif op == '>=':
                        left = float(left) >= float(right)
            return left

        def parse_add():
            left = parse_mul()
            while peek() in ('+', '-', '&'):
                op = consume()
                right = parse_mul()
                if left is _NA or right is _NA:
                    left = _NA
                elif op == '&':
                    left = f'{left}{right}'
                elif op == '+':
                    left = float(left or 0.0) + float(right or 0.0)
                else:
                    left = float(left or 0.0) - float(right or 0.0)
            return left

        def parse_mul():
            left = parse_pow()
            while peek() in ('*', '/'):
                op = consume()
                right = parse_pow()
                if left is _NA or right is _NA:
                    left = _NA
                elif op == '*':
                    left = float(left or 0.0) * float(right or 0.0)
                else:
                    denom = float(right)
                    left = _NA if denom == 0 else float(left or 0.0) / denom
            return left

        def parse_pow():
            left = parse_unary()
            if peek() == '^':
                consume()
                right = parse_pow()
                if left is _NA or right is _NA:
                    return _NA
                return float(left) ** float(right)
            return left

        def parse_unary():
            if peek() in ('+', '-'):
                op = consume()
                val = parse_unary()
                if val is _NA:
                    return _NA
                return float(val) if op == '+' else -float(val)
            return parse_primary()

        def parse_primary():
            tok = peek()
            if tok == '(':
                consume()
                val = parse_cmp()
                if peek() == ')':
                    consume()
                return val
            consume()
            if tok.startswith('"') and tok.endswith('"'):
                return tok[1:-1]
            if tok.upper() == 'TRUE':
                return True
            if tok.upper() == 'FALSE':
                return False
            if re.fullmatch(r'[\d.]+(?:[eE][+-]?\d+)?', tok):
                return float(tok)
            if peek() == '(':
                # Function call
                consume()
                depth = 1
                inner_chars = []
                # Reconstruct raw inner arg string from remaining tokens
                raw_args = []
                cur = []
                while pos[0] < len(tokens):
                    t = consume()
                    if t == '(':
                        depth += 1
                        cur.append(t)
                    elif t == ')':
                        depth -= 1
                        if depth == 0:
                            if cur:
                                raw_args.append(cur)
                            break
                        cur.append(t)
                    elif t == ',' and depth == 1:
                        raw_args.append(cur)
                        cur = []
                    else:
                        cur.append(t)
                return self._call_func(sheet, tok.upper(), raw_args)
            if ':' in tok:
                return self._expand_range(sheet, tok)
            sname, c, r = self._parse_ref(sheet, tok)
            return self.cell(sname, f'{get_column_letter(c)}{r}')

        return parse_cmp()

    def _tokenize(self, expr):
        pattern = re.compile(
            r'"[^"]*"'
            r"|(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]+\$?\d+(?::(?:(?:'[^']+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Z]+\$?\d+)?"
            r'|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
            r'|[A-Za-z_][A-Za-z0-9_.]*'
            r'|<=|>=|<>|[+\-*/^&(),=<>]'
        )
        return pattern.findall(expr)

    def _eval_tokens(self, sheet, toks):
        if len(toks) == 1 and ':' in toks[0]:
            return self._expand_range(sheet, toks[0])
        return self._eval_expr(sheet, ' '.join(toks))

    def _call_func(self, sheet, name, raw_args):
        if name == 'NA':
            return _NA
        if name == 'IF':
            cond = self._eval_tokens(sheet, raw_args[0])
            if cond is _NA:
                return _NA
            branch = raw_args[1] if cond else (raw_args[2] if len(raw_args) > 2 else ['FALSE'])
            return self._eval_tokens(sheet, branch)
        if name == 'IFERROR':
            try:
                v = self._eval_tokens(sheet, raw_args[0])
                return self._eval_tokens(sheet, raw_args[1]) if v is _NA else v
            except Exception:
                return self._eval_tokens(sheet, raw_args[1])
        if name == 'AND':
            for arg in raw_args:
                v = self._eval_tokens(sheet, arg)
                if v is _NA:
                    return _NA
                if not v:
                    return False
            return True
        if name == 'OR':
            for arg in raw_args:
                v = self._eval_tokens(sheet, arg)
                if v is _NA:
                    return _NA
                if v:
                    return True
            return False
        if name == 'NOT':
            v = self._eval_tokens(sheet, raw_args[0])
            return _NA if v is _NA else (not bool(v))
        if name == 'ISNUMBER':
            v = self._eval_tokens(sheet, raw_args[0])
            return self._is_num(v)
        if name == 'ISBLANK':
            v = self._eval_tokens(sheet, raw_args[0])
            return v is None or v == ''
        if name == 'ROUND':
            v = self._eval_tokens(sheet, raw_args[0])
            d = int(self._eval_tokens(sheet, raw_args[1]))
            return _NA if v is _NA else round(float(v), d)
        if name in ('ABS', 'SQRT', 'EXP', 'LN', 'GAMMALN', 'NORMSDIST'):
            v = self._eval_tokens(sheet, raw_args[0])
            if v is _NA:
                return _NA
            fv = float(v)
            if name == 'ABS':
                return abs(fv)
            if name == 'SQRT':
                return _NA if fv < 0 else math.sqrt(fv)
            if name == 'EXP':
                return math.exp(fv)
            if name == 'LN':
                return _NA if fv <= 0 else math.log(fv)
            if name == 'GAMMALN':
                return _NA if fv <= 0 else math.lgamma(fv)
            return float(norm.cdf(fv))
        if name in ('COUNT', 'COUNTA', 'SUM', 'AVERAGE', 'MEDIAN', 'STDEV', 'VAR', 'MIN', 'MAX'):
            items = []
            for arg in raw_args:
                v = self._eval_tokens(sheet, arg)
                if isinstance(v, list):
                    items.extend(v)
                else:
                    items.append(v)
            if name == 'COUNTA':
                return sum(1 for x in items if x is not None and x != '')
            if name == 'COUNT':
                return sum(1 for x in items if self._is_num(x))
            nums = self._nums(items)
            if nums is None:
                return _NA
            if name == 'SUM':
                return sum(nums)
            if not nums:
                return _NA
            if name == 'AVERAGE':
                return statistics.fmean(nums)
            if name == 'MEDIAN':
                return statistics.median(nums)
            if name == 'MIN':
                return min(nums)
            if name == 'MAX':
                return max(nums)
            if len(nums) < 2:
                return _NA
            if name == 'STDEV':
                return statistics.stdev(nums)
            return statistics.variance(nums)
        if name == 'COUNTIF':
            rng = self._eval_tokens(sheet, raw_args[0])
            crit = self._eval_tokens(sheet, raw_args[1])
            return sum(1 for v in rng if self._matches_crit(v, crit))
        if name == 'COUNTIFS':
            pairs = []
            for i in range(0, len(raw_args), 2):
                rng = self._eval_tokens(sheet, raw_args[i])
                crit = self._eval_tokens(sheet, raw_args[i + 1])
                pairs.append((rng, crit))
            n_items = len(pairs[0][0])
            return sum(
                1 for idx in range(n_items)
                if all(self._matches_crit(rng[idx], crit) for rng, crit in pairs)
            )
        if name == 'VLOOKUP':
            key = self._eval_tokens(sheet, raw_args[0])
            table = self._expand_range_2d(sheet, raw_args[1][0])
            col_idx = int(self._eval_tokens(sheet, raw_args[2])) - 1
            for row in table:
                if row[0] == key or (self._is_num(row[0]) and self._is_num(key) and float(row[0]) == float(key)):
                    return row[col_idx]
            return _NA
        raise NotImplementedError(f'Unsupported Excel function in test evaluator: {name}')


class QualityExcelVerificationTests(unittest.TestCase):
    def _assert_axis_readable(self, axis, check_gridlines=False):
        self.assertIs(axis.delete, False)
        self.assertEqual(axis.tickLblPos, 'low')
        self.assertEqual(axis.majorTickMark, 'out')
        if check_gridlines:
            self.assertEqual(axis.majorGridlines.spPr.line.solidFill.srgbClr, 'DFE5EC')

    def _assert_r_matches_workbook(self, presenter, entry):
        exe = os.environ.get('STATCRAFT_QA_RSCRIPT') or shutil.which('Rscript')
        if not exe:
            return
        script = build_r_script(presenter, entry)
        with tempfile.TemporaryDirectory() as tmp:
            sf = Path(tmp) / 'check.R'
            sf.write_text(script, encoding='utf-8')
            proc = subprocess.run([exe, '--vanilla', str(sf)], cwd=tmp, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('Verification: PASS', proc.stdout)

    def test_imr_workbook_formulas_charts_edits_and_invalid_inputs(self):
        p = Presenter()
        vals = [10.0, 10.4, None, 10.2, 10.8, 10.1, 10.6, 10.3, 18.0, 10.2, 10.5]
        p.worksheet = Worksheet('IMR_Excel', [Column('Reading', 'number', vals)])
        entry = p.imr_chart({
            'variables': [0],
            'options': {'span': 3, 'omit_subgroups': '5', 'k_sigma': 2.5},
        })
        self.assertTrue(supports(entry))
        self._assert_r_matches_workbook(p, entry)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'imr.xlsx'
            write_verification(path, p, entry)
            wb = load_workbook(path)
            self.assertEqual(wb.sheetnames, ['Verification', 'Inputs', 'Calculations'])
            ev = ExcelFormulaEvaluator(wb)
            self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')
            self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')

            # Check charts and axis styling
            charts = wb['Verification']._charts
            self.assertEqual(len(charts), 2)
            for ch in charts:
                self.assertEqual(ch.x_axis.axPos, 'b')
                self._assert_axis_readable(ch.x_axis, check_gridlines=False)
                self._assert_axis_readable(ch.y_axis, check_gridlines=True)
            self.assertEqual(charts[0].series[0].val.numRef.f, "'Calculations'!$C$2:$C$12")
            self.assertEqual(charts[1].series[0].val.numRef.f, "'Calculations'!$E$2:$E$12")

            # Missing row 3 breaks span-3 moving range without bridging
            self.assertIs(_NA, ev.cell('Calculations', 'E4'))
            self.assertIs(_NA, ev.cell('Calculations', 'E5'))
            self.assertIs(_NA, ev.cell('Calculations', 'E6'))

            # Edit blue input cell -> recalculates and flags DIFFERENCES FOUND
            orig = wb['Inputs']['D2'].value
            wb['Inputs']['D2'].value = 15.0
            ev.invalidate()
            self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')
            self.assertEqual(ev.cell('Verification', 'B6'), 'DIFFERENCES FOUND')

            # Restore -> returns to PASS
            wb['Inputs']['D2'].value = orig
            ev.invalidate()
            self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')

            # Clear retained numeric cell -> Check inputs
            wb['Inputs']['D2'].value = None
            ev.invalidate()
            self.assertEqual(ev.cell('Verification', 'B7'), 'Check inputs')
            self.assertEqual(ev.cell('Verification', 'B6'), 'Check inputs')

    def test_xbar_r_unequal_subgroups_and_unstacked_workbooks(self):
        groups = [
            [10.0, 10.2, 9.8, 10.0],
            [10.1, 9.9, 10.0],
            [10.0, 10.3, 9.7, 10.1, 9.9],
            [16.0, 17.0],
            [10.2, 9.8, 10.1, 9.9],
        ]
        flat = [v for g in groups for v in g]
        lots = [f'Lot{i + 1}' for i, g in enumerate(groups) for _ in g]
        p = Presenter()
        p.worksheet = Worksheet('XbarR_Excel', [
            Column('Diameter', 'number', flat),
            Column('Lot', 'text', lots),
            Column('S1', 'number', [10.0, 10.1, 10.2, 16.0, 10.1]),
            Column('S2', 'number', [10.2, 9.9, 9.8, 17.0, 9.9]),
            Column('S3', 'number', [9.8, None, 10.0, None, 10.0]),
        ])
        xr = p.subgroup_control_chart(
            chart_type='xbar_r',
            stacked=True,
            response_index=0,
            factor_index=1,
            options={'k_sigma': 2.5, 'omit_subgroups': [4]},
        )
        xr_rows = p.subgroup_control_chart(chart_type='xbar_r', stacked=False, indices=[2, 3, 4])
        xs = p.subgroup_control_chart(chart_type='xbar_s', stacked=True, response_index=0, factor_index=1)
        x_only = p.subgroup_control_chart(chart_type='xbar', stacked=True, response_index=0, factor_index=1)
        self.assertTrue(supports(xr))
        self.assertTrue(supports(xr_rows))
        self.assertTrue(supports(xs))
        self.assertFalse(supports(x_only))
        self._assert_r_matches_workbook(p, xr)

        with tempfile.TemporaryDirectory() as tmp:
            for name, entry, edit_cell in (
                ('xr_stacked.xlsx', xr, 'E2'),
                ('xr_unstacked.xlsx', xr_rows, 'D2'),
            ):
                path = Path(tmp) / name
                write_verification(path, p, entry)
                wb = load_workbook(path)
                ev = ExcelFormulaEvaluator(wb)
                self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')
                self.assertEqual(len(wb['Verification']._charts), 2)
                for ch in wb['Verification']._charts:
                    self.assertEqual(ch.x_axis.axPos, 'b')
                    self._assert_axis_readable(ch.x_axis, check_gridlines=False)
                    self._assert_axis_readable(ch.y_axis, check_gridlines=True)

                orig = wb['Inputs'][edit_cell].value
                wb['Inputs'][edit_cell].value = 14.5
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'DIFFERENCES FOUND')
                wb['Inputs'][edit_cell].value = orig
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')
                wb['Inputs'][edit_cell].value = None
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B7'), 'Check inputs')

    def test_normal_capability_subgroups_individuals_mpx_and_ui_menu(self):
        subgroups = [
            [-0.4, -0.1, 0.2, 0.3],
            [-0.2, 0.1, 0.3],
            [-0.5, -0.2, 0.0, 0.2, 0.5],
            [-0.3, 0.0, 0.1, 0.2],
        ]
        flat = [v for g in subgroups for v in g]
        batch = [f'B{i + 1}' for i, g in enumerate(subgroups) for _ in g]
        p = Presenter()
        p.worksheet = Worksheet('CapExcel', [
            Column('Offset', 'number', flat),
            Column('Batch', 'text', batch),
        ])
        cap_pooled = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 'Batch',
            'lsl': -3.0,
            'usl': 3.0,
            'options': {'target': 0.0, 'estimate_method_gt1': 'pooled', 'unbiased_within': True},
        })
        cap_rbar = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 'Batch',
            'lsl': -3.0,
            'usl': 3.0,
            'options': {'estimate_method_gt1': 'rbar', 'display_unit': 'percent'},
        })
        cap_ind = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 1,
            'lsl': None,
            'usl': 2.5,
            'options': {'estimate_method_eq1': 'amr', 'moving_range_len': 3, 'unbiased_overall': True},
        })
        cap_bw = p.normal_capability(settings={
            'single_column': True,
            'column_name': 'Offset',
            'subgroup_spec': 'Batch',
            'analysis_mode': 'between_within',
            'lsl': -3.0,
            'usl': 3.0,
        })
        self.assertTrue(supports(cap_pooled))
        self.assertFalse(supports(cap_bw))
        self._assert_r_matches_workbook(p, cap_pooled)

        with tempfile.TemporaryDirectory() as tmp:
            for fname, cap in (('pooled.xlsx', cap_pooled), ('rbar.xlsx', cap_rbar), ('ind.xlsx', cap_ind)):
                wb = load_workbook(write_verification(Path(tmp) / fname, p, cap))
                ev = ExcelFormulaEvaluator(wb)
                self.assertEqual(ev.cell('Verification', 'B7'), 'Valid')
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')
                self.assertEqual(sum(ev.cell('Calculations', f'Y{r}') for r in range(2, 12)), cap['result']['sample_n'])
                charts = wb['Verification']._charts
                self.assertEqual(len(charts), 2)
                self.assertEqual(charts[0].x_axis.axPos, 'b')
                self.assertEqual(charts[1].y_axis.axPos, 'b')
                self._assert_axis_readable(charts[0].x_axis, check_gridlines=False)
                self._assert_axis_readable(charts[0].y_axis, check_gridlines=True)
                self._assert_axis_readable(charts[1].x_axis, check_gridlines=False)
                self._assert_axis_readable(charts[1].y_axis, check_gridlines=True)

                # Edit input -> updates formulas and histogram total remains sample_n
                orig = wb['Inputs']['D2'].value
                wb['Inputs']['D2'].value = 2.0
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'DIFFERENCES FOUND')
                self.assertEqual(sum(ev.cell('Calculations', f'Y{r}') for r in range(2, 12)), cap['result']['sample_n'])
                wb['Inputs']['D2'].value = orig
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B6'), 'PASS')

                # Constant values -> Check inputs
                for row in range(2, cap['result']['sample_n'] + 2):
                    wb['Inputs'][f'D{row}'].value = 1.0
                ev.invalidate()
                self.assertEqual(ev.cell('Verification', 'B7'), 'Check inputs')

            # MPX roundtrip + stale rejection + UI context menu cancel & export
            mpx_path = Path(tmp) / 'cap_excel.mpx'
            p.save(mpx_path)
            reopened = Presenter()
            reopened.load(mpx_path)
            saved = next(e for e in reopened.history if e['entry_id'] == cap_pooled['entry_id'])
            app = QApplication.instance() or QApplication([])
            win = ModernWindow(reopened)
            try:
                out_path = Path(tmp) / 'from_menu.xlsx'
                action = next(
                    a for a in win.build_output_context_menu(saved).actions()
                    if a.text().startswith('Export Excel Verification')
                )
                with patch.object(QFileDialog, 'getSaveFileName', return_value=('', '')):
                    action.trigger()
                self.assertFalse(out_path.exists())
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out_path), '')):
                    action.trigger()
                self.assertTrue(out_path.is_file())

                reopened.worksheet.columns[0].values[0] = 5.0
                with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(out_path), '')), \
                     patch.object(QMessageBox, 'warning') as warning:
                    action.trigger()
                self.assertIn('Rerun', warning.call_args.args[2])
            finally:
                reopened.dirty = False
                win.close()
                win.deleteLater()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
