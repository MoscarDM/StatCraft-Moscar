"""Recover explicit refit setups from observed native MPX model state.

Only declarative, unweighted, untransformed OLS models (response-surface,
2-level factorial/screening, and general linear model / ANOVA) are accepted.
Native command/history text is never interpreted or executed.
Saved reports remain separate immutable snapshots. All column joins use native
UUIDs and saved internal variable IDs, never names or current C positions.
"""
import copy
import itertools
import math
from .native_mpx_outputs import _Reader
from .glm import settings, validate_terms as validate_glm_terms
from .response_surface import validate_terms

MAX_MODELS=100
_RSM_TYPES = ('ResponseSurfaceRegression',)
_FACTORIAL_TYPES = ('FractionalFactorial', 'FactorialRegression', 'ScreeningRegression', 'TwoLevelFactorial')
_GLM_TYPES = ('GeneralLinearModel', 'GeneralFactorial', 'OneWayAnova', 'OneWayANOVA')
_BINARY_LOGISTIC_TYPES = ('BinaryLogisticRegression', 'LogisticRegression')
_ORDINAL_LOGISTIC_TYPES = ('OrdinalLogisticRegression',)
_NOMINAL_LOGISTIC_TYPES = ('NominalLogisticRegression',)
_POISSON_TYPES = ('PoissonRegression',)
_RELIABILITY_TYPES = ('DistributionAnalysis', 'ParametricDistributionAnalysis')
_ARIMA_TYPES = ('ARIMA', 'BoxJenkinsARIMA')
_MIXED_TYPES = ('MixedEffectsModel', 'MixedModel')
_FAMILY_MAP = {
    **{t: 'response_surface' for t in _RSM_TYPES},
    **{t: 'factorial' for t in _FACTORIAL_TYPES},
    **{t: 'general_linear_model' for t in _GLM_TYPES},
    **{t: 'binary_logistic' for t in _BINARY_LOGISTIC_TYPES},
    **{t: 'ordinal_logistic' for t in _ORDINAL_LOGISTIC_TYPES},
    **{t: 'nominal_logistic' for t in _NOMINAL_LOGISTIC_TYPES},
    **{t: 'poisson_regression' for t in _POISSON_TYPES},
    **{t: 'reliability_distribution' for t in _RELIABILITY_TYPES},
    **{t: 'arima' for t in _ARIMA_TYPES},
    **{t: 'mixed_reml' for t in _MIXED_TYPES},
}
_MODEL_TYPE_MAP = {
    'response_surface_regression': 'response_surface',
    'factorial_regression': 'factorial',
    'fractional_factorial': 'factorial',
    'screening_regression': 'factorial',
    'two_level_factorial': 'factorial',
    'general_linear_model': 'general_linear_model',
    'general_factorial': 'general_linear_model',
    'one_way_anova': 'general_linear_model',
    'anova': 'general_linear_model',
    'binary_logistic_regression': 'binary_logistic',
    'logistic_regression': 'binary_logistic',
    'binary_logistic': 'binary_logistic',
    'ordinal_logistic_regression': 'ordinal_logistic',
    'ordinal_logistic': 'ordinal_logistic',
    'nominal_logistic_regression': 'nominal_logistic',
    'nominal_logistic': 'nominal_logistic',
    'poisson_regression': 'poisson_regression',
    'poisson': 'poisson_regression',
    'distribution_analysis': 'reliability_distribution',
    'parametric_distribution_analysis': 'reliability_distribution',
    'reliability_distribution': 'reliability_distribution',
    'arima': 'arima',
    'box_jenkins_arima': 'arima',
    'mixed_effects_model': 'mixed_reml',
    'mixed_model': 'mixed_reml',
    'mixed_reml': 'mixed_reml',
}
_OBJ_TYPE_MAP = {
    'response_surface': 'response_surface',
    'factorial': 'factorial',
    'two_level_factorial': 'factorial',
    'fractional_factorial': 'factorial',
    'screening': 'factorial',
    'doe_factorial': 'factorial',
    'general_linear_model': 'general_linear_model',
    'glm': 'general_linear_model',
    'general_factorial': 'general_linear_model',
    'one_way_anova': 'general_linear_model',
    'anova': 'general_linear_model',
    'binary_logistic': 'binary_logistic',
    'binary_logistic_regression': 'binary_logistic',
    'logistic_regression': 'binary_logistic',
    'ordinal_logistic': 'ordinal_logistic',
    'ordinal_logistic_regression': 'ordinal_logistic',
    'nominal_logistic': 'nominal_logistic',
    'nominal_logistic_regression': 'nominal_logistic',
    'poisson_regression': 'poisson_regression',
    'poisson': 'poisson_regression',
    'distribution_analysis': 'reliability_distribution',
    'parametric_distribution_analysis': 'reliability_distribution',
    'reliability_distribution': 'reliability_distribution',
    'arima': 'arima',
    'box_jenkins_arima': 'arima',
    'mixed_effects_model': 'mixed_reml',
    'mixed_model': 'mixed_reml',
    'mixed_reml': 'mixed_reml',
}


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and abs(value)<1e29


def _integer(value,label):
    if not _number(value) or int(value)!=value:raise ValueError('Invalid saved '+label+'.')
    return int(value)


def _dict(value,label):
    if not isinstance(value,dict):raise ValueError('Missing or malformed saved '+label+'.')
    return value


def _items(value,label,maximum):
    if not isinstance(value,list) or len(value)>maximum:raise ValueError('Missing or malformed saved '+label+'.')
    return value


def _source_columns(sheet):
    found={}
    for index,column in enumerate(sheet.columns):
        raw=column.metadata.get('imported_variable_metadata',{})
        identity=raw.get('Id') if isinstance(raw,dict) else None
        if isinstance(identity,str) and identity:
            if identity in found:raise ValueError('Ambiguous duplicate native column identity in the worksheet.')
            found[identity]=index
    return found


def _validate_factorial_terms(terms, count):
    if not isinstance(terms, list) or not 1 <= len(terms) <= 64:
        raise ValueError('Select 1–64 factorial model terms.')
    seen = set()
    for term in terms:
        if not isinstance(term, list) or not 1 <= len(term) <= 3 or any(type(i) is not int or not 0 <= i < count for i in term) or term != sorted(set(term)):
            raise ValueError('Factorial model terms must contain distinct factors in order, up to three-way interactions.')
        key = tuple(term)
        if key in seen:
            raise ValueError('A factorial model term was selected more than once.')
        seen.add(key)
    for term in seen:
        for size in range(1, len(term)):
            if any(sub not in seen for sub in itertools.combinations(term, size)):
                raise ValueError('Keep all lower-order terms for a hierarchical factorial model.')
    return terms


def _decode_var_ref(sheet, sources, variable, allowed_vtypes, seen_ids, seen_internal):
    variable = _dict(variable, 'variable reference')
    identity = variable.get('id')
    if not isinstance(identity, str) or identity not in sources:
        raise ValueError('A saved model column identity is unavailable in its worksheet.')
    if identity in seen_ids:
        raise ValueError('Saved model variables must have distinct column identities.')
    internal_id = _integer(variable.get('variable_id'), 'variable identity')
    if internal_id in seen_internal:
        raise ValueError('Ambiguous saved internal variable identity.')
    index = sources[identity]
    vtype = variable.get('type')
    if vtype not in allowed_vtypes:
        raise ValueError('The native model contains an unsupported variable type.')
    expected_dtype = 'text' if sheet.columns[index].kind == 'text' else 'numeric'
    if variable.get('data_type') != expected_dtype:
        raise ValueError('The source data type conflicts with its saved native variable type.')
    if vtype == 'continuous' and sheet.columns[index].kind != 'number':
        raise ValueError('The source column type no longer matches its saved model role.')
    if vtype == 'categorical' and sheet.columns[index].kind not in ('number', 'text'):
        raise ValueError('The source column type no longer matches its saved model role.')
    seen_ids.append(identity)
    seen_internal[internal_id] = identity
    return index, identity, internal_id, vtype


def _decode_reliability(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family):
    if set(variables) - {'target', 'censor'} or 'target' not in variables:
        raise ValueError('The native reliability model uses unsupported variable roles.')
    seen_ids = []
    seen_internal = {}
    resp_idx, resp_id, _, _ = _decode_var_ref(sheet, sources, variables['target'], ('continuous',), seen_ids, seen_internal)
    censor_idx, censor_id = None, None
    if 'censor' in variables:
        censor_idx, censor_id, _, _ = _decode_var_ref(sheet, sources, variables['censor'], ('continuous', 'categorical'), seen_ids, seen_internal)
    state = _dict(_dict(model.get('model_information'), 'model information').get('input_state'), 'input state')
    obj = _dict(_dict(model.get('post_analysis_data'), 'post-analysis data').get('model_object'), 'model object')
    if _OBJ_TYPE_MAP.get(obj.get('model_object_type')) != expected_family or _OBJ_TYPE_MAP.get(obj.get('model_analysis_type')) != expected_family:
        raise ValueError('Unsupported native post-analysis reliability model.')
    if state.get('has_weights') is True or obj.get('has_weights') is True or obj.get('weights_column_id') not in (None, 0, 0.0):
        raise ValueError('Native weighted reliability models are not supported for this refit.')
    if state.get('has_threshold') is True or obj.get('has_threshold') is True or obj.get('threshold') not in (None, 0, 0.0):
        raise ValueError('Three-parameter threshold reliability models are not supported for this refit.')
    for src in (state, obj):
        ctype = src.get('censoring_type')
        if ctype is not None and str(ctype).lower() not in ('none', 'right'):
            raise ValueError('Only right-censored or uncensored reliability models are supported.')
        if src.get('has_interval_censoring') is True or src.get('is_arbitrary_censoring') is True:
            raise ValueError('Arbitrary or interval censoring is not supported for this refit.')
        est = src.get('estimation_method')
        if est is not None and str(est).lower() != 'mle':
            raise ValueError('Only MLE reliability estimation is supported for this refit.')
    dist_raw = state.get('distribution') or obj.get('distribution')
    if not isinstance(dist_raw, str) or dist_raw.lower() not in ('weibull', 'lognormal', 'normal', 'exponential'):
        raise ValueError('Unsupported reliability distribution for refitting.')
    dist_name = dist_raw.lower()
    if state.get('confidence_interval', 'two_sided') != 'two_sided':
        raise ValueError('Native one-sided reliability intervals are not supported here.')
    confidence = state.get('confidence', 0.95)
    if not _number(confidence) or not 0 < confidence < 1 or (obj.get('confidence') is not None and confidence != obj.get('confidence')):
        raise ValueError('Native confidence settings are invalid or inconsistent.')
    rows = _dict(_dict(obj.get('rows_to_use'), 'row selection').get('rows'), 'row selection')
    if rows.get('use_all_rows') is not True:
        raise ValueError('Native row-subset models need a supported row-selection workflow before refitting.')
    settings_dict = {'column_index': resp_idx, 'dist_name': dist_name, 'confidence_level': float(confidence)}
    source_column_ids = {'response': resp_id}
    if censor_idx is not None:
        settings_dict['censor_index'] = censor_idx
        source_column_ids['censor'] = censor_id
        censor_val = state.get('censor_value') if state.get('censor_value') is not None else obj.get('censor_value')
        if censor_val is not None:
            settings_dict['censor_value'] = censor_val
    recipe = {'action': 'reliability_distribution', 'parameters': {'settings': settings_dict}}
    from .recipes import columns
    columns(recipe)
    params_ref = _dict(obj.get('parameters', obj.get('distribution_parameters', {})), 'reliability parameters')
    if not params_ref or not all(_number(v) for v in params_ref.values()):
        raise ValueError('Invalid saved reliability parameter estimates.')
    ll = obj.get('log_likelihood')
    mttf = obj.get('mttf')
    if (ll is not None and not _number(ll)) or (mttf is not None and not _number(mttf)):
        raise ValueError('Invalid saved reliability summary statistics.')
    verification_ref = {
        'parameters': {k: float(v) for k, v in params_ref.items()},
        'log_likelihood': float(ll) if ll is not None else None,
        'mttf': float(mttf) if mttf is not None else None,
        'row_count': _integer(rows.get('row_count'), 'saved row count'),
    }
    return {
        'supported': True, 'family': expected_family, 'command_id': cid, 'worksheet_id': wid,
        'worksheet_name': sheet.name, 'model_id': model_id, 'model_uri': uri, 'recipe': recipe,
        'source_column_map': {str(idx): ident for idx, ident in zip([resp_idx] + ([censor_idx] if censor_idx is not None else []), seen_ids)},
        'source_column_ids': source_column_ids,
        'verification_reference': verification_ref,
        'warnings': ['Refit is an independent StatCraft calculation using current worksheet values; saved native output remains unchanged.'],
    }


def _decode_arima(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family):
    if set(variables) - {'target', 'series'} or not ('target' in variables or 'series' in variables):
        raise ValueError('The native ARIMA model uses unsupported or exogenous variable roles.')
    target_var = variables['target'] if 'target' in variables else variables['series']
    seen_ids = []
    seen_internal = {}
    resp_idx, resp_id, _, _ = _decode_var_ref(sheet, sources, target_var, ('continuous',), seen_ids, seen_internal)
    state = _dict(_dict(model.get('model_information'), 'model information').get('input_state'), 'input state')
    obj = _dict(_dict(model.get('post_analysis_data'), 'post-analysis data').get('model_object'), 'model object')
    if _OBJ_TYPE_MAP.get(obj.get('model_object_type')) != expected_family or _OBJ_TYPE_MAP.get(obj.get('model_analysis_type')) != expected_family:
        raise ValueError('Unsupported native post-analysis ARIMA model.')
    if state.get('has_weights') is True or obj.get('has_weights') is True or obj.get('weights_column_id') not in (None, 0, 0.0):
        raise ValueError('Native weighted ARIMA models are not supported for this refit.')
    if state.get('has_exogenous') is True or obj.get('has_exogenous') is True:
        raise ValueError('ARIMA models with exogenous predictors are not supported for this refit.')
    if state.get('transform') not in (None, 'none') or state.get('box_cox', False) is not False or obj.get('lambda', 1) != 1:
        raise ValueError('Native transformed ARIMA models are not supported for this refit.')
    rows = _dict(_dict(obj.get('rows_to_use'), 'row selection').get('rows'), 'row selection')
    if rows.get('use_all_rows') is not True:
        raise ValueError('Native row-subset models need a supported row-selection workflow before refitting.')
    p = _integer(state.get('p', 0), 'AR order p')
    d = _integer(state.get('d', 0), 'differencing order d')
    q = _integer(state.get('q', 0), 'MA order q')
    P = _integer(state.get('P', 0), 'seasonal AR order P')
    D = _integer(state.get('D', 0), 'seasonal differencing order D')
    Q = _integer(state.get('Q', 0), 'seasonal MA order Q')
    S = _integer(state.get('S', 1), 'seasonal period S')
    if min(p, d, q, P, D, Q) < 0 or S < 1 or (S == 1 and (P > 0 or D > 0 or Q > 0)):
        raise ValueError('Invalid native ARIMA order or seasonal period.')
    include_constant = state.get('include_constant_term', True)
    if type(include_constant) is not bool:
        raise ValueError('Invalid native ARIMA constant-term setting.')
    method_raw = state.get('method', 'CLS')
    if not isinstance(method_raw, str) or method_raw.strip().upper() not in ('CLS', 'ML'):
        raise ValueError('Unsupported native ARIMA estimation method.')
    method_norm = method_raw.strip().upper()
    confidence = state.get('confidence', 0.95)
    if not _number(confidence) or not 0 < confidence < 1 or (obj.get('confidence') is not None and confidence != obj.get('confidence')):
        raise ValueError('Native confidence settings are invalid or inconsistent.')
    settings_dict = {
        'series_index': resp_idx, 'p': p, 'd': d, 'q': q, 'P': P, 'D': D, 'Q': Q, 'S': S,
        'include_constant': include_constant, 'method': method_norm,
        'conf_level': float(confidence) * 100.0, 'forecasts': 0,
    }
    recipe = {'action': 'arima', 'parameters': {'settings': settings_dict}}
    from .recipes import columns
    columns(recipe)
    estimates = _items(obj.get('estimates', []), 'ARIMA parameter estimates', 64)
    ref_coefs = []
    for est in estimates:
        est = _dict(est, 'ARIMA estimate')
        coef_val, se_val = est.get('coef'), est.get('se_coef')
        if not _number(coef_val) or not _number(se_val) or se_val < 0:
            raise ValueError('Invalid saved ARIMA coefficient data.')
        ref_coefs.append({'term': str(est.get('term', '')), 'estimate': float(coef_val), 'standard_error': float(se_val)})
    df = _integer(obj.get('error_degrees_of_freedom'), 'error degrees of freedom')
    mse = obj.get('mean_square_error')
    if not _number(mse) or mse < 0 or df < 1:
        raise ValueError('Invalid native ARIMA residual inference state.')
    verification_ref = {
        'coefficients': ref_coefs, 'mse': float(mse), 'df_error': df,
        'row_count': _integer(rows.get('row_count'), 'saved row count'),
    }
    return {
        'supported': True, 'family': expected_family, 'command_id': cid, 'worksheet_id': wid,
        'worksheet_name': sheet.name, 'model_id': model_id, 'model_uri': uri, 'recipe': recipe,
        'source_column_map': {str(resp_idx): resp_id},
        'source_column_ids': {'response': resp_id},
        'verification_reference': verification_ref,
        'warnings': ['Refit is an independent StatCraft calculation using current worksheet values; saved native output remains unchanged.'],
    }


def _decode_mixed_reml(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family):
    if set(variables) - {'target', 'fixed', 'random'} or 'target' not in variables:
        raise ValueError('The native mixed-effects model uses unsupported variable roles.')
    fixed_vars = _items(variables.get('fixed', []), 'fixed predictors', 16)
    random_vars = _items(variables.get('random', []), 'random factors', 16)
    if not random_vars:
        raise ValueError('Mixed-effects model refitting requires at least one random factor.')
    seen_ids = []
    seen_internal = {}
    resp_idx, resp_id, _, _ = _decode_var_ref(sheet, sources, variables['target'], ('continuous',), seen_ids, seen_internal)
    fixed_indices, fixed_ids = [], []
    for fv in fixed_vars:
        idx, ident, _, _ = _decode_var_ref(sheet, sources, fv, ('continuous', 'categorical'), seen_ids, seen_internal)
        fixed_indices.append(idx)
        fixed_ids.append(ident)
    random_indices, random_ids = [], []
    for rv in random_vars:
        idx, ident, _, _ = _decode_var_ref(sheet, sources, rv, ('categorical',), seen_ids, seen_internal)
        random_indices.append(idx)
        random_ids.append(ident)
    state = _dict(_dict(model.get('model_information'), 'model information').get('input_state'), 'input state')
    obj = _dict(_dict(model.get('post_analysis_data'), 'post-analysis data').get('model_object'), 'model object')
    if _OBJ_TYPE_MAP.get(obj.get('model_object_type')) != expected_family or _OBJ_TYPE_MAP.get(obj.get('model_analysis_type')) != expected_family:
        raise ValueError('Unsupported native post-analysis mixed-effects model.')
    if state.get('include_constant_term') is not True:
        raise ValueError('Native no-intercept mixed models cannot be reconstructed by this fitter.')
    est_method = state.get('estimation_method', 'reml')
    if not isinstance(est_method, str) or est_method.strip().lower() != 'reml':
        raise ValueError('Mixed-effects ML estimation is not supported by the StatCraft REML backend.')
    cov_struct = state.get('covariance_structure')
    if cov_struct is not None and (not isinstance(cov_struct, str) or cov_struct.strip().lower() not in ('variance_components', 'vc')):
        raise ValueError('Only variance-components covariance structure is supported for mixed-effects refitting.')
    coding = state.get('coding', 'reference')
    if coding != 'reference':
        raise ValueError('Only reference coding is supported for mixed-effects refitting.')
    if state.get('has_weights') is True or obj.get('has_weights') is True or obj.get('weights_column_id') not in (None, 0, 0.0):
        raise ValueError('Native weighted mixed-effects models are not supported for this refit.')
    if obj.get('lambda', 1) != 1:
        raise ValueError('Native transformed mixed-effects models are not supported for this refit.')
    rows = _dict(_dict(obj.get('rows_to_use'), 'row selection').get('rows'), 'row selection')
    if rows.get('use_all_rows') is not True:
        raise ValueError('Native row-subset models need a supported row-selection workflow before refitting.')
    termlist = state.get('termlist')
    if isinstance(termlist, dict):
        for term in _items(termlist.get('model_terms', []), 'mixed model terms', 64):
            cols = _items(_dict(term, 'mixed model term').get('term_columns', []), 'term columns', 8)
            if len(cols) != 1:
                raise ValueError('Interaction or higher-order terms are not supported in mixed-effects refitting.')
    recipe = {
        'action': 'fit_mixed_reml',
        'parameters': {'response_index': resp_idx, 'fixed_indices': fixed_indices, 'random_indices': random_indices},
    }
    from .recipes import columns
    columns(recipe)
    fixed_ref = []
    for fe in _items(obj.get('fixed_effects', []), 'fixed effects', 64):
        fe = _dict(fe, 'fixed effect')
        if not _number(fe.get('coef')) or not _number(fe.get('se_coef')) or fe['se_coef'] < 0:
            raise ValueError('Invalid saved mixed-effects fixed parameter data.')
        fixed_ref.append({'term': str(fe.get('term', '')), 'coef': float(fe['coef']), 'se_coef': float(fe['se_coef'])})
    vc_ref = []
    for vc in _items(obj.get('variance_components', []), 'variance components', 32):
        vc = _dict(vc, 'variance component')
        if not _number(vc.get('var_comp')) or vc['var_comp'] < 0:
            raise ValueError('Invalid saved variance component data.')
        vc_ref.append({'source': str(vc.get('source', '')), 'var_comp': float(vc['var_comp'])})
    neg2_rell = obj.get('neg2_rell')
    if neg2_rell is not None and not _number(neg2_rell):
        raise ValueError('Invalid saved -2 RE log-likelihood.')
    verification_ref = {
        'fixed_effects': fixed_ref,
        'variance_components': vc_ref,
        'neg2_rell': float(neg2_rell) if neg2_rell is not None else None,
        'row_count': _integer(rows.get('row_count'), 'saved row count'),
    }
    all_indices = [resp_idx] + fixed_indices + random_indices
    return {
        'supported': True, 'family': expected_family, 'command_id': cid, 'worksheet_id': wid,
        'worksheet_name': sheet.name, 'model_id': model_id, 'model_uri': uri, 'recipe': recipe,
        'source_column_map': {str(idx): ident for idx, ident in zip(all_indices, seen_ids)},
        'source_column_ids': {'response': resp_id, 'fixed': fixed_ids, 'random': random_ids},
        'verification_reference': verification_ref,
        'warnings': ['Refit is an independent StatCraft calculation using current worksheet values; saved native output remains unchanged.'],
    }


def _decode(project, model, uri, declared_id, commands, family_type='ResponseSurfaceRegression'):
    expected_family = _FAMILY_MAP.get(family_type)
    if expected_family is None:
        raise ValueError('Unsupported native model family.')
    model=_dict(model,'model');metadata=_dict(model.get('metadata'),'model metadata')
    cid=metadata.get('command_id');wid=metadata.get('worksheet_id')
    if not isinstance(cid,str) or not cid or wid not in project.worksheet_ids:raise ValueError('The saved model has no available source worksheet or command identity.')
    command=commands.get(cid)
    if command is None:raise ValueError('The saved model command is absent or ambiguous.')
    if command.get('InputWorksheet')!=wid and command.get('OutputWorksheet')!=wid:raise ValueError('The saved model and command refer to different worksheets.')
    if _MODEL_TYPE_MAP.get(metadata.get('model_type')) != expected_family:
        raise ValueError('Unsupported native model type.')
    model_id=_integer(metadata.get('model_id'),'model identity')
    if declared_id is not None and _integer(declared_id,'declared model identity')!=model_id:raise ValueError('Native model identities disagree.')
    sheet=project.worksheets[project.worksheet_ids.index(wid)];sources=_source_columns(sheet)
    variables=_dict(model.get('variables'),'model variables')
    if expected_family == 'reliability_distribution':
        return _decode_reliability(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family)
    if expected_family == 'arima':
        return _decode_arima(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family)
    if expected_family == 'mixed_reml':
        return _decode_mixed_reml(sheet, sources, variables, model, uri, cid, wid, model_id, expected_family)
    target=_dict(variables.get('target'),'response variable')
    if expected_family in ('general_linear_model', 'binary_logistic', 'poisson_regression', 'ordinal_logistic', 'nominal_logistic'):
        allowed_roles = {'target', 'predictors', 'factors', 'covariates', 'block'} if expected_family == 'general_linear_model' else {'target', 'predictors', 'factors', 'covariates'}
        if set(variables) - allowed_roles:
            raise ValueError('The native model uses additional unsupported variable roles.')
        if 'predictors' in variables:
            predictors = _items(variables.get('predictors'), 'predictors', 8)
        else:
            raw_factors = _items(variables.get('factors', []), 'factors', 8)
            raw_covs = _items(variables.get('covariates', []), 'covariates', 8)
            predictors = raw_factors + raw_covs
        if not 1 <= len(predictors) <= 8:
            raise ValueError('Model refitting supports 1–8 predictors.')
    elif expected_family == 'factorial':
        if set(variables) - {'target', 'predictors', 'block'}:
            raise ValueError('The native model uses additional unsupported variable roles.')
        predictors = _items(variables.get('predictors'), 'factorial predictors', 8)
        if not 2 <= len(predictors) <= 8:
            raise ValueError('Factorial refitting supports 2–8 factors.')
    else:
        predictors=_items(variables.get('predictors'),'continuous predictors',10)
        if not 2<=len(predictors)<=10:raise ValueError('Refitting supports 2–10 continuous factors.')
        if set(variables)-{'target','predictors','block'}:raise ValueError('The native model uses additional unsupported variable roles.')
    block=variables.get('block');roles=[target]+predictors+([] if block is None else [_dict(block,'block variable')])
    ids=[];internal={};indices=[];predictor_roles=[]
    for position,variable in enumerate(roles):
        variable=_dict(variable,'variable reference');identity=variable.get('id')
        if not isinstance(identity,str) or identity not in sources:raise ValueError('A saved model column identity is unavailable in its worksheet.')
        if identity in ids:raise ValueError('Saved response, factors and blocks must have distinct identities.')
        ids.append(identity);internal_id=_integer(variable.get('variable_id'),'variable identity')
        if internal_id in internal:raise ValueError('Ambiguous saved internal variable identity.')
        internal[internal_id]=identity;index=sources[identity];indices.append(index)
        vtype = variable.get('type')
        if position == 0:
            if expected_family in ('binary_logistic', 'ordinal_logistic', 'nominal_logistic'):
                if vtype not in ('continuous', 'categorical'):
                    raise ValueError('The native model contains an unsupported response type.')
                expected = vtype
            elif expected_family == 'poisson_regression':
                if vtype not in ('continuous', 'count'):
                    raise ValueError('The native model contains an unsupported response type.')
                expected = vtype
            else:
                expected = 'continuous'
        elif block is not None and position == len(roles) - 1:
            expected = 'categorical'
        elif expected_family == 'response_surface':
            expected = 'continuous'
            predictor_roles.append(expected)
        else:
            if vtype not in ('continuous', 'categorical'):
                raise ValueError('The native model contains an unsupported predictor type.')
            expected = vtype
            predictor_roles.append(expected)
        if vtype!=expected:raise ValueError('The native model contains an unsupported predictor type.')
        if variable.get('data_type')!=('text' if sheet.columns[index].kind=='text' else 'numeric'):raise ValueError('The source data type conflicts with its saved native variable type.')
        if position == 0 and expected_family in ('binary_logistic', 'ordinal_logistic', 'nominal_logistic'):
            if sheet.columns[index].kind not in ('number', 'text'):
                raise ValueError('The source column type no longer matches its saved model role.')
        elif (expected in ('continuous', 'count') and sheet.columns[index].kind!='number') or (expected=='categorical' and sheet.columns[index].kind not in ('number','text')):
            raise ValueError('The source column type no longer matches its saved model role.')
    response=indices[0];factors=indices[1:1+len(predictors)];block_index=indices[-1] if block is not None else None
    state=_dict(_dict(model.get('model_information'),'model information').get('input_state'),'input state')
    obj=_dict(_dict(model.get('post_analysis_data'),'post-analysis data').get('model_object'),'model object')
    if _OBJ_TYPE_MAP.get(obj.get('model_object_type')) != expected_family or _OBJ_TYPE_MAP.get(obj.get('model_analysis_type')) != expected_family:
        raise ValueError('Unsupported native post-analysis model.')
    if state.get('include_constant_term') is not True:raise ValueError('Native no-intercept models cannot be reconstructed by this fitter.')
    raw_coding = state.get('coding')
    if expected_family == 'general_linear_model':
        if raw_coding not in ('effects', 'effect', 'reference'):
            raise ValueError('Only native effects or reference coding is supported for refitting.')
        model_coding = 'reference' if raw_coding == 'reference' else 'effect'
    elif expected_family in ('binary_logistic', 'poisson_regression', 'ordinal_logistic', 'nominal_logistic'):
        if raw_coding != 'reference':
            raise ValueError('Only native reference coding is supported for refitting.')
        model_coding = 'reference'
    else:
        if raw_coding not in ('effects', 'effect'):
            raise ValueError('Only the observed native effects coding is supported for refitting.')
        model_coding = 'effect'
    if state.get('standardized') is not False:raise ValueError('Native standardized predictor models are not yet supported.')
    if expected_family in ('binary_logistic', 'ordinal_logistic', 'nominal_logistic'):
        if state.get('link_function_type') != 'logit' or obj.get('link_function_type') != 'logit':
            raise ValueError('Only logit link is supported for logistic refitting.')
    elif expected_family == 'poisson_regression':
        if state.get('link_function_type') != 'log' or obj.get('link_function_type') != 'log':
            raise ValueError('Only log link is supported for poisson regression refitting.')
    else:
        if state.get('link_function_type')!='none' or obj.get('link_function_type')!='none':raise ValueError('Native linked/generalized response models are not supported here.')
    if state.get('confidence_interval')!='two_sided':raise ValueError('Native one-sided model inference is not supported here.')
    if state.get('selection_method')!='none' or state.get('validation_type')!='none':raise ValueError('Native model selection or validation procedures cannot be replayed by a fixed-model refit.')
    if expected_family in ('binary_logistic', 'poisson_regression', 'ordinal_logistic', 'nominal_logistic'):
        continuous = state.get('continuous_response_model_data') or {}
        if (isinstance(continuous, dict) and continuous.get('box_cox', False) is not False) or obj.get('lambda', 1) != 1:
            raise ValueError('Native transformed responses are not supported for this refit.')
    else:
        continuous=_dict(state.get('continuous_response_model_data'),'continuous-response settings')
        if continuous.get('box_cox') is not False or obj.get('lambda')!=1:raise ValueError('Native transformed responses are not supported for this refit.')
    if obj.get('has_weights') is not False or obj.get('weights_column_id') not in (0,0.0,None):raise ValueError('Native weighted models are not supported for this refit.')
    if expected_family in ('binary_logistic', 'ordinal_logistic', 'nominal_logistic'):
        if obj.get('is_mle') is not True or obj.get('is_categorical_response') is not True or obj.get('is_event_trial') is not False:
            raise ValueError('Native event/trial or non-MLE logistic models are not supported here.')
        if expected_family in ('ordinal_logistic', 'nominal_logistic') and (
                state.get('has_offset') is True or obj.get('has_offset') is True
                or state.get('offset_column_id') not in (None, 0, 0.0)
                or obj.get('offset_column_id') not in (None, 0, 0.0)):
            raise ValueError('Native offset models are not supported for this refit.')
    elif expected_family == 'poisson_regression':
        if obj.get('is_mle') is not True or obj.get('is_categorical_response') is not False or obj.get('is_event_trial') is not False:
            raise ValueError('Native non-MLE or categorical Poisson models are not supported here.')
        if (state.get('has_offset') is True or obj.get('has_offset') is True
                or state.get('offset_column_id') not in (None, 0, 0.0)
                or obj.get('offset_column_id') not in (None, 0, 0.0)):
            raise ValueError('Native offset models are not supported for this refit.')
        if (state.get('overdispersion') not in (None, False, 'none')
                or obj.get('overdispersion') not in (None, False, 'none')
                or state.get('is_quasi_poisson') is True or obj.get('is_quasi_poisson') is True
                or state.get('dispersion_parameter') not in (None, 1, 1.0)
                or obj.get('dispersion_parameter') not in (None, 1, 1.0)):
            raise ValueError('Overdispersed or quasi-Poisson models are not supported for this refit.')
    else:
        if obj.get('is_categorical_response') is not False or obj.get('is_event_trial') is not False or obj.get('is_mle') is not False:raise ValueError('Native non-OLS response models are not supported here.')
    rows=_dict(_dict(obj.get('rows_to_use'),'row selection').get('rows'),'row selection')
    if rows.get('use_all_rows') is not True:raise ValueError('Native row-subset models need a supported row-selection workflow before refitting.')
    confidence=state.get('confidence')
    if not _number(confidence) or not 0<confidence<1 or confidence!=obj.get('confidence'):raise ValueError('Native confidence settings are invalid or inconsistent.')
    termlist=_dict(obj.get('model_term_list'),'post-analysis term list')
    post_predictors=_items(termlist.get('model_predictors'),'post-analysis predictors',12)
    positions={identity:i for i,identity in enumerate(ids[1:1+len(predictors)])}
    post_ids={};coding=[None]*len(predictors);cat_levels={};block_levels=[];constants=0
    for pred in post_predictors:
        pred=_dict(pred,'post-analysis predictor');pid=_integer(pred.get('predictor_id'),'predictor identity')
        if pid in post_ids:raise ValueError('Duplicate native predictor identity.')
        typ=pred.get('predictor_type')
        if typ=='constant':
            if pid!=-1 or pred.get('column_id')!=0:raise ValueError('Invalid native intercept identity.')
            post_ids[pid]='constant';constants+=1;continue
        column_id=_integer(pred.get('column_id'),'post-analysis column identity');identity=internal.get(column_id)
        if identity not in ids[1:]:raise ValueError('Post-analysis predictor does not match a declared source variable.')
        if pred.get('was_predictor_fit') is not True or pred.get('is_random') is not False or pred.get('is_hard_to_change') is not False or pred.get('nesting_predictor_ids'):
            raise ValueError('Native random, nested, excluded or hard-to-change predictors are not supported here.')
        if identity in positions:
            pos = positions[identity]
            col_idx = factors[pos]
            role = predictor_roles[pos]
            if role == 'continuous':
                if typ!='continuous':raise ValueError('Native factor types disagree across model state.')
                if expected_family in ('response_surface', 'factorial'):
                    levels=_items(pred.get('numeric_levels'),'factor coding levels',2)
                    if len(levels)!=2 or not all(_number(v) for v in levels) or not levels[0]<levels[1]:raise ValueError('The saved factor has no valid low/high coding levels.')
                    coding[pos]={'low':levels[0],'high':levels[1]}
                else:
                    coding[pos]={'kind':'covariate'}
            else:
                if typ!='categorical':raise ValueError('Native factor types disagree across model state.')
                levels=pred.get('text_levels') if sheet.columns[col_idx].kind=='text' else pred.get('numeric_levels')
                levels=_items(levels,'categorical factor levels',32)
                if len(levels)<2 or len(set(levels))!=len(levels):raise ValueError('Invalid native categorical factor levels.')
                if expected_family=='factorial' and len(levels)!=2:raise ValueError('Factorial categorical factors must have exactly 2 levels.')
                declared_classes = predictors[pos].get('classes')
                if declared_classes is not None and declared_classes != levels:
                    raise ValueError('Native categorical factor levels disagree across model state.')
                cat_levels[identity] = levels
                coding[pos] = {'kind': 'categorical', 'levels': levels}
        else:
            if block is None or identity!=ids[-1] or typ!='block':raise ValueError('Unexpected categorical predictor in native model.')
            block_levels=pred.get('text_levels') if sheet.columns[block_index].kind=='text' else pred.get('numeric_levels')
            block_levels=_items(block_levels,'block levels',32)
            if len(block_levels)<2 or len(set(block_levels))!=len(block_levels):raise ValueError('Invalid native fixed-block levels.')
            if block.get('classes')!=block_levels:raise ValueError('Native fixed-block levels disagree across model state.')
            cat_levels[identity] = block_levels
        post_ids[pid]=identity
    if constants!=1 or len(post_ids)!=1+len(predictors)+(block is not None) or any(c is None for c in coding):raise ValueError('The saved model has an incomplete predictor/coding map.')
    inputs=_dict(state.get('termlist'),'input term list');input_terms=[];block_terms=0
    fixed=_items(inputs.get('fixed_factor_columns'),'fixed factor identities',11)
    fixed_ids=[_dict(v,'fixed factor').get('id') for v in fixed]
    if len(fixed_ids)!=len(ids)-1 or set(fixed_ids)!=set(ids[1:]):raise ValueError('Native input factors disagree with the declared model variables.')
    for term in _items(inputs.get('model_terms'),'input model terms',66):
        columns=_items(_dict(term,'input term').get('term_columns'),'input term columns',3 if expected_family != 'response_surface' else 2)
        identities=[_dict(v,'term variable').get('id') for v in columns]
        if any(internal.get(_integer(v.get('variable_id'),'input term variable identity'))!=v.get('id') for v in columns):raise ValueError('Input term variable identities disagree.')
        if block is not None and identities==[ids[-1]]:block_terms+=1;continue
        if not identities or any(v not in positions for v in identities):raise ValueError('Unsupported block interaction or unknown input model term.')
        input_terms.append(sorted(positions[v] for v in identities))
    if expected_family == 'response_surface':
        validate_terms(input_terms, len(factors))
    elif expected_family == 'factorial':
        _validate_factorial_terms(input_terms, len(factors))
    else:
        validate_glm_terms(input_terms, len(factors))
    if block_terms!=(1 if block is not None else 0):raise ValueError('Native block term inclusion is inconsistent.')
    reference_terms=[];post_terms=[];constant_terms=0;post_block_terms=0
    for term in _items(termlist.get('model_terms'),'saved model terms',67):
        term=_dict(term,'saved model term');pids=_items(term.get('predictor_ids'),'saved term predictor identities',3 if expected_family != 'response_surface' else 2)
        identities=[post_ids.get(_integer(v,'term predictor identity')) for v in pids]
        coefficients=_items(term.get('coefficients'),'saved coefficients',64);ses=_items(term.get('standard_error_coefficients'),'saved coefficient standard errors',64)
        if not coefficients or len(coefficients)!=len(ses) or not all(_number(v) for v in coefficients+ses) or any(v<0 for v in ses):raise ValueError('Invalid saved coefficient data.')
        if identities==['constant']:
            if expected_family in ('ordinal_logistic', 'nominal_logistic'):
                if not coefficients:
                    raise ValueError('Invalid intercept coefficient dimension.')
                constant_terms += 1
                reference_terms.append({'kind': 'constant', 'estimate': coefficients[0], 'standard_error': ses[0], 'estimates': list(coefficients), 'standard_errors': list(ses)})
            else:
                if len(coefficients)!=1:raise ValueError('Invalid intercept coefficient dimension.')
                constant_terms+=1;reference_terms.append({'kind':'constant','estimate':coefficients[0],'standard_error':ses[0]})
        elif block is not None and identities==[ids[-1]]:
            if len(coefficients)!=len(block_levels):raise ValueError('Native block coefficient dimensions disagree with block levels.')
            post_block_terms+=1
            reference_terms.extend({'kind':'block','level':level,'estimate':value,'standard_error':se} for level,value,se in zip(block_levels,coefficients,ses))
        else:
            if not identities or any(v not in positions for v in identities):raise ValueError('Unsupported native saved term.')
            normalized=sorted(positions[v] for v in identities)
            cat_in_term = [v for v in identities if v in cat_levels]
            if not cat_in_term:
                if expected_family == 'nominal_logistic':
                    if not coefficients:
                        raise ValueError('Unsupported native saved polynomial term.')
                    post_terms.append(normalized)
                    reference_terms.append({'kind':'polynomial','term':normalized,'estimate':coefficients[0],'standard_error':ses[0],'estimates':list(coefficients),'standard_errors':list(ses)})
                else:
                    if len(coefficients)!=1:raise ValueError('Unsupported native saved polynomial term.')
                    post_terms.append(normalized)
                    reference_terms.append({'kind':'polynomial','term':normalized,'estimate':coefficients[0],'standard_error':ses[0]})
            else:
                expanded_dim = math.prod(len(cat_levels[v]) for v in cat_in_term)
                free_dim = math.prod(len(cat_levels[v]) - 1 for v in cat_in_term)
                valid_dim = (len(coefficients) in (expanded_dim, free_dim)) if expected_family != 'nominal_logistic' else (len(coefficients) % expanded_dim == 0 or len(coefficients) % free_dim == 0)
                if not valid_dim:
                    raise ValueError('Native categorical term coefficient dimensions disagree with factor levels.')
                post_terms.append(normalized)
                reference_terms.append({
                    'kind': 'categorical_term',
                    'term': normalized,
                    'coefficients': list(coefficients),
                    'standard_errors': list(ses),
                    'expanded': len(coefficients) == expanded_dim,
                })
    if constant_terms!=1 or post_block_terms!=block_terms or len(post_terms)!=len(input_terms) or {tuple(v) for v in post_terms}!={tuple(v) for v in input_terms}:raise ValueError('Input and saved model terms disagree.')
    tables=metadata.get('tables',{});graphs=metadata.get('graphs',{});o=settings()
    o.update(confidence=confidence,coding=model_coding,ss_type='sequential' if continuous.get('sequential_sum_of_squares') else 'adjusted',graphs='four' if graphs.get('display_fourpack') or any(graphs.get(k) for k in ('display_histogram','display_normal','display_fits','display_order')) else 'none')
    for key,saved_key in [('method','display_method_table'),('anova','display_anova_table'),('model_summary','display_summary_table'),('coefficients','display_coefficients')]:
        if type(tables.get(saved_key)) is bool:o[key]=tables[saved_key]
    o['diagnostics']='all' if tables.get('all_diagnostic_rows') else 'unusual' if tables.get('display_diagnostics_table',True) else 'none'
    source_column_ids = {'response': ids[0], 'factors': ids[1:1+len(factors)], 'block': ids[-1] if block is not None else None}
    if expected_family == 'response_surface':
        recipe={'action':'analyze_response_surface','parameters':dict(response_index=response,factor_indices=factors,coding=coding,terms=input_terms,options=o)}
        if block is not None:recipe['parameters']['block_index']=block_index
    elif expected_family == 'factorial':
        all_numeric = all(sheet.columns[idx].kind == 'number' and role == 'continuous' for idx, role in zip(factors, predictor_roles))
        block_compatible = (block is None) or (sheet.columns[block_index].kind == 'number' and sheet.columns[block_index].name.casefold() == 'blocks')
        if all_numeric and block_compatible:
            max_order = max(len(t) for t in input_terms)
            params = dict(
                response_index=response,
                factor_indices=factors,
                max_order=max_order,
                confidence=confidence,
                plot_residuals=(o['graphs'] != 'none'),
                show_factor_coding=True,
                selected_terms=input_terms,
            )
            if block is not None:
                params['include_blocks'] = True
            recipe = {'action': 'analyze_factorial_terms', 'parameters': params}
        else:
            cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
            cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
            glm_factors = [factors[i] for i in cat_pos] + ([block_index] if block is not None else [])
            glm_covs = [factors[i] for i in cov_pos]
            glm_pos_map = {pos: idx for idx, pos in enumerate(cat_pos)}
            block_glm_pos = len(cat_pos)
            for idx, pos in enumerate(cov_pos):
                glm_pos_map[pos] = len(glm_factors) + idx
            glm_terms = [sorted(glm_pos_map[p] for p in t) for t in input_terms]
            if block is not None:
                glm_terms.append([block_glm_pos])
            validate_glm_terms(glm_terms, len(glm_factors) + len(glm_covs))
            recipe = {'action': 'general_linear_model', 'parameters': dict(
                response_index=response, factor_indices=glm_factors, covariate_indices=glm_covs, terms=glm_terms, options=o
            )}
            source_column_ids = {
                'response': ids[0],
                'factors': [ids[1 + i] for i in cat_pos] + ([ids[-1]] if block is not None else []),
                'covariates': [ids[1 + i] for i in cov_pos],
                'block': None,
            }
    elif expected_family == 'binary_logistic':
        cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
        cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
        cat_indices = [factors[i] for i in cat_pos]
        cont_indices = [factors[i] for i in cov_pos]
        pos_map = {pos: idx for idx, pos in enumerate(cat_pos)}
        for idx, pos in enumerate(cov_pos):
            pos_map[pos] = len(cat_indices) + idx
        logistic_terms = [sorted(pos_map[p] for p in t) for t in input_terms]
        validate_glm_terms(logistic_terms, len(cat_indices) + len(cont_indices))
        event = state.get('event') if state.get('event') is not None else obj.get('event') if obj.get('event') is not None else target.get('event')
        from .logistic import settings as logistic_settings
        lo = logistic_settings()
        lo.update(
            confidence=confidence,
            graphs='four' if graphs.get('display_fourpack') or any(graphs.get(k) for k in ('display_histogram', 'display_normal', 'display_fits', 'display_order')) else 'none',
        )
        for key, saved_key in [('method', 'display_method_table'), ('response_information', 'display_response_table'), ('model_summary', 'display_summary_table'), ('coefficients', 'display_coefficients'), ('odds_ratios', 'display_odds_ratios'), ('equation', 'display_equation')]:
            if type(tables.get(saved_key)) is bool:
                lo[key] = tables[saved_key]
        lo['diagnostics'] = 'all' if tables.get('all_diagnostic_rows') else 'unusual' if tables.get('display_diagnostics_table', True) else 'none'
        recipe = {'action': 'fit_binary_logistic', 'parameters': dict(
            response_index=response, continuous_indices=cont_indices, categorical_indices=cat_indices,
            event=event, trials_index=None, terms=logistic_terms, options=lo,
        )}
        source_column_ids = {
            'response': ids[0],
            'continuous': [ids[1 + i] for i in cov_pos],
            'categorical': [ids[1 + i] for i in cat_pos],
        }
    elif expected_family == 'ordinal_logistic':
        if any(len(t) != 1 for t in input_terms) or {t[0] for t in input_terms} != set(range(len(factors))):
            raise ValueError('Ordinal logistic regression refitting supports additive main-effects models only.')
        cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
        cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
        recipe = {'action': 'ordinal_logistic_regression', 'parameters': dict(
            response_index=response, continuous_indices=[factors[i] for i in cov_pos],
            categorical_indices=[factors[i] for i in cat_pos], confidence=confidence,
        )}
        source_column_ids = {
            'response': ids[0],
            'continuous': [ids[1 + i] for i in cov_pos],
            'categorical': [ids[1 + i] for i in cat_pos],
        }
    elif expected_family == 'nominal_logistic':
        if any(len(t) != 1 for t in input_terms) or {t[0] for t in input_terms} != set(range(len(factors))):
            raise ValueError('Nominal logistic regression refitting supports additive main-effects models only.')
        cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
        cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
        ref_level = state.get('reference_level') if state.get('reference_level') is not None else obj.get('reference_level') if obj.get('reference_level') is not None else target.get('reference_level')
        recipe = {'action': 'nominal_logistic_regression', 'parameters': dict(
            response_index=response, continuous_indices=[factors[i] for i in cov_pos],
            categorical_indices=[factors[i] for i in cat_pos], reference_level=ref_level, confidence=confidence,
        )}
        source_column_ids = {
            'response': ids[0],
            'continuous': [ids[1 + i] for i in cov_pos],
            'categorical': [ids[1 + i] for i in cat_pos],
        }
    elif expected_family == 'poisson_regression':
        if any(len(t) != 1 for t in input_terms) or {t[0] for t in input_terms} != set(range(len(factors))):
            raise ValueError('Poisson regression refitting supports additive main-effects models only.')
        cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
        cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
        recipe = {'action': 'poisson_regression', 'parameters': dict(
            response_index=response, continuous_indices=[factors[i] for i in cov_pos],
            categorical_indices=[factors[i] for i in cat_pos], offset_index=None, confidence=confidence,
        )}
        source_column_ids = {
            'response': ids[0],
            'continuous': [ids[1 + i] for i in cov_pos],
            'categorical': [ids[1 + i] for i in cat_pos],
        }
    else:
        cat_pos = [i for i, r in enumerate(predictor_roles) if r == 'categorical']
        cov_pos = [i for i, r in enumerate(predictor_roles) if r == 'continuous']
        glm_factors = [factors[i] for i in cat_pos] + ([block_index] if block is not None else [])
        glm_covs = [factors[i] for i in cov_pos]
        glm_pos_map = {pos: idx for idx, pos in enumerate(cat_pos)}
        block_glm_pos = len(cat_pos)
        for idx, pos in enumerate(cov_pos):
            glm_pos_map[pos] = len(glm_factors) + idx
        glm_terms = [sorted(glm_pos_map[p] for p in t) for t in input_terms]
        if block is not None:
            glm_terms.append([block_glm_pos])
        validate_glm_terms(glm_terms, len(glm_factors) + len(glm_covs))
        recipe = {'action': 'general_linear_model', 'parameters': dict(
            response_index=response, factor_indices=glm_factors, covariate_indices=glm_covs, terms=glm_terms, options=o
        )}
        source_column_ids = {
            'response': ids[0],
            'factors': [ids[1 + i] for i in cat_pos] + ([ids[-1]] if block is not None else []),
            'covariates': [ids[1 + i] for i in cov_pos],
            'block': None,
        }
    from .recipes import columns
    columns(recipe)
    df=_integer(obj.get('error_degrees_of_freedom'),'error degrees of freedom')
    if expected_family in ('binary_logistic', 'poisson_regression', 'ordinal_logistic', 'nominal_logistic'):
        ll = obj.get('log_likelihood'); dev = obj.get('deviance')
        if df < 1 or (ll is not None and not _number(ll)) or (dev is not None and (not _number(dev) or dev < 0)):
            raise ValueError('Invalid native likelihood inference state.')
        verification_ref = {'coefficients':reference_terms,'log_likelihood':ll,'deviance':dev,'df_error':df,'row_count':_integer(rows.get('row_count'),'saved row count'),'coding':model_coding}
    else:
        mse=obj.get('mean_square_error')
        if not _number(mse) or mse<0 or df<1:raise ValueError('Invalid native residual inference state.')
        verification_ref = {'coefficients':reference_terms,'mse':mse,'df_error':df,'row_count':_integer(rows.get('row_count'),'saved row count'),'coding':model_coding}
    return {'supported':True,'family':expected_family,'command_id':cid,'worksheet_id':wid,'worksheet_name':sheet.name,'model_id':model_id,'model_uri':uri,'recipe':recipe,
            'source_column_map':{str(index):identity for index,identity in zip(indices,ids)},
            'source_column_ids':source_column_ids,
            'verification_reference':verification_ref,
            'warnings':['Refit is an independent StatCraft calculation using current worksheet values; saved native output remains unchanged.']}


def read_native_models(project):
    """Return command-ID keyed supported setups or explicit unsupported reasons.

    This function parses metadata only; it neither fits a model nor mutates the
    supplied project. Missing members and unsupported semantics remain visible.
    """
    if project is None:return {}
    metadata=project.metadata if isinstance(project.metadata,dict) else {};reader=_Reader(project.retained_members)
    commands={};ambiguous=set()
    command_collection=metadata.get('Commands',{})
    command_items=command_collection.get('Items',[]) if isinstance(command_collection,dict) else []
    if not isinstance(command_items,list):command_items=[]
    for item in command_items[:1000]:
        if not isinstance(item,dict) or not isinstance(item.get('Id'),str):continue
        if item['Id'] in commands:ambiguous.add(item['Id'])
        commands[item['Id']]=item
    for cid in ambiguous:commands.pop(cid,None)
    result={};processed=0
    model_collection=metadata.get('Models',{})
    model_items=model_collection.get('Items',[]) if isinstance(model_collection,dict) else []
    if not isinstance(model_items,list):model_items=[]
    for family in model_items[:64]:
        if not isinstance(family,dict) or family.get('Type') not in _FAMILY_MAP:continue
        family_type = family.get('Type')
        family_items=family.get('Items',[])
        if not isinstance(family_items,list):continue
        for item in family_items[:MAX_MODELS]:
            if not isinstance(item,dict):continue
            uri=item.get('Data');processed+=1
            if processed>MAX_MODELS:return result
            if not isinstance(uri,str) or not uri.startswith('/models/') or '..' in uri.split('/') or '\\' in uri:continue
            raw=reader.resolve(uri);model=raw.get('Model') if isinstance(raw,dict) else None
            model_meta=model.get('metadata',{}) if isinstance(model,dict) else {};cid=model_meta.get('command_id')
            key=cid if isinstance(cid,str) and cid else uri
            try:descriptor=_decode(project,model,uri,item.get('Id'),commands,family_type=family_type)
            except (ValueError,TypeError,KeyError,IndexError,AttributeError,OverflowError,RecursionError) as exc:
                descriptor={'supported':False,'command_id':cid,'worksheet_id':model_meta.get('worksheet_id'),'model_uri':uri,'error':str(exc),'warnings':['The native model cannot be refitted automatically: '+str(exc)]}
            if key in result:
                result[key]={'supported':False,'command_id':cid,'model_uri':uri,'error':'Multiple saved models claim the same command identity.','warnings':['Ambiguous saved native model identity; automatic refit is unavailable.']}
            else:result[key]=descriptor
    return result


def compare_native_model(result,descriptor,relative_tolerance=1e-7,absolute_tolerance=1e-9):
    """Compare an explicit fresh fit with saved native coefficient/inference data.

    This is a bounded same-data comparison, not a native execution oracle.
    Differences are reported, never hidden or used to overwrite native output.
    """
    reference=descriptor.get('verification_reference')
    if not descriptor.get('supported') or not isinstance(reference,dict):raise ValueError('Select a supported recovered native model.')
    is_rsm = isinstance(result, dict) and result.get('analysis') == 'response_surface'
    is_glm = isinstance(result, dict) and result.get('analysis') == 'general_linear_model'
    is_factorial = isinstance(result, dict) and 'factor_coding' in result and 'selected_terms' in result
    is_logistic = isinstance(result, dict) and result.get('analysis') == 'binary_logistic'
    is_ordinal_logistic = isinstance(result, dict) and result.get('analysis') == 'ordinal_logistic_regression'
    is_nominal_logistic = isinstance(result, dict) and result.get('analysis') == 'nominal_logistic_regression'
    is_poisson = isinstance(result, dict) and result.get('analysis') == 'poisson_regression'
    is_reliability = isinstance(result, dict) and result.get('analysis') == 'reliability_distribution'
    is_arima = isinstance(result, dict) and result.get('analysis') == 'arima'
    is_mixed = isinstance(result, dict) and result.get('analysis') == 'mixed_reml'
    if not (is_rsm or is_glm or is_factorial or is_logistic or is_ordinal_logistic or is_nominal_logistic or is_poisson or is_reliability or is_arima or is_mixed):
        raise ValueError('Compare a fitted response-surface, factorial, general linear, logistic, Poisson, reliability, ARIMA, or mixed-effects model result.')
    if not _number(relative_tolerance) or not _number(absolute_tolerance) or relative_tolerance<0 or absolute_tolerance<0:raise ValueError('Comparison tolerances must be finite and nonnegative.')
    coefficients=result.get('coefficients',[])
    comparisons=[]
    def append(label,actual,expected):
        matched=_number(actual) and _number(expected) and math.isclose(actual,expected,rel_tol=relative_tolerance,abs_tol=absolute_tolerance)
        comparisons.append({'label':label,'actual':actual,'native':expected,'difference':actual-expected if _number(actual) and _number(expected) else None,'matches':bool(matched)})
    if is_reliability:
        actual_params = result.get('parameters', {})
        for k, expected in reference.get('parameters', {}).items():
            append(f'Parameter {k}', actual_params.get(k), expected)
        if reference.get('log_likelihood') is not None:
            append('Log-Likelihood', result.get('log_likelihood'), reference['log_likelihood'])
        if reference.get('mttf') is not None:
            append('MTTF', result.get('mttf'), reference['mttf'])
        return {'matches_saved_native': bool(comparisons) and all(v['matches'] for v in comparisons), 'comparisons': comparisons, 'relative_tolerance': relative_tolerance, 'absolute_tolerance': absolute_tolerance, 'scope': 'Saved native distribution parameters, log-likelihood and MTTF; independent fresh fit, not native execution.'}
    if is_arima:
        actual_est = result.get('estimates', [])
        for idx, item in enumerate(reference.get('coefficients', [])):
            actual = actual_est[idx] if idx < len(actual_est) else {}
            lbl = item.get('term') or f'Param {idx + 1}'
            append(lbl, actual.get('coef'), item.get('estimate'))
            append(lbl + ' SE', actual.get('se'), item.get('standard_error'))
        append('MSE', result.get('ms'), reference.get('mse'))
        append('Error DF', result.get('df'), reference.get('df_error'))
        return {'matches_saved_native': bool(comparisons) and all(v['matches'] for v in comparisons), 'comparisons': comparisons, 'relative_tolerance': relative_tolerance, 'absolute_tolerance': absolute_tolerance, 'scope': 'Saved native ARIMA parameter estimates, standard errors, residual mean square and error degrees of freedom; independent fresh fit, not native execution.'}
    if is_mixed:
        actual_fe = result.get('fixed_effects', [])
        for idx, item in enumerate(reference.get('fixed_effects', [])):
            actual = actual_fe[idx] if idx < len(actual_fe) else {}
            lbl = item.get('term') or f'Fixed {idx + 1}'
            append(lbl, actual.get('coef'), item.get('coef'))
            append(lbl + ' SE', actual.get('se_coef'), item.get('se_coef'))
        actual_vc = result.get('variance_components', [])
        for idx, item in enumerate(reference.get('variance_components', [])):
            actual = actual_vc[idx] if idx < len(actual_vc) else {}
            lbl = f"VarComp {item.get('source') or idx + 1}"
            append(lbl, actual.get('var_comp'), item.get('var_comp'))
        if reference.get('neg2_rell') is not None:
            append('-2 RE Log-Likelihood', result.get('neg2_rell'), reference['neg2_rell'])
        return {'matches_saved_native': bool(comparisons) and all(v['matches'] for v in comparisons), 'comparisons': comparisons, 'relative_tolerance': relative_tolerance, 'absolute_tolerance': absolute_tolerance, 'scope': 'Saved native mixed-effects fixed coefficients, standard errors, variance components and -2 RE log-likelihood; independent fresh fit, not native execution.'}
    if is_rsm:
        terms=result.get('surface_terms',result.get('terms',[]));levels=result.get('block_levels',[])
        count=max(0,len(levels)-1);polynomial={tuple(term):coefficients[1+count+i] for i,term in enumerate(terms) if 1+count+i<len(coefficients)}
        blocks={level:coefficients[1+i] for i,level in enumerate(levels[:-1]) if 1+i<len(coefficients)}
        for item in reference['coefficients']:
            if item['kind']=='constant':actual=coefficients[0] if coefficients else {};label='Constant'
            elif item['kind']=='polynomial':actual=polynomial.get(tuple(item['term']),{});label='Term '+str(item['term'])
            else:
                # The effect-coded reference level is expanded natively but absent
                # as an independent parameter. Compare only free coefficients.
                if item['level'] not in blocks:continue
                actual=blocks[item['level']];label='Block '+str(item['level'])
            append(label,actual.get('estimate'),item['estimate']);append(label+' SE',actual.get('standard_error'),item['standard_error'])
    elif is_factorial:
        n_blocks = len(result.get('block_terms', []))
        terms = result.get('selected_terms', [])
        term_map = {tuple(term): coefficients[1 + n_blocks + i] for i, term in enumerate(terms) if 1 + n_blocks + i < len(coefficients)}
        for item in reference['coefficients']:
            if item['kind'] == 'constant':
                actual = coefficients[0] if coefficients else {}; label = 'Constant'
            elif item['kind'] == 'polynomial':
                actual = term_map.get(tuple(item['term']), {}); label = 'Term ' + str(item['term'])
            else:
                continue
            append(label, actual.get('estimate'), item['estimate']); append(label + ' SE', actual.get('standard_error'), item['standard_error'])
    elif is_logistic or is_poisson:
        est_key, se_key = ('coef', 'se_coef') if is_poisson else ('estimate', 'standard_error')
        for item in reference['coefficients']:
            if item['kind'] == 'constant':
                actual = coefficients[0] if coefficients else {}
                append('Constant', actual.get(est_key), item['estimate'])
                append('Constant SE', actual.get(se_key), item['standard_error'])
        if reference.get('log_likelihood') is not None:
            append('Log-Likelihood', result.get('log_likelihood'), reference['log_likelihood'])
        if reference.get('deviance') is not None:
            append('Deviance', result.get('deviance'), reference['deviance'])
        actual_df = result.get('df_residual') if is_poisson else result.get('df_error')
        append('Error DF', actual_df, reference['df_error'])
    elif is_ordinal_logistic or is_nominal_logistic:
        if is_ordinal_logistic:
            for item in reference['coefficients']:
                if item['kind'] == 'constant':
                    ests = item.get('estimates') or [item['estimate']]
                    ses = item.get('standard_errors') or [item['standard_error']]
                    for idx, (est, se) in enumerate(zip(ests, ses)):
                        actual = coefficients[idx] if idx < len(coefficients) else {}
                        lbl = f'Const({idx + 1})' if len(ests) > 1 else 'Constant'
                        append(lbl, actual.get('coef'), est)
                        append(lbl + ' SE', actual.get('se_coef'), se)
        else:
            logits = result.get('logits', [])
            for item in reference['coefficients']:
                if item['kind'] == 'constant':
                    ests = item.get('estimates') or [item['estimate']]
                    ses = item.get('standard_errors') or [item['standard_error']]
                    for idx, (est, se) in enumerate(zip(ests, ses)):
                        logit_coefs = logits[idx].get('coefficients', []) if idx < len(logits) else []
                        actual = logit_coefs[0] if logit_coefs else {}
                        lbl = f'Constant {idx + 1}' if len(ests) > 1 else 'Constant'
                        append(lbl, actual.get('coef'), est)
                        append(lbl + ' SE', actual.get('se_coef'), se)
        if reference.get('log_likelihood') is not None:
            append('Log-Likelihood', result.get('log_likelihood'), reference['log_likelihood'])
        gof = next((g for g in result.get('goodness_of_fit', []) if g.get('method') == 'Deviance'), {})
        if reference.get('deviance') is not None:
            append('Deviance', gof.get('chi_square'), reference['deviance'])
        append('Error DF', gof.get('df'), reference['df_error'])
    else:
        for item in reference['coefficients']:
            if item['kind'] == 'constant':
                actual = coefficients[0] if coefficients else {}
                append('Constant', actual.get('estimate'), item['estimate'])
                append('Constant SE', actual.get('standard_error'), item['standard_error'])
    if not (is_logistic or is_poisson or is_ordinal_logistic or is_nominal_logistic):
        append('MSE',result.get('ms_error'),reference['mse']);append('Error DF',result.get('df_error'),reference['df_error'])
    return {'matches_saved_native':bool(comparisons) and all(v['matches'] for v in comparisons),'comparisons':comparisons,'relative_tolerance':relative_tolerance,'absolute_tolerance':absolute_tolerance,'scope':'Saved native coefficients, free coefficient standard errors, residual mean square and error degrees of freedom; independent fresh fit, not native execution.'}


def resolve_model_recipe(project,descriptor):
    """Resolve current source positions by native identity after worksheet edits."""
    if not isinstance(descriptor,dict) or not descriptor.get('supported') or not isinstance(descriptor.get('recipe'),dict):
        raise ValueError('Select a supported recovered native model.')
    wid=descriptor.get('worksheet_id')
    if project is None or wid not in project.worksheet_ids:raise ValueError('The native model source worksheet is unavailable.')
    sheet=project.worksheets[project.worksheet_ids.index(wid)];columns=_source_columns(sheet)
    identities=descriptor['source_column_ids'];recipe=copy.deepcopy(descriptor['recipe']);p=recipe['parameters']
    try:
        action = recipe.get('action')
        if action == 'reliability_distribution':
            p['settings']['column_index'] = columns[identities['response']]
            if identities.get('censor') is not None:
                p['settings']['censor_index'] = columns[identities['censor']]
        elif action == 'arima':
            p['settings']['series_index'] = columns[identities['response']]
        elif action == 'fit_mixed_reml':
            p['response_index'] = columns[identities['response']]
            p['fixed_indices'] = [columns[identity] for identity in identities.get('fixed', [])]
            p['random_indices'] = [columns[identity] for identity in identities.get('random', [])]
        else:
            p['response_index']=columns[identities['response']]
            if action in ('fit_binary_logistic', 'poisson_regression', 'ordinal_logistic_regression', 'nominal_logistic_regression'):
                p['continuous_indices']=[columns[identity] for identity in identities.get('continuous', [])]
                p['categorical_indices']=[columns[identity] for identity in identities.get('categorical', [])]
            else:
                p['factor_indices']=[columns[identity] for identity in identities['factors']]
                if identities.get('covariates') is not None:p['covariate_indices']=[columns[identity] for identity in identities['covariates']]
                if identities.get('block') is not None:p['block_index']=columns[identities['block']]
    except KeyError as exc:raise ValueError('A recovered native model source column was deleted or lost its identity.') from exc
    from .recipes import columns as recipe_columns
    recipe_columns(recipe)
    return recipe


def resolve_entry_recipe(entry, worksheet=None):
    """Extract and resolve the typed model recipe from a StatCraft or native entry."""
    if not isinstance(entry, dict) or entry.get('source_unavailable'):
        return None
    origin = entry.get('origin')
    if origin == 'native':
        if not entry.get('native_model', {}).get('supported'):
            return None
        nm = entry['native_model']
        recipe = copy.deepcopy(nm.get('recipe'))
        if not isinstance(recipe, dict) or not recipe.get('parameters'):
            return None
        if worksheet is not None:
            ws_name = getattr(worksheet, 'name', None)
            entry_ws_name = entry.get('worksheet_name') or nm.get('worksheet_name')
            if ws_name and entry_ws_name and ws_name != entry_ws_name:
                return None
            try:
                cols = _source_columns(worksheet)
                identities = nm.get('source_column_ids', {})
                p = recipe['parameters']
                action = recipe.get('action')
                if action == 'reliability_distribution':
                    if identities.get('response') in cols:
                        p['settings']['column_index'] = cols[identities['response']]
                    if identities.get('censor') in cols:
                        p['settings']['censor_index'] = cols[identities['censor']]
                elif action == 'arima':
                    if identities.get('response') in cols:
                        p['settings']['series_index'] = cols[identities['response']]
                elif action == 'fit_mixed_reml':
                    if identities.get('response') in cols:
                        p['response_index'] = cols[identities['response']]
                    if 'fixed' in identities:
                        p['fixed_indices'] = [cols[fid] for fid in identities['fixed'] if fid in cols]
                    if 'random' in identities:
                        p['random_indices'] = [cols[rid] for rid in identities['random'] if rid in cols]
                else:
                    if identities.get('response') in cols:
                        p['response_index'] = cols[identities['response']]
                    if action in ('fit_binary_logistic', 'poisson_regression', 'ordinal_logistic_regression', 'nominal_logistic_regression'):
                        if 'continuous' in identities:
                            p['continuous_indices'] = [cols[cid] for cid in identities['continuous'] if cid in cols]
                        if 'categorical' in identities:
                            p['categorical_indices'] = [cols[cid] for cid in identities['categorical'] if cid in cols]
                    else:
                        if identities.get('factors'):
                            p['factor_indices'] = [cols[fid] for fid in identities['factors'] if fid in cols]
                        if identities.get('covariates'):
                            p['covariate_indices'] = [cols[cid] for cid in identities['covariates'] if cid in cols]
                        if identities.get('block') and identities['block'] in cols:
                            p['block_index'] = cols[identities['block']]
            except Exception:
                pass
        return recipe
    raw = entry.get('recipe')
    return copy.deepcopy(raw) if isinstance(raw, dict) else None
