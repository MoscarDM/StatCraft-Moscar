"""Original bounded full two-level factorial creation and coded OLS analysis.

NIST standard order/model matrix reference:
https://www.itl.nist.gov/div898/handbook/pri/section3/pri3331.htm
No native DOE metadata, response-surface/Taguchi designs,
multiple blocks, curvature test or native parity is implemented.
"""
import itertools
import math
import random
from scipy.stats import t as student_t
from .model import Column, Worksheet
from .engine import normalize_numeric
from .regression import multiple_regression


def _integer(value, low, high, name):
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')
    return value


def _level(value):
    value=normalize_numeric(value)
    if value is None:raise ValueError('Factor levels must be finite and nonmissing.')
    return value


def _coding(name,low,high):
    low,high=_level(low),_level(high)
    if low>=high:raise ValueError('Each factor low setting must be below its high setting.')
    span=high-low;center=math.fsum((low/2,high/2));half=span/2
    if not math.isfinite(span) or half<=0 or not low<center<high:
        raise ValueError('Factor range/midpoint exceeds supported numeric precision.')
    return dict(name=name,kind='number',low=low,high=high,center=center,half_range=half,levels=[low,high])


def _factor_spec(name, factor):
    kind = str(factor.get('kind', 'number')).strip().lower()
    if 'low' not in factor or 'high' not in factor:
        raise ValueError('Each factor needs low and high settings.')
    if kind == 'text':
        low = str(factor['low']).strip()
        high = str(factor['high']).strip()
        if not low or not high or low == high:
            raise ValueError('Text factor requires two distinct non-empty levels.')
        return dict(name=name, kind='text', low=low, high=high, center=None, half_range=None, levels=[low, high])
    return _coding(name, factor['low'], factor['high'])


def create_factorial(factors,replicates=1,centers=0,randomize=True,seed=1,blocks=1):
    """Create 2..8 numeric or text 2-level factors, first factor fastest, single or multiple blocks, <=4096 runs.

    Centers is the center-run count per block. PtType=1 corners, 0 centers.
    StdOrder is grouped by block (corners then centers); RunOrder is physical row order.
    """
    factors=list(factors);k=len(factors)
    _integer(k,2,8,'Factor count');_integer(replicates,1,20,'Replicates')
    _integer(centers,0,20,'Center runs')
    _integer(blocks,1,64,'Blocks')
    if type(randomize) is not bool:raise ValueError('Randomize must be true or false.')
    if seed is None:
        seed = random.SystemRandom().randint(1, 2_147_483_647)
    else:
        _integer(seed,-(2**63),2**63-1,'Randomization seed')
    total_corners=(2**k)*replicates
    if total_corners%blocks!=0:
        raise ValueError('Total corner runs must be evenly divisible by the number of blocks.')
    count=total_corners+(centers*blocks)
    if count>4096:raise ValueError('The factorial plan exceeds the 4096-run limit.')
    coding=[];names=set(n.casefold() for n in ['StdOrder','RunOrder','PtType','Blocks'])
    for i,factor in enumerate(factors):
        if not isinstance(factor,dict):raise ValueError('Factors must be objects with name, low and high.')
        name=factor.get('name')
        if not isinstance(name,str) or not name.strip() or name.casefold() in names:
            raise ValueError('Factor names must be nonempty, unique and different from design-column names.')
        names.add(name.casefold())
        code=_factor_spec(name,factor);code['column_index']=4+i;coding.append(code)
    if centers and any(f.get('kind')=='text' for f in coding):
        raise ValueError('Center points require all factors to be numeric.')
    corners_per_rep=2**k; corners_per_block=total_corners//blocks
    corner_runs=[]
    for rep in range(replicates):
        for corner in range(corners_per_rep):
            settings=[f['high'] if corner&(1<<i) else f['low'] for i,f in enumerate(coding)]
            if blocks==replicates: b=rep+1
            elif blocks==1: b=1
            elif blocks%replicates==0:
                sub_blocks=blocks//replicates
                if sub_blocks==2:
                    prod=math.prod(1 if corner&(1<<i) else -1 for i in range(k))
                    sub=0 if prod<0 else 1
                elif sub_blocks==4 and k>=3:
                    p1=math.prod(1 if corner&(1<<i) else -1 for i in range(k-1))
                    p2=math.prod(1 if corner&(1<<i) else -1 for i in range(1,k))
                    sub=(0 if p1<0 else 1)+2*(0 if p2<0 else 1)
                else:
                    sub=corner//(corners_per_rep//sub_blocks)
                b=rep*sub_blocks+sub+1
            else:
                flat_idx=rep*corners_per_rep+corner
                b=flat_idx//corners_per_block+1
            corner_runs.append(dict(pt_type=1,block=b,settings=settings))
    center_runs=[]
    for b in range(1,blocks+1):
        for _ in range(centers):
            center_runs.append(dict(pt_type=0,block=b,settings=[f['center'] for f in coding]))
    block_groups={b:[] for b in range(1,blocks+1)}
    for r in corner_runs: block_groups[r['block']].append(r)
    for r in center_runs: block_groups[r['block']].append(r)
    unrandomized=[]
    for b in range(1,blocks+1): unrandomized.extend(block_groups[b])
    for i,r in enumerate(unrandomized,1): r['std_order']=i
    if randomize:
        rng=random.Random(seed)
        plan=[]
        for b in range(1,blocks+1):
            b_runs=list(block_groups[b]); rng.shuffle(b_runs); plan.extend(b_runs)
    else: plan=unrandomized
    columns=[Column('StdOrder',values=[r['std_order'] for r in plan]),
             Column('RunOrder',values=list(range(1,count+1))),
             Column('PtType',values=[r['pt_type'] for r in plan]),
             Column('Blocks',values=[r['block'] for r in plan])]
    columns.extend(Column(f['name'],kind=f.get('kind','number'),values=[r['settings'][i] for r in plan]) for i,f in enumerate(coding))
    return Worksheet('Full factorial design',columns,metadata={'doe':dict(
        schema='statcraft-full-factorial-v1',origin='Original StatCraft design',
        design='full two-level factorial',factors=coding,replicates=replicates,
        centers=centers,randomize=randomize,seed=seed,blocks=blocks,
        standard_order='Runs grouped by block; first factor fastest within block; centers per block.',
        point_types={'factorial':1,'center':0},native_parity=False)})


def _resolve_factorial_block_column(worksheet, metadata):
    if isinstance(metadata, dict) and metadata.get('custom_defined') and metadata.get('blocks_mode') == 'none':
        return None
    idx = metadata.get('blocks_column_index') if isinstance(metadata, dict) else None
    col_name = metadata.get('blocks_column') if isinstance(metadata, dict) else None
    if type(idx) is int and 0 <= idx < len(worksheet.columns):
        candidate = worksheet.columns[idx]
        if not col_name or candidate.name == col_name:
            return candidate
    if isinstance(col_name, str) and col_name:
        matched = next((c for c in worksheet.columns if c.name == col_name), None)
        if matched is not None:
            return matched
    return next((c for c in worksheet.columns if c.name.casefold() == 'blocks'), None)


def _encode_blocks(worksheet, used, block_col, include_blocks, require_nonmissing=False):
    raw_blocks = [
        (block_col.values[r] if r < len(block_col.values) else None)
        for r in used
    ] if block_col is not None else [1] * len(used)
    observed_blocks = []
    for raw in raw_blocks:
        if block_col is not None and block_col.kind == 'text':
            val = raw.strip() if isinstance(raw, str) and raw.strip() else None
        elif block_col is not None:
            val = normalize_numeric(raw)
        else:
            val = raw
        if require_nonmissing and val is None:
            raise ValueError(f"Blocks column '{block_col.name}' has missing values on active rows.")
        observed_blocks.append(val)
    unique_blocks = sorted(
        {b for b in observed_blocks if b is not None},
        key=lambda v: (0, float(v)) if isinstance(v, (int, float)) else (1, str(v)),
    )
    has_multiple_blocks = len(unique_blocks) > 1
    if include_blocks is None:
        include_blocks = has_multiple_blocks
    elif type(include_blocks) is not bool:
        raise ValueError('Include blocks must be true or false.')
    elif include_blocks and not has_multiple_blocks:
        include_blocks = False
    block_predictors = []
    block_names = []
    if include_blocks:
        if len(unique_blocks) == 2:
            b1 = unique_blocks[1]
            block_predictors.append([1. if b == b1 else -1. for b in observed_blocks])
            block_names.append(block_col.name if block_col else 'Blocks')
        elif len(unique_blocks) > 2:
            ref_block = unique_blocks[-1]
            prefix = block_col.name if block_col else 'Blocks'
            for b_lvl in unique_blocks[:-1]:
                block_predictors.append([1. if b == b_lvl else (-1. if b == ref_block else 0.) for b in observed_blocks])
                block_names.append(f'{prefix} {b_lvl}')
    return block_predictors, block_names, unique_blocks, has_multiple_blocks, include_blocks


def _factor_terms_hierarchy(k, max_order, selected_terms):
    terms = [indices for order in range(1, min(max_order, k) + 1) for indices in itertools.combinations(range(k), order)]
    if selected_terms is not None:
        if not isinstance(selected_terms, list) or not selected_terms:
            raise ValueError('Select at least one model term.')
        terms = []
        for term in selected_terms:
            if not isinstance(term, list) or not 1 <= len(term) <= 3 or any(type(i) is not int or not 0 <= i < k for i in term):
                raise ValueError('Model terms must contain one to three valid factor positions.')
            if len(set(term)) != len(term):
                raise ValueError('A factor cannot repeat within a term.')
            value = tuple(sorted(term))
            if value in terms:
                raise ValueError('Model terms must be distinct.')
            terms.append(value)
        terms.sort(key=lambda value: (len(value), value))
        for term in terms:
            for order in range(1, len(term)):
                if any(subset not in terms for subset in itertools.combinations(term, order)):
                    raise ValueError('Include all lower-order terms for a hierarchical model.')
    return terms


def _analyze_general_factorial(worksheet, response, selected, factors, used, ys, raw_rows, metadata, max_order, confidence, selected_terms, include_blocks):
    from .fractional import _FACTOR_LETTERS
    k = len(selected)
    names = [c.name for c in selected]
    coding = []
    factor_contrasts = []
    for pos, (col, index) in enumerate(zip(selected, factors)):
        obs = [row[pos] for row in raw_rows]
        declared = next((f for f in metadata.get('factors', []) if f.get('column_index') == index and f.get('name') == col.name), None)
        if declared and isinstance(declared.get('levels'), list) and len(declared['levels']) >= 2:
            levels = list(declared['levels'])
            source = 'Custom StatCraft design metadata' if metadata.get('custom_defined') else 'StatCraft design metadata'
        else:
            levels = sorted(
                set(obs),
                key=lambda v: (0, float(v)) if isinstance(v, (int, float)) else (1, str(v)),
            )
            source = 'Observed levels'
        if len(levels) < 2:
            raise ValueError(f"Factor '{col.name}' needs at least 2 observed levels.")
        ref = levels[-1]
        contrasts = []
        contrast_labels = []
        if len(levels) == 2:
            contrasts.append([1.0 if v == levels[1] else -1.0 for v in obs])
            contrast_labels.append(col.name)
        else:
            for lvl in levels[:-1]:
                contrasts.append([1.0 if v == lvl else (-1.0 if v == ref else 0.0) for v in obs])
                contrast_labels.append(f"{col.name} ({lvl})")
        info = {'name': col.name, 'kind': col.kind, 'levels': levels, 'column_index': index,
                'letter': _FACTOR_LETTERS[pos] if pos < len(_FACTOR_LETTERS) else f'F{pos + 1}',
                'source': source}
        if len(levels) == 2:
            info['low'] = levels[0]
            info['high'] = levels[1]
            info['center'] = math.fsum((float(levels[0]) / 2.0, float(levels[1]) / 2.0)) if col.kind == 'number' else None
        coding.append(info)
        factor_contrasts.append(list(zip(contrast_labels, contrasts)))

    block_col = _resolve_factorial_block_column(worksheet, metadata)
    block_predictors, block_names, unique_blocks, has_multiple_blocks, include_blocks = _encode_blocks(
        worksheet, used, block_col, include_blocks,
        require_nonmissing=bool(metadata.get('custom_defined') and block_col is not None),
    )
    terms = _factor_terms_hierarchy(k, max_order, selected_terms)
    term_names = ['*'.join(names[i] for i in term) for term in terms]
    if len(set(term_names)) != len(term_names):
        raise ValueError('Factor names produce ambiguous interaction labels.')

    term_predictors = []
    term_pred_names = []
    term_pred_factors = []
    for term in terms:
        combos = itertools.product(*(factor_contrasts[i] for i in term))
        for combo in combos:
            lbl = '*'.join(lbl_part for lbl_part, _ in combo)
            col_vals = [math.prod(vals[r] for _, vals in combo) for r in range(len(used))]
            term_predictors.append(col_vals)
            term_pred_names.append(lbl)
            term_pred_factors.append([names[i] for i in term])

    all_predictors = block_predictors + term_predictors
    all_pred_names = block_names + term_pred_names
    result = multiple_regression(all_predictors, ys, confidence, predictor_names=all_pred_names)
    n_blocks = len(block_names)
    for i, coefficient in enumerate(result['coefficients']):
        if i == 0:
            coefficient['term_factors'] = []
            coefficient['effect'] = None
            coefficient['effect_se'] = None
        elif i <= n_blocks:
            coefficient['term_factors'] = [block_col.name if block_col else 'Blocks']
            coefficient['effect'] = None
            coefficient['effect_se'] = None
        else:
            p_idx = i - n_blocks - 1
            t_factors = term_pred_factors[p_idx]
            coefficient['term_factors'] = t_factors
            all_two_level = all(len(c['levels']) == 2 for c in coding if c['name'] in t_factors)
            coefficient['effect'] = 2 * coefficient['estimate'] if all_two_level else None
            coefficient['effect_se'] = 2 * coefficient['standard_error'] if all_two_level else None
        for suffix in ('low', 'high'):
            ci = coefficient['ci_' + suffix]
            coefficient['effect_ci_' + suffix] = None if coefficient['effect'] is None or ci is None else 2 * ci

    result.update(
        method='General factorial effects-coded OLS; hierarchical selected terms',
        response_name=response.name,
        factor_coding=coding,
        terms=block_names + term_names,
        factor_terms=term_names,
        block_terms=block_names,
        include_blocks=include_blocks,
        blocks=len(unique_blocks) if has_multiple_blocks else 1,
        blocks_column=block_col.name if (include_blocks and block_col is not None) else None,
        max_order=max(map(len, terms)),
        selected_terms=[list(term) for term in terms],
        row_indices=used,
        used_rows=used,
        missing=worksheet.row_count - len(used),
        coded_factors=raw_rows,
        native_parity=False,
        verification_block_columns=block_predictors,
        design_seed=None,
        assumptions='Independent errors with common variance and normality for t/F inference. Multi-level factors use sum-to-zero effects coding.',
    )
    return result


def analyze_factorial(worksheet,response_index,factor_indices,max_order=2,confidence=.95,selected_terms=None,include_blocks=None):
    """Fit all hierarchical coded terms through order1..3, intercept included.

    Main/interaction effects are twice coded coefficients. Centers inform the
    linear/interactions model; no center indicator or curvature test is fitted.
    Blocks are fitted when multiple blocks are present and include_blocks is not False.
    Missing responses/factors omit a row jointly. Rank/saturated models error.
    """
    if not isinstance(worksheet,Worksheet):raise ValueError('A Worksheet is required.')
    from .fractional import _FACTOR_LETTERS
    metadata=worksheet.metadata.get('doe',{}) if isinstance(worksheet.metadata,dict) else {}
    custom_general=metadata.get('design_type')=='general_full'
    factors=list(factor_indices);k=len(factors)
    _integer(k,1 if custom_general else 2,15,'Factor count');_integer(max_order,1,3,'Maximum interaction order')
    _integer(response_index,0,len(worksheet.columns)-1,'Response index')
    for index in factors:_integer(index,0,len(worksheet.columns)-1,'Factor index')
    if len(set(factors))!=k or response_index in factors:raise ValueError('Select distinct factor columns and a separate response.')
    selected=[worksheet.columns[i] for i in factors]
    response=worksheet.columns[response_index]
    if response.kind!='number' or any(c.kind not in ('number','text') for c in selected):
        raise ValueError('DOE requires a numeric response column and numeric or text factor columns.')
    names=[c.name for c in selected]
    if len(set(names))!=k:raise ValueError('Selected factors need distinct names.')
    n=worksheet.row_count
    if n>4096:raise ValueError('DOE analysis is limited to 4096 worksheet rows.')
    raw_values=[]
    for c in selected:
        if c.kind=='text':
            raw_values.append([c.values[i].strip() if i<len(c.values) and isinstance(c.values[i],str) and c.values[i].strip() else None for i in range(n)])
        else:
            raw_values.append([_level_or_missing(c.values[i]) if i<len(c.values) else None for i in range(n)])
    used=[];obs_rows=[];ys=[]
    for row in range(n):
        y=_level_or_missing(response.values[row]) if row<len(response.values) else None
        raw=[v[row] for v in raw_values]
        if y is None or any(v is None for v in raw):continue
        used.append(row);obs_rows.append(raw);ys.append(y)

    # Check whether this fit is multi-level / general full factorial
    use_general=bool(
        metadata.get('design_type')=='general_full'
        or (metadata.get('schema')=='statcraft-catalog-design-v1' and metadata.get('design')=='general_factorial')
    )
    if use_general:
        return _analyze_general_factorial(
            worksheet,response,selected,factors,used,ys,obs_rows,metadata,max_order,confidence,selected_terms,include_blocks,
        )

    trusted=metadata.get('schema') in ('statcraft-full-factorial-v1','statcraft-regular-fractional-v1','statcraft-custom-factorial-v1')
    coding=[]
    for pos,(column,index) in enumerate(zip(selected,factors)):
        observed=[row[pos] for row in obs_rows]
        declared=next((f for f in metadata.get('factors',[]) if f.get('column_index')==index and f.get('name')==column.name),None) if trusted else None
        source_label='Custom StatCraft design metadata' if (declared is not None and metadata.get('custom_defined')) else ('StatCraft design metadata' if declared is not None else 'Observed levels')
        if column.kind=='text':
            if declared is not None and declared.get('low') is not None and declared.get('high') is not None:
                low_s,high_s=str(declared['low']),str(declared['high'])
            else:
                levels=sorted(set(observed))
                if len(levels)!=2:raise ValueError('Each text two-level factor needs two observed levels.')
                low_s,high_s=levels[0],levels[1]
            code={'name':column.name,'kind':'text','low':low_s,'high':high_s,'center':None,'half_range':None,'levels':[low_s,high_s],'source':source_label}
        else:
            if declared is not None:
                code=_coding(column.name,declared['low'],declared['high']);code['source']=source_label
            else:
                levels=sorted(set(observed))
                if len(levels) not in (2,3):raise ValueError('Each factor needs two observed levels, optionally their common center setting.')
                code=_coding(column.name,levels[0],levels[-1]);code['source']='Observed levels'
        code['column_index']=index;code['letter']=_FACTOR_LETTERS[len(coding)];coding.append(code)
    coded_rows=[]
    for raw in obs_rows:
        codes=[]
        for v,code in zip(raw,coding):
            if code.get('kind')=='text':
                if v==code['low']:codes.append(-1.0)
                elif v==code['high']:codes.append(1.0)
                else:raise ValueError('Factor data contain settings outside the declared text levels.')
            else:
                z=(v-code['center'])/code['half_range']
                if not math.isfinite(z):raise ValueError('Factor coding exceeds supported numeric range.')
                nearest=min((-1.,0.,1.),key=lambda t:abs(z-t))
                if abs(z-nearest)>1e-10:raise ValueError('Factor data contain settings outside the two levels and their midpoint.')
                codes.append(nearest)
        if any(v==0 for v in codes) and not all(v==0 for v in codes):
            raise ValueError('A center run must place every selected factor at its midpoint.')
        coded_rows.append(codes)
    block_col=_resolve_factorial_block_column(worksheet,metadata)
    block_predictors,block_names,unique_blocks,has_multiple_blocks,include_blocks=_encode_blocks(
        worksheet,used,block_col,include_blocks,
        require_nonmissing=bool(metadata.get('custom_defined') and block_col is not None),
    )
    terms=_factor_terms_hierarchy(k,max_order,selected_terms)
    term_names=['*'.join(names[i] for i in term) for term in terms]
    if len(set(term_names))!=len(term_names):raise ValueError('Factor names produce ambiguous interaction labels.')
    predictors=[[math.prod(row[i] for i in term) for row in coded_rows] for term in terms]
    all_predictors=block_predictors+predictors
    all_term_names=block_names+term_names
    aliases=[]
    for i,values in enumerate(all_predictors):
        for j in range(i):
            if values==all_predictors[j] or values==[-v for v in all_predictors[j]]:
                aliases.append(all_term_names[j]+' = '+('−' if values!=all_predictors[j] else '')+all_term_names[i])
    if aliases:raise ValueError('Selected model is rank deficient; terms are confounded on the retained rows: '+ '; '.join(aliases[:8])+'. Select one representative in Terms.')
    result=multiple_regression(all_predictors,ys,confidence,predictor_names=all_term_names)
    n_blocks=len(block_names)
    for i,coefficient in enumerate(result['coefficients']):
        if i==0:
            coefficient['term_factors']=[]
            coefficient['effect']=None
            coefficient['effect_se']=None
        elif i<=n_blocks:
            coefficient['term_factors']=['Blocks']
            coefficient['effect']=2*coefficient['estimate'] if len(unique_blocks)==2 else None
            coefficient['effect_se']=2*coefficient['standard_error'] if len(unique_blocks)==2 else None
        else:
            factor_idx=i-n_blocks-1
            coefficient['term_factors']=[names[j] for j in terms[factor_idx]]
            coefficient['effect']=2*coefficient['estimate']
            coefficient['effect_se']=2*coefficient['standard_error']
        for suffix in ('low','high'):
            ci=coefficient['ci_'+suffix]
            coefficient['effect_ci_'+suffix]=None if coefficient['effect'] is None or ci is None else 2*ci
        for key in ('effect','effect_se','effect_ci_low','effect_ci_high'):
            if coefficient[key] is not None and not math.isfinite(coefficient[key]):raise ValueError('Factor effect exceeds supported numeric range.')
    result.update(method='Two-level factorial coded OLS; hierarchical selected terms',
        response_name=response.name,factor_coding=coding,terms=all_term_names,
        factor_terms=term_names,block_terms=block_names,include_blocks=include_blocks,
        blocks=len(unique_blocks) if has_multiple_blocks else 1,
        max_order=max(map(len,terms)),selected_terms=[list(term) for term in terms],row_indices=used,used_rows=used,missing=n-len(used),
        coded_factors=coded_rows,native_parity=False,
        verification_block_columns=block_predictors,design_seed=metadata.get('seed') if trusted else None,
        assumptions='Independent errors with common variance and normality for t/F inference. Selected hierarchical terms are fitted in coded units; effects equal twice coefficients. Omitted effects are assumed negligible.')
    if not include_blocks:
        result['warnings'].append('Limited coded analysis: no multiple blocks, response-surface/Taguchi models, curvature test or native parity. Omitted effects are assumed negligible.')
    if metadata.get('schema')=='statcraft-regular-fractional-v1':
        matching=len(factors)==len(metadata.get('factors',[])) and all(
            f.get('column_index')==index and f.get('name')==column.name for f,index,column in zip(metadata['factors'],factors,selected))
        if matching:
            from .fractional import alias_structure
            structure=alias_structure(metadata.get('generators'),k)
            for row in coded_rows:
                if all(value==0 for value in row):continue
                for word in structure['defining_relation']:
                    product=math.prod(row[i] for i in range(k) if word['mask']&(1<<i))
                    if product!=word['sign']:raise ValueError('Factor settings no longer match the saved fractional generators.')
            result['design_resolution']=structure['resolution']
            result['alias_structure']=[{'term':row['term'],'aliases':row['expression']} for row in structure['rows']]
            result['warnings'].append('Fractional estimates combine aliased effects; aliases are not separately estimable.')
            result['warnings'].append('Alias table describes the nominal corner fraction, excluding center rows. Letters follow the factor coding table.')
    corners={tuple(row) for row in coded_rows if all(v!=0 for v in row)}
    if len(corners)<2**k:result['warnings'].append('Not every full-factorial corner is present; estimates rely on the chosen model and retained full-rank rows.')
    if any(all(v==0 for v in row) for row in coded_rows):result['warnings'].append('Center runs included without a separate curvature term; lack-of-fit and pure error are not separated.')
    return result


def _level_or_missing(value):
    return normalize_numeric(value)


def factorial_pareto(result):
    """Build a standardized-effects plot from an estimated factorial fit."""
    if not result.get('factor_terms'):
        return None
    df_error = result.get('df_error', 0)
    if df_error <= 0:
        return None
    effects = []
    factor_terms = set(result['factor_terms'])
    for row in result.get('effects', []):
        statistic = row.get('t')
        if row['term'] in factor_terms and statistic is not None and math.isfinite(statistic):
            effects.append(dict(term=row['term'], effect=abs(statistic), p_val=row['p_value']))
    if not effects:
        return None
    effects.sort(key=lambda row: row['effect'], reverse=True)
    alpha = 1.0 - result['confidence']
    return dict(pareto_effects=effects, t_crit=float(student_t.isf(alpha / 2, df_error)),
                alpha=alpha, response_name=result['response_name'])
