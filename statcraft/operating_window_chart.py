"""3D Operating Window CAD surface and Confirmation Evaluation interval plots."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QPolygonF
from .spatial_view import DEFAULT_VIEW, project_point
from .model_plots_chart import (
    BORDER,
    MUTED,
    SLATE,
    _draw_cad_card,
    _draw_viewcube,
    _fmt,
    _pad_bounds,
)


STATUS_COLORS = {
    'drift_feasible': QColor(22, 163, 74),     # Emerald
    'nominal_only': QColor(245, 158, 11),      # Amber
    'out_of_spec': QColor(225, 29, 72),        # Slate-Rose
}


def _quad_color(statuses, outside_flags):
    if 'out_of_spec' in statuses:
        base = STATUS_COLORS['out_of_spec']
    elif 'nominal_only' in statuses:
        base = STATUS_COLORS['nominal_only']
    else:
        base = STATUS_COLORS['drift_feasible']
    out_count = sum(1 for flag in outside_flags if flag)
    if out_count == 0:
        return QColor(base), False
    # Desaturate toward cool slate and lower opacity outside the convex design hull
    blend_r = int(base.red() * 0.45 + 203 * 0.55)
    blend_g = int(base.green() * 0.45 + 213 * 0.55)
    blend_b = int(base.blue() * 0.45 + 225 * 0.55)
    return QColor(blend_r, blend_g, blend_b, 145), True


def prepare(chart, result):
    """Populate ChartWidget panels for operating_window_3d or confirmation_evaluation."""
    chart.panels = []
    chart.panel_columns = 1
    chart.note = ''
    analysis = result.get('analysis')

    if analysis == 'operating_window_3d':
        z_flat = [v for row in result['z_grid'] for v in row]
        z_min, z_max = float(min(z_flat)), float(max(z_flat))
        panel = dict(
            kind='operating_window_3d',
            title=result.get('title', '3D Operating Window'),
            x_name=result['x_name'],
            y_name=result['y_name'],
            y_label=result['primary_response_name'],
            x_grid=result['x_grid'],
            y_grid=result['y_grid'],
            z_grid=result['z_grid'],
            z_min=z_min,
            z_max=z_max,
            status_grid=result['status_grid'],
            nominal_margin_grid=result['nominal_margin_grid'],
            drift_margin_grid=result['drift_margin_grid'],
            limiting_grid=result['limiting_grid'],
            outside_region_grid=result['outside_region_grid'],
            design_hull=result.get('design_hull', []),
            holds=result.get('hold_summary', []),
            drifts=result.get('drifts', []),
            predicted_optimum=result.get('predicted_optimum'),
            robust_setting=result.get('robust_setting'),
            selected_setting=result.get('selected_setting'),
            window_summary=result.get('window_summary', {}),
            empty_window=bool(result.get('empty_window')),
        )
        chart.panels.append(panel)
        chart.setMinimumWidth(720)
        chart.setMinimumHeight(490)
        drift_txt = ', '.join(f"{d['name']} ±{_fmt(d['delta'])}" for d in result.get('drifts', [])) or 'None'
        hold_txt = ', '.join(f"{h['name']}={_fmt(h['value'])}" for h in result.get('hold_summary', [])) or 'None'
        chart.note = (
            f"Drifts: {drift_txt}   |   Holds: {hold_txt}   |   "
            f"Drift-Feasible Region: {result.get('window_summary', {}).get('drift_feasible_pct', 0):.1f}% of grid"
        )
        return

    if analysis == 'confirmation_evaluation':
        settings = result.get('settings', [])
        if not settings:
            raise ValueError('Confirmation evaluation contains no settings to chart.')
        resp_names = [r['response_name'] for r in settings[0].get('responses', [])]
        for r_idx, r_name in enumerate(resp_names):
            tracks = []
            for s in settings:
                rec = s['responses'][r_idx]
                tracks.append(dict(
                    setting_key=s['key'],
                    setting_label=s['label'],
                    factors=s['factors'],
                    **rec,
                ))
            chart.panels.append(dict(
                kind='confirmation_interval',
                title=f"Confirmation Runs: {r_name} ({result.get('confidence', 0.95) * 100:.0f}% PI, m={result.get('replicates', 1)})",
                response_name=r_name,
                tracks=tracks,
            ))
        chart.setMinimumWidth(680)
        chart.setMinimumHeight(max(360, 230 * len(chart.panels)))
        verdict = 'CONFIRMED' if result.get('confirmed') else 'NOT CONFIRMED'
        chart.note = f"Overall Verdict: {verdict}   |   Worksheet: {result.get('worksheet_name', '')}"
        return

    raise ValueError(f"Unsupported operating window chart analysis '{analysis}'.")


def draw_panel(chart, p, area, panel):
    """Render an Operating Window 3D surface or Confirmation Evaluation panel."""
    kind = panel.get('kind')
    if kind == 'operating_window_3d':
        _draw_operating_window_3d(chart, p, area, panel)
    elif kind == 'confirmation_interval':
        _draw_confirmation_interval(chart, p, area, panel)


def _draw_operating_window_3d(chart, p, area, panel):
    x_grid = panel['x_grid']
    y_grid = panel['y_grid']
    z_grid = panel['z_grid']
    z_min = panel['z_min']
    z_max = panel['z_max']
    x_name = panel['x_name']
    y_name = panel['y_name']
    status_grid = panel['status_grid']
    drift_margin_grid = panel['drift_margin_grid']
    limiting_grid = panel['limiting_grid']
    outside_grid = panel['outside_region_grid']
    holds = panel.get('holds', [])

    legend_w = min(158.0, max(124.0, area.width() * 0.22))
    cube_rect = QRectF(
        area.left() + 40.0,
        area.top() + 42.0,
        max(150.0, area.width() - 64.0 - legend_w),
        max(150.0, area.height() - 78.0),
    )
    chart.remember_axes(cube_rect)
    panel['cube_rect'] = cube_rect

    x_bounds = _pad_bounds(x_grid)
    y_bounds = _pad_bounds(y_grid)
    z_bounds = _pad_bounds([z_min, z_max])
    ranges = [x_bounds, y_bounds, z_bounds]
    state = getattr(chart, 'view_state', DEFAULT_VIEW)
    viewport = (cube_rect.left(), cube_rect.top(), cube_rect.width(), cube_rect.height())

    def projected(pt):
        return project_point(pt, ranges, state, viewport)

    def proj2d(pt):
        px, py, _ = projected(pt)
        return QPointF(px, py)

    is_dragging = getattr(chart, '_is_dragging', False)
    step = 2 if is_dragging else 1

    grid_proj = {}
    grid_qpt = {}
    surface_vertices = []
    for r in range(len(y_grid)):
        grid_proj[r] = {}
        grid_qpt[r] = {}
        for c in range(len(x_grid)):
            pt = (float(x_grid[c]), float(y_grid[r]), float(z_grid[r][c]))
            px, py, depth = projected(pt)
            grid_proj[r][c] = (px, py, depth)
            qpos = QPointF(px, py)
            grid_qpt[r][c] = qpos
            if not is_dragging:
                surface_vertices.append(dict(
                    pt=pt,
                    pos=qpos,
                    depth=depth,
                    r=r,
                    c=c,
                    status=status_grid[r][c],
                    drift_margin=drift_margin_grid[r][c],
                    limiting=limiting_grid[r][c],
                ))
    if not is_dragging:
        panel['surface_vertices'] = surface_vertices

    # Bounding cube wireframe
    lows = [r[0] for r in ranges]
    highs = [r[1] for r in ranges]
    corners = [[highs[i] if bits & (1 << i) else lows[i] for i in range(3)] for bits in range(8)]
    p.setPen(QPen(QColor('#dce3e9'), 1.0))
    for bits, corner in enumerate(corners):
        for axis in range(3):
            if not bits & (1 << axis):
                p.drawLine(proj2d(corner), proj2d(corners[bits | (1 << axis)]))

    # Project 2D convex hull of experimental design runs onto the base z plane
    design_hull = panel.get('design_hull') or []
    if len(design_hull) >= 3:
        hull_pts = [proj2d((pt[0], pt[1], lows[2])) for pt in design_hull]
        p.save()
        p.setPen(QPen(QColor('#0f766e'), 1.6, Qt.PenStyle.DashLine))
        p.setBrush(QColor(20, 184, 166, 22))
        p.drawPolygon(QPolygonF(hull_pts))
        p.restore()

    # Depth-sorted feasibility quads
    faces = []
    r_indices = list(range(0, len(y_grid), step))
    if r_indices[-1] != len(y_grid) - 1:
        r_indices.append(len(y_grid) - 1)
    c_indices = list(range(0, len(x_grid), step))
    if c_indices[-1] != len(x_grid) - 1:
        c_indices.append(len(x_grid) - 1)

    for i in range(len(r_indices) - 1):
        r0, r1 = r_indices[i], r_indices[i + 1]
        for j in range(len(c_indices) - 1):
            c0, c1 = c_indices[j], c_indices[j + 1]
            p0 = grid_proj[r0][c0]
            p1 = grid_proj[r0][c1]
            p2 = grid_proj[r1][c1]
            p3 = grid_proj[r1][c0]
            cam_depth = (p0[2] + p1[2] + p2[2] + p3[2]) * 0.25
            statuses = (status_grid[r0][c0], status_grid[r0][c1], status_grid[r1][c1], status_grid[r1][c0])
            outsides = (outside_grid[r0][c0], outside_grid[r0][c1], outside_grid[r1][c1], outside_grid[r1][c0])
            faces.append((
                cam_depth,
                statuses,
                outsides,
                [grid_qpt[r0][c0], grid_qpt[r0][c1], grid_qpt[r1][c1], grid_qpt[r1][c0]],
            ))

    p.save()
    for _, statuses, outsides, qpts in sorted(faces, key=lambda item: item[0]):
        col, is_out = _quad_color(statuses, outsides)
        if is_dragging:
            col.setAlpha(min(col.alpha(), 180))
        pen_col = QColor('#94a3b8') if is_out else QColor('#334155')
        pen_style = Qt.PenStyle.DotLine if is_out else Qt.PenStyle.SolidLine
        p.setBrush(col)
        p.setPen(QPen(pen_col, 0.55, pen_style))
        p.drawPolygon(QPolygonF(qpts))
    p.restore()

    # Candidate markers with drop lines to base plane
    if not is_dragging:
        candidates = []
        if panel.get('predicted_optimum'):
            candidates.append(('predicted_optimum', panel['predicted_optimum'], '#e11d48', 'Predicted Optimum (Cliff Risk)'))
        if panel.get('selected_setting'):
            candidates.append(('selected_setting', panel['selected_setting'], '#4f46e5', 'Selected Setting'))
        if panel.get('robust_setting'):
            candidates.append(('robust_setting', panel['robust_setting'], '#15803d', 'Best Compromise' if panel['empty_window'] else 'Robust Setting'))

        for key_name, cand, col_hex, tip_hdr in candidates:
            pt = (float(cand['x']), float(cand['y']), float(cand['z']))
            base_pt = (float(cand['x']), float(cand['y']), lows[2])
            pos = proj2d(pt)
            base_pos = proj2d(base_pt)
            p.save()
            p.setPen(QPen(QColor(col_hex), 1.4, Qt.PenStyle.DashLine))
            p.drawLine(base_pos, pos)
            p.setPen(QPen(QColor('#ffffff'), 1.6))
            p.setBrush(QColor(col_hex))
            radius = 6.0 if key_name == 'robust_setting' else 5.0
            p.drawEllipse(pos, radius, radius)
            p.restore()

            drift_state = 'Drift-Feasible' if cand.get('worst_case_feasible') else (
                'Fails Drift' if cand.get('nominal_feasible') else 'Out of Spec'
            )
            outside_note = '\n⚠ Outside Design Region' if cand.get('outside_design_region') else ''
            tooltip = (
                f"{tip_hdr} ({drift_state})\n"
                f"{x_name}: {_fmt(cand['x'])}, {y_name}: {_fmt(cand['y'])}\n"
                f"{panel['y_label']}: {_fmt(cand['z'])}\n"
                f"Min Drift Std Margin: {_fmt(cand.get('min_drift_std_margin'))} "
                f"(Limiting: {cand.get('limiting_response', '')}){outside_note}"
            )
            chart.remember_point_hover(QRectF(pos.x() - 10, pos.y() - 10, 20, 20), tooltip)

    # Probe CAD inspection card
    active_card = getattr(chart, 'active_cad_card', None)
    if not is_dragging and active_card and active_card.get('mode') == 'probe_3d':
        pr_x, pr_y, pr_fit = active_card['x'], active_card['y'], active_card['fit']
        pr_pos = proj2d((pr_x, pr_y, pr_fit))
        p.save()
        p.setPen(QPen(QColor('#38bdf8'), 1.8))
        p.setBrush(QColor(56, 189, 248, 75))
        p.drawEllipse(pr_pos, 6.0, 6.0)
        p.restore()
        card_w = min(204.0, cube_rect.width() * 0.44)
        card_h = 92.0 if holds else 76.0
        _draw_cad_card(
            chart, p,
            QRectF(cube_rect.left() + 8.0, cube_rect.top() + 6.0, card_w, card_h),
            '✦ Window Point', '#1e293b', pr_fit, x_name, pr_x, y_name, pr_y, holds,
        )

    _draw_viewcube(chart, p, cube_rect)

    # 3D Axes
    origin = proj2d(lows)
    axis_names = [str(x_name), str(y_name), str(panel.get('y_label', 'Fit'))]
    p.setFont(QFont('Segoe UI', 8, QFont.Weight.DemiBold))
    for i, label in enumerate(axis_names):
        vals = lows[:]
        vals[i] = highs[i]
        end = proj2d(vals)
        p.setPen(QPen(QColor('#536573'), 1.3))
        p.drawLine(origin, end)
        delta = end - origin
        length = math.hypot(delta.x(), delta.y())
        ux, uy = (delta.x() / length, delta.y() / length) if length > 1 else (0.0, -1.0)
        lbl_center = end + QPointF(ux * 22, uy * 18)
        lx = max(area.left() + 4.0, min(lbl_center.x() - 56.0, area.right() - legend_w - 118.0))
        ly = max(area.top() + 24.0, min(lbl_center.y() - 10.0, area.bottom() - 22.0))
        lbl_rect = QRectF(lx, ly, 112.0, 20.0)
        p.fillRect(lbl_rect, QColor(255, 255, 255, 215))
        chart._text(p, lbl_rect, label[:18], SLATE, Qt.AlignmentFlag.AlignCenter)

    # Legend card
    leg = QRectF(cube_rect.right() + 8.0, cube_rect.top() + 6.0, legend_w - 8.0, cube_rect.height() - 12.0)
    p.fillRect(leg, QColor('#f8fafb'))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(BORDER), 1.0))
    p.drawRect(leg)

    cy = leg.top() + 8.0
    p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
    chart._text(p, QRectF(leg.left() + 8, cy, leg.width() - 16, 16), 'Feasibility', SLATE, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    cy += 18.0

    p.setFont(QFont('Segoe UI', 7.5))
    swatches = [
        (STATUS_COLORS['drift_feasible'], 'Drift-Feasible'),
        (STATUS_COLORS['nominal_only'], 'Breaks Under Drift'),
        (STATUS_COLORS['out_of_spec'], 'Out of Spec'),
        (QColor(148, 163, 184, 145), 'Outside Design Hull'),
    ]
    for col, txt in swatches:
        sw = QRectF(leg.left() + 8, cy + 2, 11, 11)
        p.fillRect(sw, col)
        p.setPen(QPen(QColor(BORDER), 0.8))
        p.drawRect(sw)
        chart._text(p, QRectF(sw.right() + 6, cy, leg.width() - 30, 15), txt, SLATE, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cy += 17.0

    cy += 6.0
    p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
    chart._text(p, QRectF(leg.left() + 8, cy, leg.width() - 16, 16), 'Settings', SLATE, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    cy += 18.0

    pins = []
    if panel.get('robust_setting'):
        rob = panel['robust_setting']
        label = 'Compromise' if panel['empty_window'] else 'Robust'
        pins.append(('#15803d', f"{label}: {_fmt(rob['z'])}"))
    if panel.get('predicted_optimum'):
        opt = panel['predicted_optimum']
        pins.append(('#e11d48', f"Optimum: {_fmt(opt['z'])}"))
    if panel.get('selected_setting'):
        sel = panel['selected_setting']
        label = 'Original' if sel.get('label') == 'Original Recommended Setting' else 'Selected'
        pins.append(('#4f46e5', f"{label}: {_fmt(sel['z'])}"))
    p.setFont(QFont('Segoe UI', 7.5))
    for col_hex, txt in pins:
        if cy + 16 > leg.bottom():
            break
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(col_hex))
        p.drawEllipse(QPointF(leg.left() + 13, cy + 7.5), 4.0, 4.0)
        chart._text(p, QRectF(leg.left() + 23, cy, leg.width() - 30, 15), txt, SLATE, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cy += 16.0

    summary = panel.get('window_summary', {})
    if cy + 24 <= leg.bottom():
        cy += 4.0
        chart._text(
            p,
            QRectF(leg.left() + 8, cy, leg.width() - 16, 16),
            f"Window: {summary.get('drift_feasible_pct', 0):.1f}%",
            MUTED,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )


def _draw_confirmation_interval(chart, p, area, panel):
    tracks = panel.get('tracks', [])
    if not tracks:
        return

    all_vals = []
    for tr in tracks:
        for key in ('lower', 'upper', 'indiv_pi_low', 'indiv_pi_high', 'confirm_pi_low', 'confirm_pi_high', 'fit', 'observed_mean'):
            v = tr.get(key)
            if v is not None:
                all_vals.append(float(v))
        all_vals.extend(float(v) for v in tr.get('observed_values', []))

    x_lo, x_hi = _pad_bounds(all_vals)
    span = max(1e-9, x_hi - x_lo)
    plot = area.adjusted(148.0, 42.0, -28.0, -40.0)
    if plot.width() <= 60 or plot.height() <= 40:
        return
    chart.remember_axes(plot)

    def x_px(val):
        return plot.left() + (float(val) - x_lo) / span * plot.width()

    # Plot frame
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.fillRect(plot, QColor('#ffffff'))
    p.setPen(QPen(QColor(BORDER), 1.0))
    p.drawRect(plot)

    # Feasible spec shading & LSL/USL lines
    ref_lo = tracks[0].get('lower')
    ref_hi = tracks[0].get('upper')
    spec_left = x_px(ref_lo) if ref_lo is not None else plot.left()
    spec_right = x_px(ref_hi) if ref_hi is not None else plot.right()
    spec_left = max(plot.left(), min(plot.right(), spec_left))
    spec_right = max(plot.left(), min(plot.right(), spec_right))
    if spec_right > spec_left:
        p.fillRect(QRectF(spec_left, plot.top(), spec_right - spec_left, plot.height()), QColor(220, 252, 231, 95))

    p.setFont(QFont('Segoe UI', 7.5, QFont.Weight.DemiBold))
    for spec_val, tag in ((ref_lo, 'LSL'), (ref_hi, 'USL')):
        if spec_val is None:
            continue
        sx = x_px(spec_val)
        p.setPen(QPen(QColor('#0f766e'), 1.3, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(sx, plot.top()), QPointF(sx, plot.bottom()))
        lbl_rect = QRectF(max(plot.left(), min(sx - 34, plot.right() - 68)), plot.top() - 16, 68, 14)
        chart._text(p, lbl_rect, f"{tag}={_fmt(spec_val)}", '#0f766e', Qt.AlignmentFlag.AlignCenter)

    # Axis ticks and compact legend key
    p.setFont(QFont('Segoe UI', 8))
    for i in range(6):
        tv = x_lo + span * i / 5.0
        tx = x_px(tv)
        p.setPen(QPen(QColor(BORDER), 0.9))
        p.drawLine(QPointF(tx, plot.bottom()), QPointF(tx, plot.bottom() + 4))
        chart._text(p, QRectF(tx - 28, plot.bottom() + 6, 56, 15), _fmt(tv), MUTED, Qt.AlignmentFlag.AlignCenter)
    p.setFont(QFont('Segoe UI', 7))
    chart._text(
        p,
        QRectF(plot.left(), plot.bottom() + 22, plot.width(), 14),
        'Key: ◇ Fit   |   Blue: Confirm Mean PI   |   Gray: Indiv PI   |   ● Obs Mean   |   ○ Replicate',
        MUTED,
        Qt.AlignmentFlag.AlignCenter,
    )

    # Render each setting track
    n_tr = len(tracks)
    track_h = plot.height() / max(1, n_tr)
    for idx, tr in enumerate(tracks):
        cy = plot.top() + (idx + 0.5) * track_h
        if idx > 0:
            p.setPen(QPen(QColor('#e2e8f0'), 1.0))
            p.drawLine(QPointF(plot.left(), plot.top() + idx * track_h), QPointF(plot.right(), plot.top() + idx * track_h))

        # Left setting label
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.DemiBold))
        chart._text(
            p,
            QRectF(area.left() + 8, cy - 16, 132, 16),
            tr['setting_label'],
            SLATE,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        p.setFont(QFont('Segoe UI', 7.5))
        status_col = '#15803d' if tr.get('confirmed') else '#be123c'
        chart._text(
            p,
            QRectF(area.left() + 8, cy + 2, 132, 14),
            tr.get('status', ''),
            status_col,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        # Individual PI whisker (thin slate)
        ix0, ix1 = x_px(tr['indiv_pi_low']), x_px(tr['indiv_pi_high'])
        p.setPen(QPen(QColor('#94a3b8'), 1.2))
        p.drawLine(QPointF(ix0, cy - 10), QPointF(ix1, cy - 10))
        p.drawLine(QPointF(ix0, cy - 14), QPointF(ix0, cy - 6))
        p.drawLine(QPointF(ix1, cy - 14), QPointF(ix1, cy - 6))

        # Confirmation-mean PI bracket (bold blue)
        cx0, cx1 = x_px(tr['confirm_pi_low']), x_px(tr['confirm_pi_high'])
        p.setPen(QPen(QColor('#0284c7'), 2.6))
        p.drawLine(QPointF(cx0, cy), QPointF(cx1, cy))
        p.drawLine(QPointF(cx0, cy - 6), QPointF(cx0, cy + 6))
        p.drawLine(QPointF(cx1, cy - 6), QPointF(cx1, cy + 6))

        # Predicted Fit diamond
        fx = x_px(tr['fit'])
        diamond = QPolygonF([QPointF(fx, cy - 6), QPointF(fx + 5, cy), QPointF(fx, cy + 6), QPointF(fx - 5, cy)])
        p.setPen(QPen(QColor('#0f172a'), 1.2))
        p.setBrush(QColor('#ffffff'))
        p.drawPolygon(diamond)

        # Observed runs (slightly offset below confirmation bar)
        obs_vals = tr.get('observed_values', [])
        obs_rids = tr.get('observed_run_ids', [])
        for r_i, ov in enumerate(obs_vals):
            ox = x_px(ov)
            oy = cy + 12.0 + ((r_i % 3) - 1) * 3.0
            p.setPen(QPen(QColor('#334155'), 1.1))
            p.setBrush(QColor('#cbd5e1'))
            p.drawEllipse(QPointF(ox, oy), 3.2, 3.2)
            rid = obs_rids[r_i] if r_i < len(obs_rids) else f'Run {r_i + 1}'
            chart.remember_point_hover(
                QRectF(ox - 7, oy - 7, 14, 14),
                f"{tr['setting_label']} · {rid}\nObserved {panel['response_name']}: {_fmt(ov)}",
            )

        # Observed mean marker
        mx = x_px(tr['observed_mean'])
        p.setPen(QPen(QColor('#ffffff'), 1.4))
        p.setBrush(QColor('#16a34a' if tr.get('confirmed') else '#e11d48'))
        p.drawEllipse(QPointF(mx, cy), 5.5, 5.5)
        chart.remember_point_hover(
            QRectF(mx - 9, cy - 9, 18, 18),
            f"{tr['setting_label']} ({tr.get('status')})\n"
            f"Observed Mean (n={tr.get('m')}): {_fmt(tr['observed_mean'])}\n"
            f"Predicted Fit: {_fmt(tr['fit'])}\n"
            f"Confirmation PI: [{_fmt(tr['confirm_pi_low'])}, {_fmt(tr['confirm_pi_high'])}]",
        )
