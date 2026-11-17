"""TDD tests for Task 12: Native MPX model recovery for Reliability, ARIMA, and Mixed-Effects (REML)."""
import copy
import json
from types import SimpleNamespace
import unittest

import numpy as np

from statcraft.app import Presenter
from statcraft.arima import fit_arima
from statcraft.mixed_reml import fit_mixed_reml
from statcraft.model import Column, Worksheet
from statcraft.native_mpx_models import (
    compare_native_model,
    read_native_models,
    resolve_entry_recipe,
    resolve_model_recipe,
)
from statcraft.reliability_engine import run_reliability_analysis


def _make_project(family_type, model, sheet, command_id="cmd-1", worksheet_id="ws-1", model_id=1):
    uri = f"/models/{model_id}/"
    project = SimpleNamespace(
        metadata={
            "Models": {"Items": [{"Type": family_type, "Items": [{"Id": model_id, "Data": uri}]}]},
            "Commands": {"Items": [{"Id": command_id, "InputWorksheet": worksheet_id, "OutputWorksheet": worksheet_id}]},
        },
        retained_members={f"{uri}.json": json.dumps({"Model": model}).encode("utf-8")},
        worksheets=[sheet],
        worksheet_ids=[worksheet_id],
        active_index=0,
    )
    return project


def _var_ref(sheet, idx, role):
    col = sheet.columns[idx]
    return {
        "id": col.metadata["imported_variable_metadata"]["Id"],
        "variable_id": float(col.metadata["imported_variable_metadata"]["VarId"]),
        "name": col.name,
        "type": role,
        "data_type": "text" if col.kind == "text" else "numeric",
    }


def _reliability_fixture(family_type="ParametricDistributionAnalysis", dist_name="weibull", censored=True):
    times = [12.5, 18.2, 24.0, 29.1, 35.4, 41.0, 48.5, 55.2, 62.0, 70.3, 81.1, 95.0]
    censors = ["F", "F", "C", "F", "F", "C", "F", "F", "F", "C", "F", "F"]
    cols = [Column("FailureTime", "number", times)]
    if censored:
        cols.append(Column("Status", "text", censors))
    sheet = Worksheet("RelData", columns=cols)
    for idx, col in enumerate(sheet.columns):
        col.metadata["imported_variable_metadata"] = {"Id": f"rel-col-{idx}", "VarId": idx + 1}

    fit_res = run_reliability_analysis(
        time_values=times,
        censor_values=censors if censored else None,
        censor_value="C" if censored else None,
        dist_name=dist_name,
        confidence_level=0.95,
    )

    variables = {"target": _var_ref(sheet, 0, "continuous")}
    if censored:
        censor_ref = _var_ref(sheet, 1, "categorical")
        variables["censor"] = censor_ref

    state = {
        "distribution": dist_name,
        "estimation_method": "mle",
        "censoring_type": "right" if censored else "none",
        "censor_value": "C" if censored else None,
        "confidence": 0.95,
        "confidence_interval": "two_sided",
        "has_weights": False,
        "has_threshold": False,
    }
    obj = {
        "model_object_type": "parametric_distribution_analysis",
        "model_analysis_type": "parametric_distribution_analysis",
        "distribution": dist_name,
        "estimation_method": "mle",
        "censoring_type": "right" if censored else "none",
        "censor_value": "C" if censored else None,
        "has_weights": False,
        "weights_column_id": 0.0,
        "has_threshold": False,
        "threshold": 0.0,
        "confidence": 0.95,
        "parameters": dict(fit_res["parameters"]),
        "log_likelihood": float(fit_res["log_likelihood"]),
        "mttf": float(fit_res["mttf"]),
        "rows_to_use": {"rows": {"use_all_rows": True, "row_count": float(len(times))}},
    }
    model = {
        "metadata": {
            "command_id": "cmd-1",
            "worksheet_id": "ws-1",
            "model_id": 1.0,
            "model_type": "parametric_distribution_analysis",
            "tables": {},
            "graphs": {},
        },
        "variables": variables,
        "model_information": {"input_state": state},
        "post_analysis_data": {"model_object": obj},
    }
    return _make_project(family_type, model, sheet), model, fit_res


def _arima_fixture(family_type="ARIMA", p=1, d=0, q=0, P=0, D=0, Q=0, S=1, include_constant=True, method="CLS"):
    rng = np.random.default_rng(7)
    n = 60
    y = np.zeros(n)
    eps = rng.normal(0.0, 0.5, n)
    for t in range(1, n):
        y[t] = 2.0 + 0.65 * y[t - 1] + eps[t]
    sheet = Worksheet("SeriesData", columns=[Column("Demand", "number", y.tolist())])
    sheet.columns[0].metadata["imported_variable_metadata"] = {"Id": "ts-col-0", "VarId": 1}

    fit_res = fit_arima(
        values=y.tolist(),
        p=p,
        d=d,
        q=q,
        P=P,
        D=D,
        Q=Q,
        S=S,
        include_constant=include_constant,
        method=method,
        conf_level=95.0,
        forecasts=0,
    )

    state = {
        "p": p,
        "d": d,
        "q": q,
        "P": P,
        "D": D,
        "Q": Q,
        "S": S,
        "include_constant_term": include_constant,
        "method": method,
        "confidence": 0.95,
        "transform": "none",
        "box_cox": False,
        "has_weights": False,
    }
    obj = {
        "model_object_type": "arima",
        "model_analysis_type": "arima",
        "p": p,
        "d": d,
        "q": q,
        "P": P,
        "D": D,
        "Q": Q,
        "S": S,
        "include_constant_term": include_constant,
        "method": method,
        "lambda": 1.0,
        "has_weights": False,
        "weights_column_id": 0.0,
        "confidence": 0.95,
        "estimates": [
            {"term": e["type"], "coef": float(e["coef"]), "se_coef": float(e["se"])}
            for e in fit_res["estimates"]
        ],
        "mean_square_error": float(fit_res["ms"]),
        "error_degrees_of_freedom": float(fit_res["df"]),
        "rows_to_use": {"rows": {"use_all_rows": True, "row_count": float(n)}},
    }
    model = {
        "metadata": {
            "command_id": "cmd-1",
            "worksheet_id": "ws-1",
            "model_id": 1.0,
            "model_type": "arima",
            "tables": {},
            "graphs": {},
        },
        "variables": {"target": _var_ref(sheet, 0, "continuous")},
        "model_information": {"input_state": state},
        "post_analysis_data": {"model_object": obj},
    }
    return _make_project(family_type, model, sheet), model, fit_res


def _mixed_fixture(family_type="MixedEffectsModel"):
    rng = np.random.default_rng(123)
    batches = ["B1", "B2", "B3", "B4", "B5", "B6"]
    treatments = ["Ctrl", "Trt"]
    y_vals, trt_vals, batch_vals, temp_vals = [], [], [], []
    batch_effects = {b: rng.normal(0.0, 1.5) for b in batches}
    for b in batches:
        for t in treatments:
            for rep in range(3):
                temp = 20.0 + 2.0 * rep
                y = 10.0 + (2.5 if t == "Trt" else 0.0) + 0.3 * temp + batch_effects[b] + rng.normal(0.0, 0.4)
                y_vals.append(float(y))
                trt_vals.append(t)
                temp_vals.append(float(temp))
                batch_vals.append(b)
    sheet = Worksheet(
        "MixedData",
        columns=[
            Column("Strength", "number", y_vals),
            Column("Treatment", "text", trt_vals),
            Column("Temp", "number", temp_vals),
            Column("Batch", "text", batch_vals),
        ],
    )
    for idx, col in enumerate(sheet.columns):
        col.metadata["imported_variable_metadata"] = {"Id": f"mix-col-{idx}", "VarId": idx + 1}

    fit_res = fit_mixed_reml(sheet, response_index=0, fixed_indices=[1, 2], random_indices=[3])

    trt_ref = _var_ref(sheet, 1, "categorical")
    trt_ref["classes"] = ["Ctrl", "Trt"]
    temp_ref = _var_ref(sheet, 2, "continuous")
    batch_ref = _var_ref(sheet, 3, "categorical")
    batch_ref["classes"] = batches

    state = {
        "estimation_method": "reml",
        "covariance_structure": "variance_components",
        "include_constant_term": True,
        "coding": "reference",
        "has_weights": False,
        "confidence": 0.95,
        "termlist": {
            "fixed_factor_columns": [trt_ref, temp_ref],
            "random_factor_columns": [batch_ref],
            "model_terms": [
                {"term_columns": [trt_ref]},
                {"term_columns": [temp_ref]},
                {"term_columns": [batch_ref]},
            ],
        },
    }
    obj = {
        "model_object_type": "mixed_effects_model",
        "model_analysis_type": "mixed_effects_model",
        "estimation_method": "reml",
        "covariance_structure": "variance_components",
        "lambda": 1.0,
        "has_weights": False,
        "weights_column_id": 0.0,
        "confidence": 0.95,
        "fixed_effects": [
            {"term": fe["term"], "coef": float(fe["coef"]), "se_coef": float(fe["se_coef"])}
            for fe in fit_res["fixed_effects"]
        ],
        "variance_components": [
            {"source": vc["source"], "var_comp": float(vc["var_comp"])}
            for vc in fit_res["variance_components"]
        ],
        "neg2_rell": float(fit_res["neg2_rell"]),
        "rows_to_use": {"rows": {"use_all_rows": True, "row_count": float(len(y_vals))}},
    }
    model = {
        "metadata": {
            "command_id": "cmd-1",
            "worksheet_id": "ws-1",
            "model_id": 1.0,
            "model_type": "mixed_effects_model",
            "tables": {},
            "graphs": {},
        },
        "variables": {
            "target": _var_ref(sheet, 0, "continuous"),
            "fixed": [trt_ref, temp_ref],
            "random": [batch_ref],
        },
        "model_information": {"input_state": state},
        "post_analysis_data": {"model_object": obj},
    }
    return _make_project(family_type, model, sheet), model, fit_res


class NativeModelRecoveryPhase2Tests(unittest.TestCase):
    def test_reliability_weibull_censored_recovery_resolve_and_refit(self):
        for family_type in ("DistributionAnalysis", "ParametricDistributionAnalysis"):
            for dist in ("weibull", "lognormal", "normal", "exponential"):
                with self.subTest(family_type=family_type, dist=dist):
                    project, _, _ = _reliability_fixture(family_type=family_type, dist_name=dist, censored=True)
                    models = read_native_models(project)
                    desc = models["cmd-1"]
                    self.assertTrue(desc["supported"], desc.get("error"))
                    self.assertEqual(desc["family"], "reliability_distribution")
                    self.assertEqual(desc["recipe"]["action"], "reliability_distribution")
                    self.assertEqual(desc["recipe"]["parameters"]["settings"]["dist_name"], dist)
                    self.assertEqual(desc["recipe"]["parameters"]["settings"]["censor_index"], 1)
                    self.assertEqual(desc["recipe"]["parameters"]["settings"]["censor_value"], "C")

                    # Reorder columns and verify resolve_model_recipe + resolve_entry_recipe
                    sheet = project.worksheets[0]
                    moved_censor = sheet.columns.pop(1)
                    moved_censor.name = "StatusRenamed"
                    sheet.columns.insert(0, moved_censor)
                    resolved = resolve_model_recipe(project, desc)
                    self.assertEqual(resolved["parameters"]["settings"]["censor_index"], 0)
                    self.assertEqual(resolved["parameters"]["settings"]["column_index"], 1)

                    entry = {"origin": "native", "native_model": desc}
                    entry_recipe = resolve_entry_recipe(entry, sheet)
                    self.assertEqual(entry_recipe, resolved)

                    # End-to-end refit
                    p = Presenter()
                    p.native_project = project
                    p.worksheet = sheet
                    p.history.append(entry)
                    fresh = p.refit_native_model(entry)
                    self.assertEqual(fresh["result"]["analysis"], "reliability_distribution")
                    self.assertTrue(fresh["native_model_source"]["comparison"]["matches_saved_native"])

    def test_reliability_uncensored_and_unsupported_guards(self):
        project, _, _ = _reliability_fixture(dist_name="weibull", censored=False)
        desc = read_native_models(project)["cmd-1"]
        self.assertTrue(desc["supported"])
        self.assertNotIn("censor_index", desc["recipe"]["parameters"]["settings"])

        cases = [
            ("arbitrary_censoring", lambda m: m["model_information"]["input_state"].__setitem__("censoring_type", "arbitrary")),
            ("interval_censoring", lambda m: m["model_information"]["input_state"].__setitem__("censoring_type", "interval")),
            ("rank_regression", lambda m: m["model_information"]["input_state"].__setitem__("estimation_method", "least_squares")),
            ("unsupported_dist", lambda m: m["model_information"]["input_state"].__setitem__("distribution", "gamma")),
            ("weighted", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_weights", True)),
            ("threshold", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_threshold", True)),
            ("subset", lambda m: m["post_analysis_data"]["model_object"]["rows_to_use"]["rows"].__setitem__("use_all_rows", False)),
        ]
        for label, mutator in cases:
            with self.subTest(label=label):
                p, m, _ = _reliability_fixture()
                mutator(m)
                p.retained_members["/models/1/.json"] = json.dumps({"Model": m}).encode("utf-8")
                d = read_native_models(p)["cmd-1"]
                self.assertFalse(d["supported"])
                self.assertIn("error", d)

    def test_arima_recovery_resolve_and_refit(self):
        for family_type in ("ARIMA", "BoxJenkinsARIMA"):
            with self.subTest(family_type=family_type):
                project, _, _ = _arima_fixture(family_type=family_type, p=1, d=0, q=0, method="CLS")
                desc = read_native_models(project)["cmd-1"]
                self.assertTrue(desc["supported"], desc.get("error"))
                self.assertEqual(desc["family"], "arima")
                self.assertEqual(desc["recipe"]["action"], "arima")
                st = desc["recipe"]["parameters"]["settings"]
                self.assertEqual((st["p"], st["d"], st["q"]), (1, 0, 0))
                self.assertEqual(st["method"], "CLS")

                sheet = project.worksheets[0]
                sheet.columns.insert(0, Column("Extra", "number", [0.0] * sheet.row_count))
                resolved = resolve_model_recipe(project, desc)
                self.assertEqual(resolved["parameters"]["settings"]["series_index"], 1)

                entry = {"origin": "native", "native_model": desc}
                self.assertEqual(resolve_entry_recipe(entry, sheet), resolved)

                p = Presenter()
                p.native_project = project
                p.worksheet = sheet
                p.history.append(entry)
                fresh = p.refit_native_model(entry)
                self.assertEqual(fresh["result"]["analysis"], "arima")
                self.assertTrue(fresh["native_model_source"]["comparison"]["matches_saved_native"])

    def test_arima_unsupported_guards(self):
        cases = [
            ("box_cox", lambda m: m["model_information"]["input_state"].__setitem__("transform", "log")),
            ("lambda_nonzero", lambda m: m["post_analysis_data"]["model_object"].__setitem__("lambda", 0.5)),
            ("weighted", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_weights", True)),
            ("subset", lambda m: m["post_analysis_data"]["model_object"]["rows_to_use"]["rows"].__setitem__("use_all_rows", False)),
            ("invalid_seasonal", lambda m: m["model_information"]["input_state"].__setitem__("D", 1)),
            ("bad_method", lambda m: m["model_information"]["input_state"].__setitem__("method", "CSS_OLD")),
            ("exogenous", lambda m: m["variables"].__setitem__("predictors", [copy.deepcopy(m["variables"]["target"])])),
        ]
        for label, mutator in cases:
            with self.subTest(label=label):
                p, m, _ = _arima_fixture()
                mutator(m)
                p.retained_members["/models/1/.json"] = json.dumps({"Model": m}).encode("utf-8")
                d = read_native_models(p)["cmd-1"]
                self.assertFalse(d["supported"])
                self.assertIn("error", d)

    def test_mixed_reml_recovery_resolve_and_refit(self):
        for family_type in ("MixedEffectsModel", "MixedModel"):
            with self.subTest(family_type=family_type):
                project, _, _ = _mixed_fixture(family_type=family_type)
                desc = read_native_models(project)["cmd-1"]
                self.assertTrue(desc["supported"], desc.get("error"))
                self.assertEqual(desc["family"], "mixed_reml")
                self.assertEqual(desc["recipe"]["action"], "fit_mixed_reml")
                self.assertEqual(desc["recipe"]["parameters"]["response_index"], 0)
                self.assertEqual(desc["recipe"]["parameters"]["fixed_indices"], [1, 2])
                self.assertEqual(desc["recipe"]["parameters"]["random_indices"], [3])

                sheet = project.worksheets[0]
                moved = sheet.columns.pop(3)
                moved.name = "BatchRenamed"
                sheet.columns.insert(0, moved)
                resolved = resolve_model_recipe(project, desc)
                self.assertEqual(resolved["parameters"]["response_index"], 1)
                self.assertEqual(resolved["parameters"]["fixed_indices"], [2, 3])
                self.assertEqual(resolved["parameters"]["random_indices"], [0])

                entry = {"origin": "native", "native_model": desc}
                self.assertEqual(resolve_entry_recipe(entry, sheet), resolved)

                p = Presenter()
                p.native_project = project
                p.worksheet = sheet
                p.history.append(entry)
                fresh = p.refit_native_model(entry)
                self.assertEqual(fresh["result"]["analysis"], "mixed_reml")
                self.assertTrue(fresh["native_model_source"]["comparison"]["matches_saved_native"])

    def test_mixed_unsupported_guards(self):
        cases = [
            ("ml_method", lambda m: m["model_information"]["input_state"].__setitem__("estimation_method", "ml")),
            ("ar1_cov", lambda m: m["model_information"]["input_state"].__setitem__("covariance_structure", "ar1")),
            ("no_random", lambda m: m["variables"].__setitem__("random", [])),
            ("interaction", lambda m: m["model_information"]["input_state"]["termlist"]["model_terms"][0]["term_columns"].append(copy.deepcopy(m["variables"]["fixed"][1]))),
            ("weighted", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_weights", True)),
            ("subset", lambda m: m["post_analysis_data"]["model_object"]["rows_to_use"]["rows"].__setitem__("use_all_rows", False)),
            ("effects_coding", lambda m: m["model_information"]["input_state"].__setitem__("coding", "effects")),
        ]
        for label, mutator in cases:
            with self.subTest(label=label):
                p, m, _ = _mixed_fixture()
                mutator(m)
                p.retained_members["/models/1/.json"] = json.dumps({"Model": m}).encode("utf-8")
                d = read_native_models(p)["cmd-1"]
                self.assertFalse(d["supported"])
                self.assertIn("error", d)


if __name__ == "__main__":
    unittest.main()
