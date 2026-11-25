"""Export saved StatCraft analyses as formula-driven Excel verification workbooks."""
import math
import os
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.formula import ArrayFormula

from .capability_engine import d2 as _cap_d2, d4 as _cap_d4
from .engine import normalize_numeric
from .r_verification import (
    _extract_attribute_rows,
    _extract_capability_rows,
    _extract_subgroup_rows,
    _normalize_imr_values,
)
from .subgroup_control import c4 as _sub_c4, c5 as _sub_c5, d2 as _sub_d2, d3 as _sub_d3

_FACTORIAL = {'analyze_factorial', 'analyze_factorial_terms'}
_NUMBER = '0.000000E+00'
_NAVY = '193354'
_EDITABLE_FONT = Font(color='175AD3')


def supports(entry):
    if not isinstance(entry, dict):
        return False
    recipe = entry.get('recipe', {})
    params = recipe.get('parameters', {})
    action = recipe.get('action')
    result = entry.get('result', {})
    if action in _FACTORIAL:
        return True
    if action == 'multiple_regression':
        return not params.get('categorical_indices') and not params.get('model_terms')
    if action == 'imr_chart':
        return result.get('analysis') == 'imr_control'
    if action == 'subgroup_control_chart':
        return params.get('chart_type', result.get('chart_type', 'xbar_r')) in ('xbar_r', 'xbar_s')
    if action == 'attribute_control_chart':
        chart_type = str(result.get('chart_type', result.get('chart', params.get('settings', {}).get('chart_type', '')))).upper().strip().replace('′', "'")
        return result.get('analysis') == 'attribute_control' and chart_type in ('P', 'NP', 'C', 'U')
    if action == 'normal_capability':
        return result.get('analysis') == 'capability' and result.get('analysis_mode', 'normal') == 'normal'
    if action == 'gage_rr':
        return result.get('analysis') == 'gage_rr'
    return False


def _style_chart_axis(axis):
    axis.delete = False
    axis.majorTickMark = 'out'
    axis.tickLblPos = 'low'
    if hasattr(axis, 'numFmt'):
        axis.numFmt = 'General'
    if axis.title is not None:
        axis.title.overlay = False
    label_font = CharacterProperties(sz=1000, solidFill=_NAVY)
    axis.txPr = RichText(p=[Paragraph(pPr=ParagraphProperties(defRPr=label_font),
                                    endParaRPr=label_font)])
    if axis.majorGridlines is not None:
        grid = GraphicalProperties()
        grid.line.solidFill = 'DFE5EC'
        axis.majorGridlines = ChartLines(spPr=grid)


def _column(ws_column):
    return get_column_letter(ws_column)


def _text(sheet, row, col, value):
    cell = sheet.cell(row, col, str(value))
    cell.data_type = 's'
    return cell


def _headers(sheet, row, labels):
    for col, label in enumerate(labels, 1):
        cell = _text(sheet, row, col, label)
        cell.fill = PatternFill('solid', fgColor=_NAVY)
        cell.font = Font(color='FFFFFF', bold=True)
        width = min(42, max(15, len(str(label)) + 3))
        sheet.column_dimensions[cell.column_letter].width = width


def _init_verification_sheets(instruction_lines):
    workbook = Workbook()
    workbook.calculation.calcMode = 'auto'
    workbook.calculation.fullCalcOnLoad = True
    summary = workbook.active
    summary.title = 'Verification'
    summary.sheet_view.zoomScale = 82
    inputs = workbook.create_sheet('Inputs')
    fit = workbook.create_sheet('Calculations')
    for sheet in workbook:
        sheet.sheet_view.showGridLines = False

    _text(summary, 1, 1, 'StatCraft model verification').font = Font(size=18, bold=True, color=_NAVY)
    for row, line in enumerate(instruction_lines, 2):
        _text(summary, row, 1, line)
    _text(summary, 6, 1, 'Result').font = Font(bold=True, color=_NAVY)
    _text(summary, 7, 1, 'Model inputs').font = Font(bold=True, color=_NAVY)
    _headers(summary, 9, ('Metric', 'StatCraft reference', 'Excel calculation', 'Difference', 'Check'))
    summary.column_dimensions['A'].width = 28
    summary.freeze_panes = 'B10'
    return workbook, summary, inputs, fit


def _populate_verification_table(summary, references, formulas, settings):
    for row, ((label, value), formula) in enumerate(zip(references, formulas), 10):
        _text(summary, row, 1, label)
        summary.cell(row, 2, value)
        summary.cell(row, 3, f'=IF($B$7="Valid",{formula},"")')
        summary.cell(row, 4, f'=IF(ISNUMBER(C{row}),C{row}-B{row},"")')
        summary.cell(row, 5, f'=IF(ISNUMBER(D{row}),IF(ABS(D{row})<=1E-7+1E-6*ABS(B{row}),"Match","Different"),"")')
        if (
            not label.endswith('DF')
            and not label.startswith(('Observations', 'Subgroups', 'Sample N', 'Complete Subgroups'))
            and 'Signals' not in label
            and label != 'NDC'
        ):
            for col in range(2, 5):
                summary.cell(row, col).number_format = _NUMBER
    final = 9 + len(references)
    summary['B6'] = f'=IF(B7<>"Valid","Check inputs",IF(COUNTIF(E10:E{final},"Match")={len(references)},"PASS","DIFFERENCES FOUND"))'
    summary['B6'].font = Font(bold=True, color=_NAVY)
    summary['B6'].alignment = Alignment(horizontal='left')
    summary.conditional_formatting.add(f'E10:E{final}', CellIsRule(
        operator='equal', formula=['"Different"'], fill=PatternFill('solid', fgColor='FCE1DA')))

    _headers(summary, final + 2, ('Saved setting', 'Value'))
    summary.column_dimensions['A'].width = 28
    summary.column_dimensions['B'].width = 24
    for row, (label, value) in enumerate(settings, final + 3):
        _text(summary, row, 1, label)
        if isinstance(value, (int, float)):
            summary.cell(row, 2, value).number_format = '0.0%' if label == 'Saved confidence level' else 'General'
        else:
            _text(summary, row, 2, value)
    return final


def _check_budget(cells, cols, rows):
    if cells > 1_100_000:
        raise ValueError('This workbook exceeds the supported Excel export cell budget.')
    if cols > 16384 or rows >= 1048576:
        raise ValueError('The saved analysis exceeds Excel worksheet limits.')


def _input_data(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    params = entry['recipe']['parameters']
    response = sheet.columns[params['response_index']]
    method = [('Worksheet', sheet.name), ('Saved confidence level', params['confidence'])]
    if entry['recipe']['action'] == 'multiple_regression':
        columns = [sheet.columns[index] for index in params['predictor_indices']]
        return [response, *columns], [*method, ('Method', 'Continuous OLS with intercept')], None

    result = entry['result']
    factors = [sheet.columns[index] for index in params['factor_indices']]
    block_levels = []
    if result['include_blocks']:
        block_column = next((column for column in sheet.columns if column.name.casefold() == 'blocks'), None)
        if block_column is None or 'verification_block_columns' not in result:
            raise ValueError('Rerun this blocked factorial fit to verify the saved block coding.')
        raw_blocks = [normalize_numeric(value) for value in block_column.numeric_values(True)]
        retained = [raw_blocks[i] if i < len(raw_blocks) else None for i in result['row_indices']]
        block_levels = sorted({level for level in retained if level is not None})
        count = len(block_levels)
        if count < 2:
            raise ValueError('Rerun the factorial fit after changes to its block assignments.')
        contrasts = ([[-1, 1]] if count == 2 else
                     [[int(i == j) - int(i == count - 1) for i in range(count)] for j in range(count - 1)])
        mapping = dict(zip(block_levels, zip(*contrasts)))
        if None in retained:
            mapping[None] = (-1,) if count == 2 else (0,) * (count - 1)
        if list(zip(*(mapping[level] for level in retained))) != [
            tuple(column) for column in result['verification_block_columns']
        ]:
            raise ValueError('Rerun the factorial fit after changes to its block assignments.')
        block_levels = list(mapping.items())
        factors.append(block_column)
    method.extend([('Method', 'Two-level factorial coded OLS'),
                   ('Include blocks', 'Yes' if result['include_blocks'] else 'No'),
                   ('Design seed', str(result['design_seed']) if result.get('design_seed') is not None else 'Unavailable')])
    return [response, *factors], method, block_levels


def _write_factor_coding(workbook, result, retained, block_levels):
    # Write the settings and dependent columns for the saved design matrix.
    coding = workbook.create_sheet('Factor Coding')
    coding.sheet_view.showGridLines = False
    factors = result['factor_coding']
    block_names = result['block_terms']
    _headers(coding, 1, ('Worksheet row', *(factor['name'] for factor in factors), *block_names))
    coding.freeze_panes = 'B2'

    settings_col = len(factors) + len(block_names) + 3
    for offset, label in enumerate(('Factor', 'Low', 'High', 'Center', 'Half range')):
        _text(coding, 1, settings_col + offset, label).font = Font(bold=True, color=_NAVY)
        coding.column_dimensions[_column(settings_col + offset)].width = 15
    for row, factor in enumerate(factors, 2):
        _text(coding, row, settings_col, factor['name'])
        for offset, key in enumerate(('low', 'high', 'center', 'half_range'), 1):
            coding.cell(row, settings_col + offset, factor[key])

    if block_levels:
        header = len(factors) + 4
        _text(coding, header, settings_col, 'Block level').font = Font(bold=True, color=_NAVY)
        for offset, name in enumerate(block_names, 1):
            _text(coding, header, settings_col + offset, name).font = Font(bold=True, color=_NAVY)
        for row, (level, values) in enumerate(block_levels, header + 1):
            if level is None:
                _text(coding, row, settings_col, 'Missing')
            else:
                coding.cell(row, settings_col, level)
            for offset, value in enumerate(values, 1):
                coding.cell(row, settings_col + offset, value)
        has_blank = block_levels[-1][0] is None
        last_lookup = header + len(block_levels) - int(has_blank)
        lookup = (f'${_column(settings_col)}${header + 1}:'
                  f'${_column(settings_col + len(block_names))}${last_lookup}')

    center = _column(settings_col + 3)
    half = _column(settings_col + 4)
    first, last = 'B', _column(len(factors) + 1)
    for row, index in enumerate(retained, 2):
        coding.cell(row, 1, index + 1)
        for offset in range(len(factors)):
            source = f'Inputs!{_column(4 + offset)}{index + 2}'
            setting_row = 2 + offset
            standardized = f'(({source}-${center}${setting_row})/${half}${setting_row})'
            rounded = f'ROUND({standardized},0)'
            coding.cell(row, 2 + offset, f'=IF(AND(ISNUMBER({source}),ABS({rounded})<=1,'
                        f'ABS({standardized}-{rounded})<=1E-10),{rounded},NA())')
        if block_levels:
            source = f'Inputs!{_column(4 + len(factors))}{index + 2}'
            for offset in range(len(block_names)):
                blank = f'${_column(settings_col + offset + 1)}${last_lookup + 1}' if has_blank else 'NA()'
                coding.cell(row, 2 + len(factors) + offset,
                            f'=IF(ISBLANK({source}),{blank},IF(ISNUMBER({source}),'
                            f'VLOOKUP({source},{lookup},{offset + 2},FALSE),NA()))')
    return first, last


def _factorial_predictors(row, result, factor_first, factor_last):
    coding_row = f"'Factor Coding'!{factor_first}{row}:{factor_last}{row}"
    block_count = len(result['block_terms'])
    factor_count = len(result['factor_coding'])
    terms = [f"'Factor Coding'!{_column(2 + factor_count + offset)}{row}" for offset in range(block_count)]
    for term in result['selected_terms']:
        factors = ','.join(f"'Factor Coding'!{_column(2 + index)}{row}" for index in term)
        terms.append(f'PRODUCT({factors})')
    # A valid design row has either all center settings or no center settings.
    valid = (f'AND(COUNT({coding_row})={factor_count},'
             f'OR(COUNTIF({coding_row},0)=0,COUNTIF({coding_row},0)={factor_count}))')
    return [f'=IF({valid},{term},NA())' for term in terms]


def _build_ols_workbook(presenter, entry):
    columns, settings, block_levels = _input_data(presenter, entry)
    result = entry['result']
    retained = result['row_indices']
    row_count = result['count'] + result['missing']
    predictors = len(result['coefficients']) - 1
    _check_budget((row_count + 1) * (len(columns) + 2) + len(retained) * (predictors + 4),
                  max(len(columns) + 2, 2 * predictors + 6), row_count)

    workbook, summary, inputs, fit = _init_verification_sheets((
        'Edit the blue values on Inputs to recalculate the fit and residual chart.',
        'Row inclusion is fixed to the saved analysis. Re-export to test a different set of rows.',
        'StatCraft reference values and saved settings are snapshots. Other report statistics are outside this comparison.',
    ))

    names = [column.name for column in columns]
    _headers(inputs, 1, ('Worksheet row', 'In saved fit', *names))
    inputs.freeze_panes = 'C2'
    inputs.auto_filter.ref = f'A1:{_column(len(columns) + 2)}{row_count + 1}'
    if block_levels is not None:
        factor_first, factor_last = _write_factor_coding(workbook, result, retained, block_levels)
    raw = [[normalize_numeric(value) for value in column.numeric_values(True)] for column in columns]
    included = set(retained)
    for index in range(row_count):
        row = index + 2
        inputs.append([index + 1, index in included, *(
            values[index] if index < len(values) else None for values in raw
        )])
        for cell in inputs[row][2:]:
            cell.font = _EDITABLE_FONT

    coefficient_names = [coefficient['name'] for coefficient in result['coefficients']]
    _headers(fit, 1, ('Worksheet row', names[0], *coefficient_names[1:], 'Fitted', 'Residual'))
    fit.freeze_panes = 'C2'
    last = len(retained) + 1
    x_end = _column(predictors + 2)
    fitted_col, residual_col = predictors + 3, predictors + 4
    fitted_letter, residual_letter = _column(fitted_col), _column(residual_col)
    # LINEST returns slopes in reverse input order followed by the intercept.
    first_coef = _column(residual_col + 2)
    last_coef = _column(residual_col + predictors + 2)
    _text(fit, 1, residual_col + 2, 'LINEST coefficients (reverse order, then intercept)')
    x_range = f'C2:{x_end}{last}'
    y_range = f'B2:B{last}'
    linest = f'LINEST({y_range},{x_range},TRUE,TRUE)'
    fit[f'{first_coef}2'] = ArrayFormula(f'{first_coef}2:{last_coef}2', f'=LINEST({y_range},{x_range},TRUE,FALSE)')
    # Align the slopes with the predictor columns for a same-shape SUMPRODUCT.
    last_slope = _column(residual_col + predictors + 1)
    _text(fit, 4, residual_col + 1, 'Slopes in input order')
    for offset in range(predictors):
        coef = _column(residual_col + predictors + 1 - offset)
        fit.cell(4, residual_col + 2 + offset, f'={coef}2')
    for row, index in enumerate(retained, 2):
        fit.cell(row, 1, index + 1)
        response = f'Inputs!C{index + 2}'
        fit.cell(row, 2, f'=IF(ISNUMBER({response}),{response},NA())')
        if block_levels is None:
            for col in range(3, predictors + 3):
                source = f'Inputs!{_column(col + 1)}{index + 2}'
                fit.cell(row, col, f'=IF(ISNUMBER({source}),{source},NA())')
        else:
            for col, formula in enumerate(_factorial_predictors(row, result, factor_first, factor_last), 3):
                fit.cell(row, col, formula)
        fit.cell(row, fitted_col, f'=IF(Verification!$B$7="Valid",${last_coef}$2+'
                 f'SUMPRODUCT(C{row}:{x_end}{row},${first_coef}$4:${last_slope}$4),NA())')
        fit.cell(row, residual_col, f'=B{row}-{fitted_letter}{row}')

    expected_df = len(retained) - predictors - 1
    x_count = len(retained) * predictors
    summary['B7'] = (f'=IFERROR(IF(AND(COUNT(Calculations!{x_range})={x_count},'
                     f'COUNT(Calculations!{y_range})={len(retained)},'
                     f'MAX(Calculations!{y_range})>MIN(Calculations!{y_range}),'
                     f'Calculations!{first_coef}3={expected_df}),"Valid","Check inputs"),"Check inputs")')
    fit[f'{first_coef}3'] = f'=INDEX({linest},4,2)'
    references = [(c['name'], c['estimate']) for c in result['coefficients']]
    references.extend((('Residual SS', result['ss_error']), ('Residual DF', result['df_error']),
                       ('R-squared', result['r_squared'])))
    residuals = f'Calculations!{residual_letter}2:{residual_letter}{last}'
    formulas = [f'Calculations!{last_coef}2'] + [
        f'Calculations!{_column(residual_col + predictors + 1 - i)}2'
        for i in range(predictors)
    ]
    formulas += [f'SUMSQ({residuals})', f'Calculations!{first_coef}3',
                 f'1-SUMSQ({residuals})/DEVSQ(Calculations!{y_range})']
    effect_start = 10 + len(references)
    if block_levels is not None:
        for row, coefficient in enumerate(result['coefficients'], 10):
            if coefficient['effect'] is not None:
                references.append((f"Effect: {coefficient['name']}", coefficient['effect']))
                formulas.append(f'2*C{row}')
    final = _populate_verification_table(summary, references, formulas, settings)

    chart = ScatterChart()
    chart.title = 'Residuals versus fitted values'
    chart.x_axis.axPos = 'b'
    chart.x_axis.title = 'Fitted value'
    chart.y_axis.title = 'Residual'
    _style_chart_axis(chart.x_axis)
    _style_chart_axis(chart.y_axis)
    chart.scatterStyle = 'marker'
    chart.legend = None
    chart.width, chart.height = 17, 9
    x = Reference(fit, min_col=fitted_col, min_row=2, max_row=last)
    y = Reference(fit, min_col=residual_col, min_row=2, max_row=last)
    series = Series(y, x, title='Residuals')
    series.marker.symbol = 'circle'
    series.marker.size = 5
    series.marker.graphicalProperties.solidFill = '25729C'
    series.marker.graphicalProperties.line.solidFill = '25729C'
    series.graphicalProperties.line.noFill = True
    chart.series.append(series)
    summary.add_chart(chart, 'G6')
    if effect_start <= final:
        effects = BarChart()
        effects.type = 'bar'
        effects.title = 'Factorial effects'
        effects.y_axis.axPos = 'b'
        effects.y_axis.title = 'Estimated effect'
        _style_chart_axis(effects.x_axis)
        _style_chart_axis(effects.y_axis)
        effects.legend = None
        effects.width = 17
        effects.height = max(9, min(25, (final - effect_start + 1) * 0.65))
        effects.add_data(Reference(summary, min_col=3, min_row=effect_start, max_row=final))
        effects.set_categories(Reference(summary, min_col=1, min_row=effect_start, max_row=final))
        effects.series[0].graphicalProperties.solidFill = '25729C'
        summary.add_chart(effects, 'G27')
    return workbook


def _style_line_series(series, color, dashed=False, width=22000):
    series.graphicalProperties.line.solidFill = color
    series.graphicalProperties.line.width = width
    if dashed:
        series.graphicalProperties.line.dashStyle = 'dash'


def _add_control_chart(summary, anchor, title, y_title, calc_sheet, cat_col, last_row, series_specs):
    chart = LineChart()
    chart.smooth = False
    chart.legend.position = "b"
    chart.legend.overlay = False
    chart.title = title
    chart.x_axis.axPos = 'b'
    chart.x_axis.title = 'Observation' if cat_col == 1 and calc_sheet['A1'].value == 'Worksheet row' else 'Subgroup'
    chart.y_axis.title = y_title
    _style_chart_axis(chart.x_axis)
    _style_chart_axis(chart.y_axis)
    chart.width, chart.height = 17, 9
    cats = Reference(calc_sheet, min_col=cat_col, min_row=2, max_row=last_row)
    for col_idx, color, dashed, show_marker in series_specs:
        if col_idx is None:
            continue
        data = Reference(calc_sheet, min_col=col_idx, min_row=1, max_row=last_row)
        chart.add_data(data, titles_from_data=True)
        series = chart.series[-1]
        series.smooth = False
        _style_line_series(series, color, dashed=dashed)
        if show_marker:
            series.marker.symbol = 'circle'
            series.marker.size = 4
            series.marker.graphicalProperties.solidFill = color
    chart.set_categories(cats)
    summary.add_chart(chart, anchor)


def _build_imr_workbook(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    params = entry['recipe']['parameters']['settings']
    col = sheet.columns[params['variables'][0]]
    if col.kind != 'number':
        raise ValueError('Excel verification requires a numeric I-MR column.')
    result = entry['result']
    opts = result.get('options', {})
    trace = result.get('estimation_trace', {})
    span = int(result.get('span', opts.get('span', 2)))
    est_method = str(result.get('estimation_method', opts.get('estimation_method', 'amr'))).lower()
    unbiasing = bool(result.get('unbiasing', opts.get('unbiasing', True)))
    use_nelson = bool(result.get('use_nelson', opts.get('use_nelson', True)))
    k_sigma = float(trace.get('k_sigma', opts.get('k_sigma', 3.0)))
    hist_mean = trace.get('historical_mean', opts.get('historical_mean'))
    hist_sigma = trace.get('historical_sigma', opts.get('historical_sigma'))
    display_upper = bool(opts.get('display_upper', True))
    display_lower = bool(opts.get('display_lower', True))
    omitted_set = {int(x) for x in result.get('omit_subgroups', [])}

    observations = _normalize_imr_values(col.values, opts.get('exclude_rows'))
    n_total = len(observations)
    _check_budget(n_total * 20, 20, n_total)

    workbook, summary, inputs, calc = _init_verification_sheets((
        'Edit the blue values on Inputs to recalculate I-MR statistics, limits, and control charts.',
        'Row inclusion and estimation omissions match the saved analysis. Missing gaps break moving ranges.',
        'StatCraft reference values and saved settings are snapshots. Nelson rules 2-4 are outside this comparison.',
    ))

    _headers(inputs, 1, ('Worksheet row', 'In saved observations', 'Omitted from estimation', col.name))
    inputs.freeze_panes = 'D2'
    inputs.auto_filter.ref = f'A1:D{n_total + 1}'
    for idx, val in enumerate(observations, 1):
        row = idx + 1
        inputs.append([idx, val is not None, idx in omitted_set, val])
        inputs.cell(row, 4).font = _EDITABLE_FONT

    _headers(calc, 1, (
        'Worksheet row', 'Valid input', 'Observed', 'Est Observed', 'Moving Range', 'Est MR',
        'Sq Diff', 'I Center', 'I LCL', 'I UCL', 'MR Center', 'MR LCL', 'MR UCL', 'I Signal', 'MR Signal',
    ))
    calc.freeze_panes = 'C2'
    last = n_total + 1

    d2_val = _cap_d2(span)
    d3_val = _sub_d3(span)
    d4_val = _cap_d4(span)

    _text(calc, 1, 17, 'Parameter')
    _text(calc, 1, 18, 'Value')
    calc_params = [
        ('d2', d2_val),
        ('d3', d3_val),
        ('d4', d4_val),
        ('k_sigma', k_sigma),
        ('Observations N', f'=COUNT(Inputs!D2:D{last})'),
        ('I Center', float(hist_mean) if hist_mean is not None else f'=AVERAGE(D2:D{last})'),
    ]
    if hist_sigma is not None:
        sigma_formula = float(hist_sigma)
        mr_center_formula = f'={repr(float(d2_val))}*$R$8'
    elif est_method == 'mmr':
        d4_eff = d4_val if unbiasing else 1.0
        sigma_formula = f'=IF(COUNT(F2:F{last})>0,MEDIAN(F2:F{last})/{repr(float(d4_eff))},IF(COUNT(D2:D{last})>1,STDEV(D2:D{last}),0))'
        mr_center_formula = f'=IF(COUNT(F2:F{last})>0,MEDIAN(F2:F{last}),{repr(float(d2_val))}*$R$8)'
    elif est_method == 'srmssd':
        sigma_formula = f'=IF(COUNT(G2:G{last})>0,SQRT(SUM(G2:G{last})/(2*COUNT(G2:G{last}))),IF(COUNT(D2:D{last})>1,STDEV(D2:D{last}),0))'
        mr_center_formula = f'={repr(float(d2_val))}*$R$8'
    else:
        d2_eff = d2_val if (unbiasing or use_nelson) else 1.0
        sigma_formula = f'=IF(COUNT(F2:F{last})>0,AVERAGE(F2:F{last})/{repr(float(d2_eff))},IF(COUNT(D2:D{last})>1,STDEV(D2:D{last}),0))'
        mr_center_formula = f'=IF(COUNT(F2:F{last})>0,AVERAGE(F2:F{last}),{repr(float(d2_val))}*$R$8)'

    calc_params.extend([
        ('Within Sigma', sigma_formula),
        ('MR Center', mr_center_formula),
        ('I LCL', '=IF($R$16=1,$R$7-$R$5*$R$8,NA())' if display_lower else '=NA()'),
        ('I UCL', '=IF($R$16=1,$R$7+$R$5*$R$8,NA())' if display_upper else '=NA()'),
        ('MR LCL', '=IF($R$16=1,MAX(0,(1-$R$5*($R$3/$R$2))*$R$9),NA())' if display_lower else '=NA()'),
        ('MR UCL', '=IF($R$16=1,(1+$R$5*($R$3/$R$2))*$R$9,NA())' if display_upper else '=NA()'),
        ('I Test 1 Signals', f'=SUM(N2:N{last})'),
        ('MR Test 1 Signals', f'=SUM(O2:O{last})'),
        ('Inputs Valid', f'=IFERROR(IF(AND(MIN(B2:B{last})=1,COUNT(Inputs!D2:D{last})>=2,COUNT(D2:D{last})>=1),1,0),0)'),
    ])
    for r_idx, (pname, pval) in enumerate(calc_params, 2):
        _text(calc, r_idx, 17, pname)
        calc.cell(r_idx, 18, pval)

    for r in range(2, last + 1):
        calc.cell(r, 1, f'=Inputs!A{r}')
        calc.cell(r, 2, f'=IF(Inputs!B{r},IF(ISNUMBER(Inputs!D{r}),1,0),IF(OR(ISBLANK(Inputs!D{r}),ISNUMBER(Inputs!D{r})),1,0))')
        calc.cell(r, 3, f'=IF(ISNUMBER(Inputs!D{r}),Inputs!D{r},NA())')
        calc.cell(r, 4, f'=IF(AND(ISNUMBER(Inputs!D{r}),NOT(Inputs!C{r})),Inputs!D{r},"")')
        if r >= span + 1:
            start_r = r - span + 1
            calc.cell(r, 5, f'=IF(COUNT(Inputs!D{start_r}:Inputs!D{r})={span},MAX(Inputs!D{start_r}:Inputs!D{r})-MIN(Inputs!D{start_r}:Inputs!D{r}),NA())')
            calc.cell(r, 6, f'=IF(AND(ISNUMBER(E{r}),COUNTIF(Inputs!C{start_r}:Inputs!C{r},TRUE)=0),E{r},"")')
        else:
            calc.cell(r, 5, '=NA()')
            calc.cell(r, 6, '')
        if r >= 3:
            calc.cell(r, 7, f'=IF(AND(ISNUMBER(Inputs!D{r-1}),ISNUMBER(Inputs!D{r}),NOT(Inputs!C{r-1}),NOT(Inputs!C{r})),(Inputs!D{r}-Inputs!D{r-1})^2,"")')
        else:
            calc.cell(r, 7, '')
        calc.cell(r, 8, '=$R$7')
        calc.cell(r, 9, '=$R$10')
        calc.cell(r, 10, '=$R$11')
        calc.cell(r, 11, '=$R$9')
        calc.cell(r, 12, '=$R$12')
        calc.cell(r, 13, '=$R$13')
        i_cond_l = 'C{r}<I{r}'.format(r=r) if display_lower else 'FALSE'
        i_cond_u = 'C{r}>J{r}'.format(r=r) if display_upper else 'FALSE'
        calc.cell(r, 14, f'=IF(ISNUMBER(C{r}),IF(OR({i_cond_l},{i_cond_u}),1,0),0)')
        m_cond_l = 'E{r}<L{r}'.format(r=r) if display_lower else 'FALSE'
        m_cond_u = 'E{r}>M{r}'.format(r=r) if display_upper else 'FALSE'
        calc.cell(r, 15, f'=IF(ISNUMBER(E{r}),IF(OR({m_cond_l},{m_cond_u}),1,0),0)')

    summary['B7'] = '=IF(Calculations!$R$16=1,"Valid","Check inputs")'

    references = [
        ('Observations (N)', result['count']),
        ('Mean (I Center)', result['i_center']),
        ('MR Center', result['mr_center']),
        ('Within Sigma', result['within_stdev']),
    ]
    formulas = [
        'Calculations!$R$6',
        'Calculations!$R$7',
        'Calculations!$R$9',
        'Calculations!$R$8',
    ]
    if result.get('i_lcl') is not None:
        references.append(('I LCL', result['i_lcl']))
        formulas.append('Calculations!$R$10')
    if result.get('i_ucl') is not None:
        references.append(('I UCL', result['i_ucl']))
        formulas.append('Calculations!$R$11')
    if result.get('mr_lcl') is not None:
        references.append(('MR LCL', result['mr_lcl']))
        formulas.append('Calculations!$R$12')
    if result.get('mr_ucl') is not None:
        references.append(('MR UCL', result['mr_ucl']))
        formulas.append('Calculations!$R$13')
    references.extend([
        ('I Test 1 Signals', len(result.get('i_signals', []))),
        ('MR Test 1 Signals', len(result.get('mr_signals', []))),
    ])
    formulas.extend(['Calculations!$R$14', 'Calculations!$R$15'])

    settings = [
        ('Worksheet', sheet.name),
        ('Variable', col.name),
        ('Method', f'I-MR ({est_method.upper()})'),
        ('Moving range span', span),
        ('d2 constant', d2_val),
        ('d3 constant', d3_val),
        ('K sigma', k_sigma),
        ('Unbiasing', 'Yes' if unbiasing else 'No'),
        ('Historical mean', hist_mean if hist_mean is not None else 'Estimated'),
        ('Historical sigma', hist_sigma if hist_sigma is not None else 'Estimated'),
    ]
    _populate_verification_table(summary, references, formulas, settings)

    _add_control_chart(
        summary, 'G10', f'Individuals Chart: {col.name}', col.name, calc, 1, last,
        [
            (3, '25729C', False, True),
            (8, '1B7F4B', False, False),
            (9 if display_lower else None, 'C0392B', True, False),
            (10 if display_upper else None, 'C0392B', True, False),
        ],
    )
    _add_control_chart(
        summary, 'G31', f'Moving Range Chart (Span = {span})', 'Moving Range', calc, 1, last,
        [
            (5, '25729C', False, True),
            (11, '1B7F4B', False, False),
            (12 if display_lower else None, 'C0392B', True, False),
            (13 if display_upper else None, 'C0392B', True, False),
        ],
    )
    return workbook


def _build_subgroup_workbook(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    params = entry['recipe']['parameters']
    result = entry['result']
    chart_type = params.get('chart_type', result.get('chart_type', 'xbar_r'))
    if chart_type not in ('xbar_r', 'xbar_s'):
        raise ValueError('Excel verification supports Xbar-R and Xbar-S subgroup control charts.')
    is_s = (chart_type == 'xbar_s')
    disp_short = 'S' if is_s else 'R'
    disp_full = 'StDev' if is_s else 'Range'
    opts = result['options']
    stacked = bool(params.get('stacked', True))
    subgroups_with_rows = _extract_subgroup_rows(sheet, params)
    k_subgroups = len(subgroups_with_rows)
    k_sigma = float(opts['k_sigma'])
    method = str(opts['estimation_method']).lower()
    unbiasing = bool(opts['unbiasing'])
    omitted_set = {int(x) for x in opts.get('omit_subgroups', [])}
    hist_mean = opts.get('historical_mean')
    hist_sigma = opts.get('historical_sigma')
    display_upper = bool(opts.get('display_upper', True))
    display_lower = bool(opts.get('display_lower', True))
    t1_cfg = opts.get('tests', {}).get('test1', {})
    t1_enabled = bool(t1_cfg.get('enabled', True))
    t1_k = float(t1_cfg.get('k', 3.0))

    workbook, summary, inputs, calc = _init_verification_sheets((
        f'Edit the blue values on Inputs to recalculate {"Xbar-S" if is_s else "Xbar-R"} means, {disp_full.lower()}s, stepped limits, and charts.',
        'Subgroup membership and estimation omissions match the saved analysis.',
        'StatCraft reference values and saved settings are snapshots. Nelson rules 2-8 are outside this comparison.',
    ))

    subgroup_ranges = []
    max_n = 2
    if stacked:
        resp_col = sheet.columns[params['response_index']]
        _headers(inputs, 1, ('Worksheet row', 'Subgroup', 'Has saved value', 'In estimation', resp_col.name))
        inputs.freeze_panes = 'D2'
        cur_row = 2
        for sg_idx, sg_label, items in subgroups_with_rows:
            start_r = cur_row
            in_est = sg_idx not in omitted_set
            clean_cnt = 0
            for ws_row, val in items:
                has_val = val is not None and math.isfinite(val)
                if has_val:
                    clean_cnt += 1
                inputs.append([ws_row, sg_label, has_val, in_est, val])
                inputs.cell(cur_row, 5).font = _EDITABLE_FONT
                cur_row += 1
            end_r = cur_row - 1
            max_n = max(max_n, clean_cnt, len(items))
            subgroup_ranges.append((sg_idx, sg_label, in_est, f'Inputs!E{start_r}:E{end_r}', start_r, end_r, items))
        inputs.auto_filter.ref = f'A1:E{cur_row - 1}'
    else:
        col_indices = params['indices']
        cols = [sheet.columns[i] for i in col_indices]
        _headers(inputs, 1, ('Worksheet row', 'Subgroup', 'In estimation', *(c.name for c in cols)))
        inputs.freeze_panes = 'D2'
        first_col_l = _column(4)
        last_col_l = _column(3 + len(cols))
        for row_idx, (sg_idx, sg_label, items) in enumerate(subgroups_with_rows, 2):
            in_est = sg_idx not in omitted_set
            vals = [v for _, v in items]
            inputs.append([sg_idx, sg_label, in_est, *vals])
            for c_off in range(4, 4 + len(cols)):
                inputs.cell(row_idx, c_off).font = _EDITABLE_FONT
            max_n = max(max_n, len(cols))
            subgroup_ranges.append((
                sg_idx, sg_label, in_est,
                f'Inputs!{first_col_l}{row_idx}:{last_col_l}{row_idx}',
                row_idx, row_idx, items,
            ))
        inputs.auto_filter.ref = f'A1:{last_col_l}{k_subgroups + 1}'

    _check_budget(k_subgroups * 35 + max_n * 10, 40, max(k_subgroups, len(inputs['A'])))

    _headers(calc, 1, (
        'Subgroup', 'Valid input', 'In estimation', 'n_i', 'Mean_i', 'Range_i', 'StDev_i',
        'c4_i' if is_s else 'd2_i', 'c5_i' if is_s else 'd3_i',
        'Est Obs', 'Est Mean Term', 'Disp Weight', 'Disp Weighted Term',
        f'Est {disp_full}', 'Est SS', 'Est DF', 'Est Disp n', 'All Disp n',
        'Xbar Center', 'Xbar LCL', 'Xbar UCL', f'{disp_short} Center', f'{disp_short} LCL', f'{disp_short} UCL',
        'Xbar Signal', f'{disp_short} Signal', 'Xbar LCL Num', 'Xbar UCL Num', f'{disp_short} LCL Num', f'{disp_short} UCL Num',
    ))
    calc.freeze_panes = 'D2'
    last = k_subgroups + 1

    max_tbl = max(50, max_n)
    _text(calc, 1, 32, 'n')
    _text(calc, 1, 33, 'c4' if is_s else 'd2')
    _text(calc, 1, 34, 'c5' if is_s else 'd3')
    for n_val in range(1, max_tbl + 1):
        tbl_r = n_val + 1
        calc.cell(tbl_r, 32, n_val)
        calc.cell(tbl_r, 33, _sub_c4(n_val) if is_s else _sub_d2(n_val))
        calc.cell(tbl_r, 34, _sub_c5(n_val) if is_s else _sub_d3(n_val))
    tbl_ref = f'$AF$2:$AH${max_tbl + 1}'

    _text(calc, 1, 36, 'Parameter')
    _text(calc, 1, 37, 'Value')
    unequal_est_formula = f'=IF(COUNT(Q2:Q{last})=0,FALSE,MIN(Q2:Q{last})<>MAX(Q2:Q{last}))'
    varying_all_formula = f'=IF(COUNT(R2:R{last})=0,FALSE,MIN(R2:R{last})<>MAX(R2:R{last}))'
    xbar_center_formula = float(hist_mean) if hist_mean is not None else f'=SUM(K2:K{last})/SUM(J2:J{last})'

    if hist_sigma is not None:
        sigma_formula = float(hist_sigma)
    elif method == 'pooled_stdev':
        c4_pool = (
            f'EXP(0.5*LN(2/SUM(P2:P{last}))+GAMMALN((SUM(P2:P{last})+1)/2)-GAMMALN(SUM(P2:P{last})/2))'
            if unbiasing else '1'
        )
        sigma_formula = f'=IF(SUM(P2:P{last})>0,SQRT(SUM(O2:O{last})/SUM(P2:P{last}))/{c4_pool},0)'
    elif unbiasing:
        sigma_formula = (
            f'=IF(COUNT(Q2:Q{last})=0,0,IF($AK$4,SUM(M2:M{last})/SUM(L2:L{last}),'
            f'AVERAGE(N2:N{last})/VLOOKUP(ROUND(AVERAGE(Q2:Q{last}),0),{tbl_ref},2,FALSE)))'
        )
    else:
        sigma_formula = f'=IF(COUNT(Q2:Q{last})=0,0,AVERAGE(N2:N{last}))'

    unbias_factor_avg = f'VLOOKUP(IF(COUNT(R2:R{last})>0,ROUND(AVERAGE(R2:R{last}),0),2),{tbl_ref},2,FALSE)' if (not is_s or unbiasing) else '1'
    if hist_sigma is not None:
        disp_center_formula = f'={unbias_factor_avg}*$AK$6'
    else:
        disp_center_formula = (
            f'=IF($AK$5,{unbias_factor_avg}*$AK$6,'
            f'IF(COUNT(N2:N{last})>0,AVERAGE(N2:N{last}),0))'
        )

    scalar_rows = [
        ('k_sigma', k_sigma),
        ('Xbar Center', xbar_center_formula),
        ('Unequal est disp', unequal_est_formula),
        ('Varying all disp', varying_all_formula),
        ('Within Sigma', sigma_formula),
        (f'{disp_short} Center', disp_center_formula),
        ('Subgroups (K)', f'=COUNTA(A2:A{last})'),
        ('Xbar Signals', f'=SUM(Y2:Y{last})'),
        (f'{disp_short} Signals', f'=SUM(Z2:Z{last})'),
        ('Inputs Valid', f'=IFERROR(IF(AND(MIN(B2:B{last})=1,SUM(J2:J{last})>=1),1,0),0)'),
    ]
    for r_idx, (pname, pval) in enumerate(scalar_rows, 2):
        _text(calc, r_idx, 36, pname)
        calc.cell(r_idx, 37, pval)
    _text(calc, 1, 39, 'Mean_i')
    _text(calc, 1, 40, f'{disp_full}_i')

    disp_obs_col = 'G' if is_s else 'F'
    for idx, (sg_idx, sg_label, in_est, rng_ref, start_r, end_r, items) in enumerate(subgroup_ranges, 2):
        _text(calc, idx, 1, sg_label)
        if stacked:
            checks = []
            for offset, (_, v) in enumerate(items):
                cell_ref = f'Inputs!E{start_r + offset}'
                if v is not None and math.isfinite(v):
                    checks.append(f'ISNUMBER({cell_ref})')
                else:
                    checks.append(f'OR(ISBLANK({cell_ref}),ISNUMBER({cell_ref}))')
            calc.cell(idx, 2, f'=IF(AND({",".join(checks)}),1,0)')
            in_est_ref = f'Inputs!D{start_r}'
        else:
            checks = []
            for offset, (_, v) in enumerate(items):
                col_l = _column(4 + offset)
                cell_ref = f'Inputs!{col_l}{start_r}'
                if v is not None and math.isfinite(v):
                    checks.append(f'ISNUMBER({cell_ref})')
                else:
                    checks.append(f'OR(ISBLANK({cell_ref}),ISNUMBER({cell_ref}))')
            calc.cell(idx, 2, f'=IF(AND({",".join(checks)}),1,0)')
            in_est_ref = f'Inputs!C{start_r}'
        calc.cell(idx, 3, f'={in_est_ref}')
        calc.cell(idx, 4, f'=COUNT({rng_ref})')
        calc.cell(idx, 5, f'=IF(D{idx}>=1,AVERAGE({rng_ref}),NA())')
        calc.cell(idx, 6, f'=IF(D{idx}>=2,MAX({rng_ref})-MIN({rng_ref}),NA())')
        calc.cell(idx, 7, f'=IF(D{idx}>=2,STDEV({rng_ref}),NA())')
        calc.cell(idx, 8, f'=IF(D{idx}>=2,VLOOKUP(D{idx},{tbl_ref},2,FALSE),NA())')
        calc.cell(idx, 9, f'=IF(D{idx}>=2,VLOOKUP(D{idx},{tbl_ref},3,FALSE),NA())')
        calc.cell(idx, 10, f'=IF(AND(C{idx},D{idx}>=1),D{idx},0)')
        calc.cell(idx, 11, f'=IF(AND(C{idx},D{idx}>=1),D{idx}*E{idx},0)')
        if is_s:
            calc.cell(idx, 12, f'=IF(AND(C{idx},D{idx}>=2),(H{idx}^2)/MAX(1E-12,1-(H{idx}^2)),0)')
        else:
            calc.cell(idx, 12, f'=IF(AND(C{idx},D{idx}>=2),IF(I{idx}>0,(H{idx}^2)/(I{idx}^2),1),0)')
        calc.cell(idx, 13, f'=IF(AND(C{idx},D{idx}>=2),L{idx}*IF(H{idx}>0,{disp_obs_col}{idx}/H{idx},{disp_obs_col}{idx}),0)')
        calc.cell(idx, 14, f'=IF(AND(C{idx},D{idx}>=2),{disp_obs_col}{idx},"")')
        calc.cell(idx, 15, f'=IF(AND(C{idx},D{idx}>=2),MAX(0,D{idx}-1)*(G{idx}^2),0)')
        calc.cell(idx, 16, f'=IF(AND(C{idx},D{idx}>=2),MAX(0,D{idx}-1),0)')
        calc.cell(idx, 17, f'=IF(AND(C{idx},D{idx}>=2),D{idx},"")')
        calc.cell(idx, 18, f'=IF(D{idx}>=2,D{idx},"")')
        calc.cell(idx, 19, f'=IF($AK$11=1,$AK$3,NA())')
        calc.cell(idx, 20, f'=IF(AND($AK$11=1,D{idx}>=1),$AK$3-$AK$2*($AK$6/SQRT(D{idx})),NA())' if display_lower else '=NA()')
        calc.cell(idx, 21, f'=IF(AND($AK$11=1,D{idx}>=1),$AK$3+$AK$2*($AK$6/SQRT(D{idx})),NA())' if display_upper else '=NA()')
        row_cl_unbias = f'H{idx}' if (not is_s or unbiasing) else '1'
        disp_cl_expr = f'{row_cl_unbias}*$AK$6' if hist_sigma is not None else f'IF($AK$5,{row_cl_unbias}*$AK$6,$AK$7)'
        calc.cell(idx, 22, f'=IF(AND($AK$11=1,D{idx}>=2),{disp_cl_expr},NA())')
        calc.cell(idx, 23, f'=IF(AND($AK$11=1,D{idx}>=2),MAX(0,V{idx}-$AK$2*I{idx}*$AK$6),NA())' if display_lower else '=NA()')
        calc.cell(idx, 24, f'=IF(AND($AK$11=1,D{idx}>=2),V{idx}+$AK$2*I{idx}*$AK$6,NA())' if display_upper else '=NA()')
        if t1_enabled:
            calc.cell(idx, 25, f'=IF(AND(ISNUMBER(E{idx}),D{idx}>=1,$AK$6>0),IF(ABS((E{idx}-$AK$3)/($AK$6/SQRT(D{idx})))>{repr(t1_k)},1,0),0)')
        else:
            calc.cell(idx, 25, 0)
        d_l_cond = f'{disp_obs_col}{idx}<W{idx}' if display_lower else 'FALSE'
        d_u_cond = f'{disp_obs_col}{idx}>X{idx}' if display_upper else 'FALSE'
        calc.cell(idx, 26, f'=IF(ISNUMBER({disp_obs_col}{idx}),IF(OR({d_l_cond},{d_u_cond}),1,0),0)')
        calc.cell(idx, 27, f'=IF(ISNUMBER(T{idx}),T{idx},"")')
        calc.cell(idx, 28, f'=IF(ISNUMBER(U{idx}),U{idx},"")')
        calc.cell(idx, 29, f'=IF(ISNUMBER(W{idx}),W{idx},"")')
        calc.cell(idx, 30, f'=IF(ISNUMBER(X{idx}),X{idx},"")')
        calc.cell(idx, 39, f'=IF(AND($AK$11=1,ISNUMBER(E{idx})),E{idx},NA())')
        calc.cell(idx, 40, f'=IF(AND($AK$11=1,ISNUMBER({disp_obs_col}{idx})),{disp_obs_col}{idx},NA())')

    summary['B7'] = '=IF(Calculations!$AK$11=1,"Valid","Check inputs")'

    xbar_lcl_vals = [v for v in result['xbar_lcl'] if v is not None]
    xbar_ucl_vals = [v for v in result['xbar_ucl'] if v is not None]
    disp_lcl_vals = [v for v in result['disp_lcl'] if v is not None]
    disp_ucl_vals = [v for v in result['disp_ucl'] if v is not None]
    xbar_t1_count = sum(1 for rules in result.get('test_failures', {}).values() if 1 in rules)

    references = [
        ('Subgroups (K)', result['k_subgroups']),
        ('Xbar Center', result['xbar_center']),
        ('Within Sigma', result['within_stdev']),
        (f'{disp_short} Center', result['disp_center']),
    ]
    formulas = [
        'Calculations!$AK$8',
        'Calculations!$AK$3',
        'Calculations!$AK$6',
        'Calculations!$AK$7',
    ]
    if xbar_lcl_vals:
        references.extend([
            ('Min Xbar LCL', min(xbar_lcl_vals)),
            ('Max Xbar LCL', max(xbar_lcl_vals)),
        ])
        formulas.extend([f'MIN(Calculations!AA2:AA{last})', f'MAX(Calculations!AA2:AA{last})'])
    if xbar_ucl_vals:
        references.extend([
            ('Min Xbar UCL', min(xbar_ucl_vals)),
            ('Max Xbar UCL', max(xbar_ucl_vals)),
        ])
        formulas.extend([f'MIN(Calculations!AB2:AB{last})', f'MAX(Calculations!AB2:AB{last})'])
    if disp_lcl_vals:
        references.extend([
            (f'Min {disp_short} LCL', min(disp_lcl_vals)),
            (f'Max {disp_short} LCL', max(disp_lcl_vals)),
        ])
        formulas.extend([f'MIN(Calculations!AC2:AC{last})', f'MAX(Calculations!AC2:AC{last})'])
    if disp_ucl_vals:
        references.extend([
            (f'Min {disp_short} UCL', min(disp_ucl_vals)),
            (f'Max {disp_short} UCL', max(disp_ucl_vals)),
        ])
        formulas.extend([f'MIN(Calculations!AD2:AD{last})', f'MAX(Calculations!AD2:AD{last})'])
    references.extend([
        ('Xbar Test 1 Signals', xbar_t1_count),
        (f'{disp_short} Signals', len(result.get('disp_signals', []))),
    ])
    formulas.extend(['Calculations!$AK$9', 'Calculations!$AK$10'])

    settings = [
        ('Worksheet', sheet.name),
        ('Variable', result.get('variable_name', 'Data')),
        ('Method', f'{"Xbar-S" if is_s else "Xbar-R"} ({method})'),
        ('K sigma', k_sigma),
        ('Unbiasing', 'Yes' if unbiasing else 'No'),
        ('Historical mean', hist_mean if hist_mean is not None else 'Estimated'),
        ('Historical sigma', hist_sigma if hist_sigma is not None else 'Estimated'),
    ]
    _populate_verification_table(summary, references, formulas, settings)

    _add_control_chart(
        summary, 'G10', f"Xbar Chart: {result.get('variable_name', 'Data')}", 'Sample Mean', calc, 1, last,
        [
            (39, '25729C', False, True),
            (19, '1B7F4B', False, False),
            (20 if display_lower else None, 'C0392B', True, False),
            (21 if display_upper else None, 'C0392B', True, False),
        ],
    )
    _add_control_chart(
        summary, 'G31', f'{disp_short} Chart (Subgroup {disp_full})', f'Sample {disp_full}', calc, 1, last,
        [
            (40, '25729C', False, True),
            (22, '1B7F4B', False, False),
            (23 if display_lower else None, 'C0392B', True, False),
            (24 if display_upper else None, 'C0392B', True, False),
        ],
    )
    return workbook


def _c4_excel(df_expr):
    return f'EXP(0.5*LN(2/({df_expr}))+GAMMALN((({df_expr})+1)/2)-GAMMALN(({df_expr})/2))'


def _build_capability_workbook(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    result = entry['result']
    if result.get('analysis_mode', 'normal') != 'normal':
        raise ValueError('Excel verification supports standard Normal Capability (not Between/Within mode).')
    params = entry['recipe']['parameters']
    var_name, cap_rows, opts = _extract_capability_rows(sheet, params, result)
    n_total = len(cap_rows)
    if n_total < 2:
        raise ValueError('Capability Excel verification requires at least two numeric observations.')

    sg_slices = []
    cur_sg = None
    start_r = 2
    for idx, (_, sg_id, _) in enumerate(cap_rows, 2):
        if cur_sg is None:
            cur_sg = sg_id
            start_r = idx
        elif sg_id != cur_sg:
            sg_slices.append((cur_sg, start_r, idx - 1))
            cur_sg = sg_id
            start_r = idx
    if cur_sg is not None:
        sg_slices.append((cur_sg, start_r, n_total + 1))

    group_sizes = [end_r - s_r + 1 for _, s_r, end_r in sg_slices]
    max_size = max(group_sizes)
    min_size = min(group_sizes)
    k_sg = len(sg_slices)
    span_eff = max(2, int(opts.get('moving_range_len', 2)))
    max_d = max(max_size, span_eff, 2)

    lsl = result.get('lsl')
    usl = result.get('usl')
    target = result.get('target')
    tolerance_k = float(result.get('tolerance_k', 6.0))
    half_k = tolerance_k / 2.0
    display_unit = str(result.get('display_unit', 'ppm')).lower()
    scale_factor = 100.0 if display_unit == 'percent' else 1_000_000.0
    est_gt1 = str(opts.get('estimate_method_gt1', 'pooled')).lower()
    est_eq1 = str(opts.get('estimate_method_eq1', 'amr')).lower()
    unbiased_within = bool(opts.get('unbiased_within', True))
    unbiased_overall = bool(opts.get('unbiased_overall', False))
    settings_dict = params.get('settings', {})
    hist_mean = settings_dict.get('historical_mean')
    hist_stdev = settings_dict.get('historical_stdev')

    _check_budget(n_total * 10 + k_sg * 10 + 200, 35, max(n_total, k_sg))

    workbook, summary, inputs, calc = _init_verification_sheets((
        'Edit the blue values on Inputs to recalculate capability indices, PPM rates, and histogram bins.',
        'Observation inclusion and subgroup grouping match the saved Normal Capability analysis.',
        'StatCraft reference values and saved settings are snapshots. Confidence intervals are outside this comparison.',
    ))

    _headers(inputs, 1, ('Worksheet row', 'Subgroup', 'In saved analysis', var_name))
    inputs.freeze_panes = 'D2'
    inputs.auto_filter.ref = f'A1:D{n_total + 1}'
    for r_idx, (ws_row, sg_id, val) in enumerate(cap_rows, 2):
        inputs.append([ws_row, sg_id, True, val])
        inputs.cell(r_idx, 4).font = _EDITABLE_FONT

    _headers(calc, 1, (
        'Worksheet row', 'Subgroup', 'Observed', 'Below LSL', 'Above USL', 'Moving Range', 'Sq Diff',
        'Spacer', 'Sg ID', 'n_i', 'df_i', 'Mean_i', 'Range_i', 'StDev_i', 'SS_i', 'd2_i', 'c4_i',
    ))
    calc.freeze_panes = 'C2'
    last = n_total + 1
    last_sg = k_sg + 1

    _text(calc, 1, 29, 'n')
    _text(calc, 1, 30, 'd2')
    _text(calc, 1, 31, 'd4')
    for n_val in range(1, max_d + 1):
        tbl_r = n_val + 1
        calc.cell(tbl_r, 29, n_val)
        calc.cell(tbl_r, 30, _cap_d2(n_val))
        calc.cell(tbl_r, 31, _cap_d4(n_val))
    tbl_ref = f'$AC$2:$AE${max_d + 1}'

    mr_len_active = span_eff if n_total >= span_eff else 2
    for r in range(2, last + 1):
        calc.cell(r, 1, f'=Inputs!A{r}')
        calc.cell(r, 2, f'=Inputs!B{r}')
        calc.cell(r, 3, f'=IF(ISNUMBER(Inputs!D{r}),Inputs!D{r},NA())')
        calc.cell(r, 4, f'=IF(ISNUMBER(C{r}),IF(C{r}<{repr(float(lsl))},1,0),0)' if lsl is not None else 0)
        calc.cell(r, 5, f'=IF(ISNUMBER(C{r}),IF(C{r}>{repr(float(usl))},1,0),0)' if usl is not None else 0)
        if r >= mr_len_active + 1:
            start_mr = r - mr_len_active + 1
            calc.cell(r, 6, f'=MAX(Inputs!D{start_mr}:Inputs!D{r})-MIN(Inputs!D{start_mr}:Inputs!D{r})')
        else:
            calc.cell(r, 6, '')
        calc.cell(r, 7, f'=(Inputs!D{r}-Inputs!D{r-1})^2' if r >= 3 else '')

    if max_size > 1:
        for sr, (sg_id, s_r, e_r) in enumerate(sg_slices, 2):
            rng_ref = f'Inputs!D{s_r}:D{e_r}'
            calc.cell(sr, 9, sg_id)
            calc.cell(sr, 10, f'=COUNT({rng_ref})')
            calc.cell(sr, 11, f'=MAX(0,J{sr}-1)')
            calc.cell(sr, 12, f'=AVERAGE({rng_ref})')
            calc.cell(sr, 13, f'=IF(J{sr}>1,MAX({rng_ref})-MIN({rng_ref}),"")')
            calc.cell(sr, 14, f'=IF(J{sr}>1,STDEV({rng_ref}),"")')
            calc.cell(sr, 15, f'=IF(J{sr}>1,K{sr}*(N{sr}^2),0)')
            calc.cell(sr, 16, f'=IF(J{sr}>1,VLOOKUP(J{sr},{tbl_ref},2,FALSE),"")')
            calc.cell(sr, 17, f'=IF(J{sr}>1,{_c4_excel(f"K{sr}")},"")')

    _text(calc, 1, 19, 'Metric')
    _text(calc, 1, 20, 'Formula')
    mean_expr = float(hist_mean) if hist_mean is not None else f'=AVERAGE(Inputs!D2:D{last})'
    if hist_stdev is not None:
        sd_overall_expr = float(hist_stdev)
    elif unbiased_overall:
        sd_overall_expr = f'=MAX(1E-9,STDEV(Inputs!D2:D{last})/{_c4_excel("$T$2-1")})'
    else:
        sd_overall_expr = f'=MAX(1E-9,STDEV(Inputs!D2:D{last}))'

    if max_size == 1:
        if est_eq1 == 'mmr':
            sd_within_expr = f'=MAX(1E-9,MEDIAN(F2:F{last})/{repr(float(_cap_d4(span_eff)))})'
        elif est_eq1 == 'srmssd':
            sd_within_expr = f'=MAX(1E-9,SQRT(SUM(G2:G{last})/(2*($T$2-1))))'
        else:
            sd_within_expr = f'=MAX(1E-9,AVERAGE(F2:F{last})/{repr(float(_cap_d2(span_eff)))})'
    elif est_gt1 == 'rbar':
        if min_size == max_size:
            sd_within_expr = f'=MAX(1E-9,AVERAGE(M2:M{last_sg})/{repr(float(_cap_d2(max_size)))})'
        else:
            sd_within_expr = f'=MAX(1E-9,SUM(M2:M{last_sg})/SUM(P2:P{last_sg}))'
    elif est_gt1 == 'sbar':
        if min_size == max_size:
            c4_const = _c4_excel(str(max_size - 1)) if unbiased_within else '1'
            sd_within_expr = f'=MAX(1E-9,AVERAGE(N2:N{last_sg})/{c4_const})'
        else:
            sd_within_expr = f'=MAX(1E-9,SUM(N2:N{last_sg})/SUM(Q2:Q{last_sg}))'
    else:
        c4_pool = _c4_excel(f'SUM(K2:K{last_sg})') if unbiased_within else '1'
        sd_within_expr = f'=MAX(1E-9,SQRT(SUM(O2:O{last_sg})/SUM(K2:K{last_sg}))/{c4_pool})'

    def _cap_formulas(sd_cell):
        p = f'=({repr(float(usl))}-{repr(float(lsl))})/({repr(tolerance_k)}*{sd_cell})' if (lsl is not None and usl is not None) else '=NA()'
        pl = f'=($T$3-{repr(float(lsl))})/({repr(half_k)}*{sd_cell})' if lsl is not None else '=NA()'
        pu = f'=({repr(float(usl))}-$T$3)/({repr(half_k)}*{sd_cell})' if usl is not None else '=NA()'
        if lsl is not None and usl is not None:
            pk = f'=MIN({pl[1:]},{pu[1:]})'
        elif lsl is not None:
            pk = pl
        else:
            pk = pu
        if target is not None:
            denom = f'(3*SQRT({sd_cell}^2+($T$3-{repr(float(target))})^2))'
            if lsl is not None and usl is not None:
                pm = f'=({repr(float(usl))}-{repr(float(lsl))})/(2*{denom})'
            elif lsl is not None:
                pm = f'=($T$3-{repr(float(lsl))})/{denom}'
            else:
                pm = f'=({repr(float(usl))}-$T$3)/{denom}'
        else:
            pm = '=NA()'
        pb = f'NORMSDIST(({repr(float(lsl))}-$T$3)/{sd_cell})' if lsl is not None else '0'
        pa = f'NORMSDIST(($T$3-{repr(float(usl))})/{sd_cell})' if usl is not None else '0'
        exp_rate = f'=({pb}+{pa})*{repr(scale_factor)}'
        return p, pl, pu, pk, pm, exp_rate

    cp_f, cpl_f, cpu_f, cpk_f, cpm_f, exp_w_f = _cap_formulas('$T$5')
    pp_f, ppl_f, ppu_f, ppk_f, _, exp_o_f = _cap_formulas('$T$4')
    obs_rate_f = f'=((SUM(D2:D{last})+SUM(E2:E{last}))/$T$2)*{repr(scale_factor)}'

    metric_rows = [
        ('Sample N', f'=COUNT(Inputs!D2:D{last})'),
        ('Mean', mean_expr),
        ('StDev (Overall)', sd_overall_expr),
        ('StDev (Within)', sd_within_expr),
        ('Cp', cp_f),
        ('CPL', cpl_f),
        ('CPU', cpu_f),
        ('Cpk', cpk_f),
        ('Cpm', cpm_f),
        ('Pp', pp_f),
        ('PPL', ppl_f),
        ('PPU', ppu_f),
        ('Ppk', ppk_f),
        ('Observed Total', obs_rate_f),
        ('Expected Within Total', exp_w_f),
        ('Expected Overall Total', exp_o_f),
    ]
    metric_cell_map = {}
    for r_idx, (m_label, m_formula) in enumerate(metric_rows, 2):
        _text(calc, r_idx, 19, m_label)
        calc.cell(r_idx, 20, m_formula)
        metric_cell_map[m_label] = f'Calculations!$T${r_idx}'

    # Live 10-bin histogram (columns V..Z)
    _text(calc, 1, 22, 'Bin Lower')
    _text(calc, 1, 23, 'Bin Upper')
    _text(calc, 1, 24, 'Bin Center')
    _text(calc, 1, 25, 'Frequency')
    _text(calc, 13, 22, 'Data Min')
    calc.cell(13, 23, f'=MIN(Inputs!D2:D{last})')
    _text(calc, 14, 22, 'Data Max')
    calc.cell(14, 23, f'=MAX(Inputs!D2:D{last})')
    _text(calc, 15, 22, 'Bin Width')
    calc.cell(15, 23, '=(W14-W13)/10')
    for b in range(10):
        r_idx = b + 2
        calc.cell(r_idx, 22, f'=$W$13+{b}*$W$15')
        calc.cell(r_idx, 23, f'=$W$13+{b + 1}*$W$15')
        calc.cell(r_idx, 24, f'=ROUND(0.5*(V{r_idx}+W{r_idx}),2)')
        upper_op = '<=' if b == 9 else '<'
        calc.cell(r_idx, 25, f'=COUNTIFS(Inputs!$D$2:$D${last},">="&V{r_idx},Inputs!$D$2:$D${last},"{upper_op}"&W{r_idx})')

    summary['B7'] = (
        f'=IFERROR(IF(AND(COUNT(Inputs!D2:D{last})={n_total},'
        f'MAX(Inputs!D2:D{last})>MIN(Inputs!D2:D{last})),'
        f'"Valid","Check inputs"),"Check inputs")'
    )

    unit_tag = '%' if display_unit == 'percent' else 'PPM'
    references = [
        ('Sample N', result['sample_n']),
        ('Mean', result['mean']),
        ('StDev (Within)', result['stdev_within']),
        ('StDev (Overall)', result['stdev_overall']),
    ]
    formulas = [
        metric_cell_map['Sample N'],
        metric_cell_map['Mean'],
        metric_cell_map['StDev (Within)'],
        metric_cell_map['StDev (Overall)'],
    ]
    index_labels = []
    for label, key in [
        ('Cp', 'cp'), ('CPL', 'cpl'), ('CPU', 'cpu'), ('Cpk', 'cpk'), ('Cpm', 'cpm'),
        ('Pp', 'pp'), ('PPL', 'ppl'), ('PPU', 'ppu'), ('Ppk', 'ppk'),
    ]:
        if result.get(key) is not None:
            references.append((label, result[key]))
            formulas.append(metric_cell_map[label])
            index_labels.append((label, metric_cell_map[label]))
    references.extend([
        (f'Observed Total ({unit_tag})', result['within_perf']['observed_total']),
        (f'Expected Within Total ({unit_tag})', result['within_perf']['expected_total']),
        (f'Expected Overall Total ({unit_tag})', result['overall_perf']['expected_total']),
    ])
    formulas.extend([
        metric_cell_map['Observed Total'],
        metric_cell_map['Expected Within Total'],
        metric_cell_map['Expected Overall Total'],
    ])

    # Capability index table for BarChart (columns AA..AB)
    _text(calc, 1, 27, 'Index')
    _text(calc, 1, 28, 'Calculated Value')
    for idx, (idx_label, ref_cell) in enumerate(index_labels, 2):
        _text(calc, idx, 27, idx_label)
        calc.cell(idx, 28, f'=IF(Verification!$B$7="Valid",{ref_cell},NA())')

    settings = [
        ('Worksheet', sheet.name),
        ('Variable', var_name),
        ('LSL', lsl if lsl is not None else 'None'),
        ('Target', target if target is not None else 'None'),
        ('USL', usl if usl is not None else 'None'),
        ('Tolerance K', tolerance_k),
        ('Display unit', display_unit),
        ('Within method', est_eq1 if max_size == 1 else est_gt1),
        ('Unbiased within', 'Yes' if unbiased_within else 'No'),
        ('Unbiased overall', 'Yes' if unbiased_overall else 'No'),
        ('Historical mean', hist_mean if hist_mean is not None else 'Estimated'),
        ('Historical stdev', hist_stdev if hist_stdev is not None else 'Estimated'),
    ]
    _populate_verification_table(summary, references, formulas, settings)

    hist = BarChart()
    hist.type = 'col'
    hist.title = f'Process Histogram: {var_name}'
    hist.x_axis.axPos = 'b'
    hist.x_axis.title = var_name
    hist.y_axis.title = 'Frequency'
    _style_chart_axis(hist.x_axis)
    _style_chart_axis(hist.y_axis)
    hist.legend = None
    hist.width, hist.height = 17, 9
    hist.add_data(Reference(calc, min_col=25, min_row=1, max_row=11), titles_from_data=True)
    hist.set_categories(Reference(calc, min_col=24, min_row=2, max_row=11))
    hist.series[0].graphicalProperties.solidFill = '25729C'
    summary.add_chart(hist, 'G10')

    if index_labels:
        cap_chart = BarChart()
        cap_chart.type = 'bar'
        cap_chart.title = 'Capability Indices'
        cap_chart.y_axis.axPos = 'b'
        cap_chart.y_axis.title = 'Index Value'
        _style_chart_axis(cap_chart.x_axis)
        _style_chart_axis(cap_chart.y_axis)
        cap_chart.legend = None
        cap_chart.width = 17
        cap_chart.height = max(9, min(25, len(index_labels) * 0.9))
        cap_chart.add_data(Reference(calc, min_col=28, min_row=1, max_row=1 + len(index_labels)), titles_from_data=True)
        cap_chart.set_categories(Reference(calc, min_col=27, min_row=2, max_row=1 + len(index_labels)))
        cap_chart.series[0].graphicalProperties.solidFill = '1B7F4B'
        summary.add_chart(cap_chart, 'G31')
    return workbook


def _build_attribute_workbook(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    params = entry['recipe']['parameters']
    result = entry['result']
    chart_type, var_name, size_name, attr_rows, opts = _extract_attribute_rows(sheet, params, result)
    if chart_type not in ('P', 'NP', 'C', 'U'):
        raise ValueError("Excel verification supports P, NP, C, and U attribute charts (use R Workbench for Laney P'/U').")
    n_rows = len(attr_rows)
    _check_budget(n_rows * 16, 20, n_rows)

    k_sigma = float(result.get('k_sigma', opts.get('k_sigma', 3.0)))
    display_upper = bool(result.get('display_upper', opts.get('display_upper', True)))
    display_lower = bool(result.get('display_lower', opts.get('display_lower', True)))
    is_historical = bool(result.get('is_historical', False))
    hist_val = opts.get('historical_p') if chart_type in ('P', 'NP') else opts.get('historical_mean')
    tests_cfg = result.get('tests_cfg') or opts.get('tests') or {}
    t1_cfg = tests_cfg.get('test1', {})
    t1_enabled = bool(t1_cfg.get('enabled', True))
    t1_k = float(t1_cfg.get('k', 3.0))

    workbook, summary, inputs, calc = _init_verification_sheets((
        f'Edit the blue values on Inputs to recalculate {chart_type} chart observations, limits, signals, and plot.',
        'Missing or incomplete baseline rows remain matched; invalid counts or sizes flag Check inputs.',
        'StatCraft reference values and saved settings are snapshots. Nelson rules 2-4 are outside this comparison.',
    ))

    _headers(inputs, 1, ('Worksheet row', 'In estimation', 'Count', 'Subgroup size'))
    inputs.freeze_panes = 'C2'
    for idx, (ws_row, c_val, s_val, in_est) in enumerate(attr_rows, 2):
        inputs.append([ws_row, in_est, c_val, s_val])
        inputs.cell(idx, 3).font = _EDITABLE_FONT
        if chart_type != 'C':
            inputs.cell(idx, 4).font = _EDITABLE_FONT
    last = n_rows + 1
    inputs.auto_filter.ref = f'A1:D{last}'

    _headers(calc, 1, (
        'Subgroup', 'Valid input', 'In estimation', 'Complete', 'Est Count', 'Est Size',
        'Obs', 'CL', 'Sigma', 'LCL', 'UCL', 'Test 1 Signal', 'CL Num', 'LCL Num', 'UCL Num',
    ))
    calc.freeze_panes = 'D2'

    _text(calc, 1, 17, 'Parameter')
    _text(calc, 1, 18, 'Value')
    param_formula = float(hist_val) if (is_historical and hist_val is not None) else f'=IF(SUM(F2:F{last})>0,SUM(E2:E{last})/SUM(F2:F{last}),0)'
    valid_attr_expr = (
        f'=IFERROR(IF(AND(MIN(B2:B{last})=1,$R$3>=1),1,0),0)'
        if is_historical
        else f'=IFERROR(IF(AND(MIN(B2:B{last})=1,$R$3>=1,SUM(F2:F{last})>0),1,0),0)'
    )
    scalar_rows = [
        ('k_sigma', k_sigma),
        ('Complete Subgroups', f'=SUM(D2:D{last})'),
        ('Center (Param)', param_formula),
        ('Test 1 Signals', f'=SUM(L2:L{last})'),
        ('Inputs Valid', valid_attr_expr),
    ]
    for r_idx, (pname, pval) in enumerate(scalar_rows, 2):
        _text(calc, r_idx, 17, pname)
        calc.cell(r_idx, 18, pval)

    for r_idx, (ws_row, c_val, s_val, in_est) in enumerate(attr_rows, 2):
        calc.cell(r_idx, 1, f'=Inputs!A{r_idx}')
        complete_cond = f'AND(ISNUMBER(Inputs!C{r_idx}),Inputs!C{r_idx}>=0,ISNUMBER(Inputs!D{r_idx}),Inputs!D{r_idx}>0'
        if chart_type in ('P', 'NP'):
            complete_cond += f',Inputs!C{r_idx}<=Inputs!D{r_idx})'
        else:
            complete_cond += ')'
        if c_val is not None and s_val is not None:
            valid_formula = f'=IF({complete_cond},1,0)'
        else:
            c_blank_or_num = f'ISBLANK(Inputs!C{r_idx})' if c_val is None else f'AND(ISNUMBER(Inputs!C{r_idx}),Inputs!C{r_idx}>=0)'
            s_blank_or_pos = f'ISBLANK(Inputs!D{r_idx})' if s_val is None else f'AND(ISNUMBER(Inputs!D{r_idx}),Inputs!D{r_idx}>0)'
            valid_formula = f'=IF(OR({complete_cond},AND({c_blank_or_num},{s_blank_or_pos})),1,0)'
        calc.cell(r_idx, 2, valid_formula)
        calc.cell(r_idx, 3, f'=Inputs!B{r_idx}')
        calc.cell(r_idx, 4, f'=IF(AND(ISNUMBER(Inputs!C{r_idx}),ISNUMBER(Inputs!D{r_idx}),Inputs!D{r_idx}>0),1,0)')
        calc.cell(r_idx, 5, f'=IF(AND(C{r_idx},D{r_idx}=1),Inputs!C{r_idx},0)')
        calc.cell(r_idx, 6, f'=IF(AND(C{r_idx},D{r_idx}=1),Inputs!D{r_idx},0)')

        if chart_type in ('P', 'U'):
            obs_expr = f'Inputs!C{r_idx}/Inputs!D{r_idx}'
        else:
            obs_expr = f'Inputs!C{r_idx}'
        calc.cell(r_idx, 7, f'=IF(AND($R$6=1,D{r_idx}=1),{obs_expr},NA())')

        if chart_type == 'NP':
            cl_expr = f'Inputs!D{r_idx}*$R$4'
            sig_expr = f'IF($R$4*(1-$R$4)>0,SQRT(Inputs!D{r_idx}*$R$4*(1-$R$4)),0)'
            ucl_expr = f'MIN(Inputs!D{r_idx},H{r_idx}+$R$2*I{r_idx})'
        elif chart_type == 'P':
            cl_expr = '$R$4'
            sig_expr = f'IF($R$4*(1-$R$4)>0,SQRT($R$4*(1-$R$4)/Inputs!D{r_idx}),0)'
            ucl_expr = f'MIN(1,H{r_idx}+$R$2*I{r_idx})'
        elif chart_type == 'C':
            cl_expr = '$R$4'
            sig_expr = 'IF($R$4>0,SQRT($R$4),0)'
            ucl_expr = f'H{r_idx}+$R$2*I{r_idx}'
        else:
            cl_expr = '$R$4'
            sig_expr = f'IF($R$4>0,SQRT($R$4/Inputs!D{r_idx}),0)'
            ucl_expr = f'H{r_idx}+$R$2*I{r_idx}'

        calc.cell(r_idx, 8, f'=IF(AND($R$6=1,D{r_idx}=1),{cl_expr},NA())')
        calc.cell(r_idx, 9, f'=IF(D{r_idx}=1,{sig_expr},NA())')
        calc.cell(r_idx, 10, f'=IF(AND($R$6=1,D{r_idx}=1),MAX(0,H{r_idx}-$R$2*I{r_idx}),NA())' if display_lower else '=NA()')
        calc.cell(r_idx, 11, f'=IF(AND($R$6=1,D{r_idx}=1),{ucl_expr},NA())' if display_upper else '=NA()')
        if t1_enabled:
            calc.cell(r_idx, 12, f'=IF(AND(D{r_idx}=1,ISNUMBER(I{r_idx}),I{r_idx}>0),IF(ABS(G{r_idx}-H{r_idx})>{repr(t1_k)}*I{r_idx},1,0),0)')
        else:
            calc.cell(r_idx, 12, 0)
        calc.cell(r_idx, 13, f'=IF(ISNUMBER(H{r_idx}),H{r_idx},"")')
        calc.cell(r_idx, 14, f'=IF(ISNUMBER(J{r_idx}),J{r_idx},"")')
        calc.cell(r_idx, 15, f'=IF(ISNUMBER(K{r_idx}),K{r_idx},"")')

    summary['B7'] = '=IF(Calculations!$R$6=1,"Valid","Check inputs")'

    cl_vals = [v for v in result['center_lines'] if v is not None]
    lcl_vals = [v for v in result['lcl'] if v is not None]
    ucl_vals = [v for v in result['ucl'] if v is not None]
    references = [
        ('Complete Subgroups', result['n_subgroups']),
        ('Center (Param)', result['center']),
    ]
    formulas = [
        'Calculations!$R$3',
        'Calculations!$R$4',
    ]
    if cl_vals:
        references.extend([('Min CL', min(cl_vals)), ('Max CL', max(cl_vals))])
        formulas.extend([f'MIN(Calculations!M2:M{last})', f'MAX(Calculations!M2:M{last})'])
    if lcl_vals:
        references.extend([('Min LCL', min(lcl_vals)), ('Max LCL', max(lcl_vals))])
        formulas.extend([f'MIN(Calculations!N2:N{last})', f'MAX(Calculations!N2:N{last})'])
    if ucl_vals:
        references.extend([('Min UCL', min(ucl_vals)), ('Max UCL', max(ucl_vals))])
        formulas.extend([f'MIN(Calculations!O2:O{last})', f'MAX(Calculations!O2:O{last})'])
    references.append(('Test 1 Signals', len(result.get('signals', []))))
    formulas.append('Calculations!$R$5')

    settings = [
        ('Worksheet', sheet.name),
        ('Chart type', f'{chart_type} Chart'),
        ('Variable', var_name),
        ('Subgroup size', size_name),
        ('K sigma', k_sigma),
        ('Omitted subgroups', ', '.join(map(str, result.get('omitted_subgroups', []))) or 'None'),
        ('Excluded rows', ', '.join(map(str, result.get('excluded_rows', []))) or 'None'),
        ('Historical parameter', hist_val if (is_historical and hist_val is not None) else 'Estimated'),
    ]
    _populate_verification_table(summary, references, formulas, settings)

    y_title = 'Proportion' if chart_type == 'P' else ('Defective Count' if chart_type == 'NP' else ('Defects' if chart_type == 'C' else 'Defects per Unit'))
    _add_control_chart(
        summary, 'G10', f'{chart_type} Chart: {var_name}', y_title, calc, 1, last,
        [
            (7, '25729C', False, True),
            (8, '1B7F4B', False, False),
            (10 if display_lower else None, 'C0392B', True, False),
            (11 if display_upper else None, 'C0392B', True, False),
        ],
    )
    return workbook


def _build_gage_rr_workbook(presenter, entry):
    sheet = presenter.result_worksheet(entry)
    params = entry['recipe']['parameters']
    result = entry['result']
    indices = [params['measurement_index'], params['part_index'], params['operator_index']]
    if any(not isinstance(i, int) or i < 0 or i >= len(sheet.columns) for i in indices) or len(set(indices)) != 3:
        raise ValueError('The saved Gage R&R measurement, part, or operator column is unavailable.')
    m_col, p_col, o_col = [sheet.columns[i] for i in indices]
    if m_col.kind != 'number' or any(c.kind not in ('number', 'text') for c in (p_col, o_col)):
        raise ValueError('Gage R&R measurement must be numeric; parts and operators must be numeric or text.')

    row_indices = list(result['row_indices'])
    parts = list(result['parts'])
    operators = list(result['operators'])
    p_cnt, q_cnt, repeats = len(parts), len(operators), int(result['repeats'])
    n_obs = len(row_indices)
    _check_budget(n_obs * 15, 24, n_obs)

    part_id_map = {str(val): idx for idx, val in enumerate(parts, 1)}
    op_id_map = {str(val): idx for idx, val in enumerate(operators, 1)}

    workbook, summary, inputs, calc = _init_verification_sheets((
        'Edit the blue measurement cells on Inputs to recalculate ANOVA, variance components, %StudyVar, and charts.',
        'Part and operator assignments preserve the balanced crossed design from the saved study.',
        'StatCraft reference values and saved settings are snapshots from the time of export.',
    ))

    _headers(inputs, 1, ('Worksheet row', p_col.name, o_col.name, m_col.name))
    inputs.freeze_panes = 'D2'

    opts = result.get('options', result.get('settings', {}))
    study_mult = float(opts.get('study_multiplier', 6.0))
    tolerance = opts.get('tolerance')
    process_stdev = opts.get('process_stdev')
    interaction_alpha = float(opts.get('interaction_alpha', 0.05))
    remove_interaction = bool(opts.get('remove_interaction', True))

    _headers(calc, 1, (
        'Worksheet row', 'Part ID', 'Op ID', 'Cell ID', 'Centered Meas',
        'Part Mean', 'Op Mean', 'Cell Mean', 'Part Dev Sq', 'Op Dev Sq', 'Int Dev Sq', 'Err Dev Sq', 'Tot Dev Sq',
    ))
    calc.freeze_panes = 'E2'
    last = n_obs + 1

    for r_idx, ws_idx in enumerate(row_indices, 2):
        if ws_idx >= len(m_col.values) or ws_idx >= len(p_col.values) or ws_idx >= len(o_col.values):
            raise ValueError('The worksheet no longer contains all analyzed Gage R&R rows.')
        mv = normalize_numeric(m_col.values[ws_idx])
        pv = p_col.values[ws_idx]
        ov = o_col.values[ws_idx]
        if mv is None or not math.isfinite(float(mv)) or pv is None or ov is None:
            raise ValueError('Analyzed Gage R&R rows contain missing values; rerun first.')
        pid = part_id_map[str(pv)]
        oid = op_id_map[str(ov)]
        cid = (pid - 1) * q_cnt + oid

        inputs.append([ws_idx + 1, str(pv), str(ov), float(mv)])
        inputs.cell(r_idx, 4).font = _EDITABLE_FONT

        calc.cell(r_idx, 1, f'=Inputs!A{r_idx}')
        calc.cell(r_idx, 2, pid)
        calc.cell(r_idx, 3, oid)
        calc.cell(r_idx, 4, cid)
        calc.cell(r_idx, 5, f'=Inputs!D{r_idx}-Inputs!$D$2')
        calc.cell(r_idx, 6, f'=AVERAGEIF($B$2:$B${last},B{r_idx},$E$2:$E${last})')
        calc.cell(r_idx, 7, f'=AVERAGEIF($C$2:$C${last},C{r_idx},$E$2:$E${last})')
        calc.cell(r_idx, 8, f'=AVERAGEIF($D$2:$D${last},D{r_idx},$E$2:$E${last})')
        calc.cell(r_idx, 9, f'=(F{r_idx}-$P$2)^2')
        calc.cell(r_idx, 10, f'=(G{r_idx}-$P$2)^2')
        calc.cell(r_idx, 11, f'=(H{r_idx}-F{r_idx}-G{r_idx}+$P$2)^2')
        calc.cell(r_idx, 12, f'=(E{r_idx}-H{r_idx})^2')
        calc.cell(r_idx, 13, f'=(E{r_idx}-$P$2)^2')
    inputs.auto_filter.ref = f'A1:D{last}'

    _text(calc, 1, 15, 'Parameter')
    _text(calc, 1, 16, 'Value')
    scalar_rows = [
        ('Grand Mean (Centered)', f'=AVERAGE(E2:E{last})'),
        ('Parts (p)', p_cnt),
        ('Operators (q)', q_cnt),
        ('Replicates (r)', repeats),
        ('Study Multiplier', study_mult),
        ('Remove Interaction', remove_interaction),
        ('Interaction Alpha', interaction_alpha),
        ('Tolerance', float(tolerance) if tolerance is not None else '=NA()'),
        ('Process StDev', float(process_stdev) if process_stdev is not None else '=NA()'),
        ('SS Part', f'=SUM(I2:I{last})'),
        ('SS Operator', f'=SUM(J2:J{last})'),
        ('SS Interaction', f'=SUM(K2:K{last})'),
        ('SS Repeatability', f'=SUM(L2:L{last})'),
        ('SS Total', f'=SUM(M2:M{last})'),
        ('MS Part', '=P11/(P3-1)'),
        ('MS Operator', '=P12/(P4-1)'),
        ('MS Interaction', '=P13/((P3-1)*(P4-1))'),
        ('MS Repeatability', '=P14/(P3*P4*(P5-1))'),
        ('Interaction P-value', '=IF(P19>0,IF(P18<=0,1,FDIST(P18/P19,(P3-1)*(P4-1),P3*P4*(P5-1))),IF(P18>0,0,NA()))'),
        ('Pool Interaction', '=IF(AND(P7,ISNUMBER(P20),P20>=P8),TRUE,FALSE)'),
        ('Error Denom MS', '=IF(P21,(P13+P14)/((P3-1)*(P4-1)+P3*P4*(P5-1)),P18)'),
        ('Repeatability Var', '=IF(P21,P22,P19)'),
        ('Interaction Var', '=IF(P21,0,MAX(0,(P18-P19)/P5))'),
        ('Operator Var', '=MAX(0,(P17-P22)/(P3*P5))'),
        ('Part-To-Part Var', '=MAX(0,(P16-P22)/(P4*P5))'),
        ('Reproducibility Var', '=P25+P24'),
        ('Total Gage R&R Var', '=P23+P27'),
        ('Total Variation', '=P28+P26'),
        ('NDC', '=IF(P28>0,MAX(1,INT(1.41*SQRT(P26)/SQRT(P28))),IF(P26=0,1,NA()))'),
    ]
    for r_idx, (pname, pval) in enumerate(scalar_rows, 2):
        _text(calc, r_idx, 15, pname)
        calc.cell(r_idx, 16, pval)

    # Chart summary table 1: Components of Variation (R..T)
    _text(calc, 1, 18, 'Component')
    _text(calc, 1, 19, '%Contribution')
    _text(calc, 1, 20, '%Study Var')
    for offset, (cname, vcell) in enumerate([
        ('Total Gage R&R', 'P28'),
        ('Repeatability', 'P23'),
        ('Reproducibility', 'P27'),
        ('Part-To-Part', 'P26'),
    ], 2):
        _text(calc, offset, 18, cname)
        calc.cell(offset, 19, f'=IF(Verification!$B$7="Valid",IF($P$29>0,100*{vcell}/$P$29,0),NA())')
        calc.cell(offset, 20, f'=IF(Verification!$B$7="Valid",IF($P$29>0,100*SQRT({vcell})/SQRT($P$29),0),NA())')

    # Chart summary table 2: Mean by Part (V..W)
    _text(calc, 1, 22, p_col.name)
    _text(calc, 1, 23, f'Mean ({m_col.name})')
    for pid, pval in enumerate(parts, 1):
        r_idx = pid + 1
        _text(calc, r_idx, 22, str(pval))
        calc.cell(r_idx, 23, f'=IF(Verification!$B$7="Valid",AVERAGEIF($B$2:$B${last},{pid},$E$2:$E${last})+Inputs!$D$2,NA())')

    summary['B7'] = f'=IFERROR(IF(COUNT(Inputs!D2:D{last})={n_obs},"Valid","Check inputs"),"Check inputs")'

    anova_full = {row['source']: row for row in result['anova_with_interaction']}
    vc_map = {row['source']: row for row in result['variance_components']}
    references = [
        ('SS Part', anova_full['Part']['ss']),
        ('SS Operator', anova_full['Operator']['ss']),
        ('SS Interaction', anova_full['Part * Operator']['ss']),
        ('SS Repeatability', anova_full['Repeatability']['ss']),
    ]
    formulas = [
        'Calculations!$P$11',
        'Calculations!$P$12',
        'Calculations!$P$13',
        'Calculations!$P$14',
    ]
    for src, v_cell in [
        ('Total Gage R&R', 'P28'),
        ('Repeatability', 'P23'),
        ('Reproducibility', 'P27'),
        ('Operator', 'P25'),
        ('Part * Operator', 'P24'),
        ('Part-To-Part', 'P26'),
        ('Total Variation', 'P29'),
    ]:
        if src not in vc_map:
            continue
        row = vc_map[src]
        references.append((f'{src} Var', row['variance']))
        formulas.append(f'Calculations!${v_cell[0]}${v_cell[1:]}')
        references.append((f'{src} StudyVar', row['study_variation']))
        formulas.append(f'Calculations!$P$6*SQRT(Calculations!${v_cell[0]}${v_cell[1:]})')
        if row.get('percent_study_variation') is not None:
            references.append((f'{src} %StudyVar', row['percent_study_variation']))
            formulas.append(f'100*SQRT(Calculations!${v_cell[0]}${v_cell[1:]})/SQRT(Calculations!$P$29)')
        if tolerance is not None and row.get('percent_tolerance') is not None:
            references.append((f'{src} %Tol', row['percent_tolerance']))
            formulas.append(f'100*Calculations!$P$6*SQRT(Calculations!${v_cell[0]}${v_cell[1:]})/Calculations!$P$9')
        if process_stdev is not None and row.get('percent_process') is not None:
            references.append((f'{src} %Process', row['percent_process']))
            formulas.append(f'100*SQRT(Calculations!${v_cell[0]}${v_cell[1:]})/Calculations!$P$10')
    if result.get('ndc') is not None:
        references.append(('NDC', result['ndc']))
        formulas.append('Calculations!$P$30')

    settings = [
        ('Worksheet', sheet.name),
        ('Measurement', m_col.name),
        ('Part factor', f'{p_col.name} ({p_cnt})'),
        ('Operator factor', f'{o_col.name} ({q_cnt})'),
        ('Replicates', repeats),
        ('Study multiplier', study_mult),
        ('Interaction pooled', 'Yes' if result['interaction']['pooled'] else 'No'),
        ('Interaction alpha', interaction_alpha),
        ('Tolerance', tolerance if tolerance is not None else 'None'),
        ('Process StDev', process_stdev if process_stdev is not None else 'None'),
    ]
    _populate_verification_table(summary, references, formulas, settings)

    comp_chart = BarChart()
    comp_chart.type = 'col'
    comp_chart.grouping = 'clustered'
    comp_chart.title = f'Components of Variation: {m_col.name}'
    comp_chart.x_axis.axPos = 'b'
    comp_chart.x_axis.title = 'Source'
    comp_chart.y_axis.title = 'Percent (%)'
    _style_chart_axis(comp_chart.x_axis)
    _style_chart_axis(comp_chart.y_axis)
    comp_chart.legend.position = 'b'
    comp_chart.legend.overlay = False
    comp_chart.width, comp_chart.height = 17, 9
    comp_chart.add_data(Reference(calc, min_col=19, max_col=20, min_row=1, max_row=5), titles_from_data=True)
    comp_chart.set_categories(Reference(calc, min_col=18, min_row=2, max_row=5))
    comp_chart.series[0].graphicalProperties.solidFill = '25729C'
    if len(comp_chart.series) > 1:
        comp_chart.series[1].graphicalProperties.solidFill = 'B45309'
    summary.add_chart(comp_chart, 'G10')

    part_chart = LineChart()
    part_chart.smooth = False
    part_chart.title = f'Mean {m_col.name} by {p_col.name}'
    part_chart.x_axis.axPos = 'b'
    part_chart.x_axis.title = p_col.name
    part_chart.y_axis.title = m_col.name
    _style_chart_axis(part_chart.x_axis)
    _style_chart_axis(part_chart.y_axis)
    part_chart.legend = None
    part_chart.width, part_chart.height = 17, 9
    part_chart.add_data(Reference(calc, min_col=23, min_row=1, max_row=1 + p_cnt), titles_from_data=True)
    part_chart.set_categories(Reference(calc, min_col=22, min_row=2, max_row=1 + p_cnt))
    ps = part_chart.series[0]
    ps.smooth = False
    _style_line_series(ps, '25729C', dashed=False)
    ps.marker.symbol = 'circle'
    ps.marker.size = 5
    ps.marker.graphicalProperties.solidFill = '25729C'
    summary.add_chart(part_chart, 'G31')
    return workbook


def build_workbook(presenter, entry):
    """Build an editable workbook with fixed membership of the originally analyzed rows."""
    if isinstance(entry, dict) and entry.get('recipe', {}).get('action') == 'attribute_control_chart':
        result = entry.get('result', {})
        ct = str(result.get('chart_type', result.get('chart', ''))).upper().strip().replace('′', "'")
        if ct in ("P'", "U'"):
            raise ValueError("Excel verification supports P, NP, C, and U attribute charts (use R Workbench for Laney P'/U').")
    if not supports(entry):
        raise ValueError(
            'Excel verification supports continuous main-effects regression, two-level factorial DOE, '
            'I-MR, Xbar-R/S, Attribute (P/NP/C/U), Normal Capability, and Crossed Gage R&R.'
        )
    if presenter.result_stale(entry) is not False:
        raise ValueError('Rerun the result on its source worksheet before exporting verification inputs.')

    action = entry['recipe']['action']
    if action == 'imr_chart':
        return _build_imr_workbook(presenter, entry)
    if action == 'subgroup_control_chart':
        return _build_subgroup_workbook(presenter, entry)
    if action == 'attribute_control_chart':
        return _build_attribute_workbook(presenter, entry)
    if action == 'normal_capability':
        return _build_capability_workbook(presenter, entry)
    if action == 'gage_rr':
        return _build_gage_rr_workbook(presenter, entry)
    return _build_ols_workbook(presenter, entry)


def write_verification(path, presenter, entry):
    """Write atomically so an interrupted export cannot replace a workbook."""
    path = Path(path)
    if path.suffix.lower() != '.xlsx':
        raise ValueError('Excel workbooks use the .xlsx extension.')
    workbook = build_workbook(presenter, entry)
    handle, temporary = tempfile.mkstemp(prefix='.statcraft-verify-', suffix='.xlsx', dir=path.parent)
    os.close(handle)
    try:
        workbook.save(temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path
