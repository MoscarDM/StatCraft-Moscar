"""Tests for MPX copy-on-write shared numeric blobs and logistic/Poisson native model recovery."""
import copy
import json
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

import numpy as np

from statcraft._mpx_fixture import write_blob_fixture
from statcraft.app import Presenter
from statcraft.logistic import fit as fit_logistic
from statcraft.model import Column, Worksheet
from statcraft.mpx import load_mpx, save_mpx
from statcraft.native_mpx_models import (
    compare_native_model,
    read_native_models,
    resolve_model_recipe,
)
from statcraft.poisson_regression import fit_poisson_regression


def _rewrite_zip(path, mutator):
    with zipfile.ZipFile(path) as archive:
        members = [(info, archive.read(info)) for info in archive.infolist()]
    mutator(members)
    with zipfile.ZipFile(path, "w") as archive:
        for info, raw in members:
            archive.writestr(copy.deepcopy(info), raw)


def _date_blob_fixture(path):
    from tests.test_mpx import fixture as base_fixture

    base_fixture(path)

    def add_shared_date(members):
        for idx, (info, raw) in enumerate(members):
            if info.filename == "/sheets/1/sheet.json":
                sheet = json.loads(raw)
                body = sheet["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"]
                body["CellCt"] = 2
                body["NumericData"] = "/blobs/blob2?size=2"
                members[idx] = (info, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))
            elif info.filename == "/sheets/0/sheet.json":
                sheet = json.loads(raw)
                date_col = copy.deepcopy(sheet["Data"]["Columns"][0])
                date_col["WorksheetVarBody"]["Name"] = "DateCol"
                date_col["WorksheetVarBody"]["Format"]["Key"] = 2
                body = date_col["WorksheetVarBody"]["VarData"]["VarDataBody"]
                body["CellCt"] = 2
                body["NumericData"] = "/blobs/blob2?size=2"
                sheet["Data"]["Columns"].append(date_col)
                members[idx] = (info, json.dumps(sheet, ensure_ascii=False).encode("utf-8"))

    with zipfile.ZipFile(path) as archive:
        members = [(info, archive.read(info)) for info in archive.infolist()]
    add_shared_date(members)
    with zipfile.ZipFile(path, "w") as archive:
        for info, raw in members:
            archive.writestr(copy.deepcopy(info), raw)
        archive.writestr("/blobs/blob2", struct.pack("<2d", 43831.0, 43832.0), compress_type=zipfile.ZIP_DEFLATED)


def _logistic_project_fixture(model_family="BinaryLogisticRegression"):
    rng = np.random.default_rng(42)
    n = 60
    x = rng.normal(0.0, 1.0, n)
    cat = ["A" if i % 2 == 0 else "B" for i in range(n)]
    logits = -0.3 + 1.4 * x + np.where(np.array(cat) == "A", 0.9, 0.0)
    probs = 1.0 / (1.0 + np.exp(-logits))
    y = ["Pass" if p > 0.5 else "Fail" for p in probs]
    # Add some overlap so there is no separation
    y[0] = "Fail"
    y[1] = "Pass"
    y[2] = "Pass"
    y[3] = "Fail"

    sheet = Worksheet(
        "Data",
        columns=[
            Column("Outcome", "text", y),
            Column("Dose", "number", x.tolist()),
            Column("Group", "text", cat),
        ],
    )
    for idx, col in enumerate(sheet.columns):
        col.metadata["imported_variable_metadata"] = {"Id": f"col-{idx}", "VarId": idx + 1}

    fit_res = fit_logistic(sheet, 0, [1], [2], event="Pass")
    coefs = fit_res["coefficients"]

    def var_ref(idx, role):
        return {
            "id": f"col-{idx}",
            "variable_id": float(idx + 1),
            "name": sheet.columns[idx].name,
            "type": role,
            "data_type": "text" if sheet.columns[idx].kind == "text" else "numeric",
        }

    factors = [var_ref(1, "continuous"), var_ref(2, "categorical")]
    factors[1]["classes"] = ["A", "B"]

    pred_defs = [
        {"predictor_type": "constant", "predictor_id": -1.0, "column_id": 0.0},
        {
            "predictor_type": "continuous",
            "predictor_id": 0.0,
            "column_id": 2.0,
            "was_predictor_fit": True,
            "is_random": False,
            "is_hard_to_change": False,
            "nesting_predictor_ids": [],
        },
        {
            "predictor_type": "categorical",
            "predictor_id": 1.0,
            "column_id": 3.0,
            "text_levels": ["A", "B"],
            "was_predictor_fit": True,
            "is_random": False,
            "is_hard_to_change": False,
            "nesting_predictor_ids": [],
        },
    ]
    post_terms = [
        {
            "predictor_ids": [-1.0],
            "coefficients": [float(coefs[0]["estimate"])],
            "standard_error_coefficients": [float(coefs[0]["standard_error"])],
        },
        {
            "predictor_ids": [0.0],
            "coefficients": [float(coefs[2]["estimate"])],
            "standard_error_coefficients": [float(coefs[2]["standard_error"])],
        },
        {
            "predictor_ids": [1.0],
            "coefficients": [float(coefs[1]["estimate"])],
            "standard_error_coefficients": [float(coefs[1]["standard_error"])],
        },
    ]
    obj = {
        "model_object_type": "binary_logistic",
        "model_analysis_type": "binary_logistic",
        "link_function_type": "logit",
        "lambda": 1.0,
        "has_weights": False,
        "weights_column_id": 0.0,
        "is_categorical_response": True,
        "is_event_trial": False,
        "is_mle": True,
        "confidence": 0.95,
        "model_term_list": {"model_predictors": pred_defs, "model_terms": post_terms},
        "rows_to_use": {"rows": {"use_all_rows": True, "row_count": float(n)}},
        "log_likelihood": float(fit_res["log_likelihood"]),
        "deviance": float(fit_res["deviance"]),
        "error_degrees_of_freedom": float(fit_res["df_error"]),
    }
    state = {
        "include_constant_term": True,
        "coding": "reference",
        "standardized": False,
        "link_function_type": "logit",
        "confidence_interval": "two_sided",
        "selection_method": "none",
        "validation_type": "none",
        "confidence": 0.95,
        "event": "Pass",
        "termlist": {
            "fixed_factor_columns": factors,
            "model_terms": [{"term_columns": [factors[0]]}, {"term_columns": [factors[1]]}],
        },
    }
    model = {
        "metadata": {
            "command_id": "cmd-log",
            "worksheet_id": "ws-1",
            "model_id": 1.0,
            "model_type": "binary_logistic_regression",
            "tables": {},
            "graphs": {},
        },
        "variables": {"target": var_ref(0, "categorical"), "predictors": factors},
        "model_information": {"input_state": state},
        "post_analysis_data": {"model_object": obj},
    }
    project = SimpleNamespace(
        metadata={
            "Models": {"Items": [{"Type": model_family, "Items": [{"Id": 1, "Data": "/models/1/"}]}]},
            "Commands": {"Items": [{"Id": "cmd-log", "InputWorksheet": "ws-1", "OutputWorksheet": "ws-1"}]},
        },
        retained_members={"/models/1/.json": json.dumps({"Model": model}).encode()},
        worksheets=[sheet],
        worksheet_ids=["ws-1"],
    )
    return project, model, fit_res


def _poisson_project_fixture():
    rng = np.random.default_rng(7)
    n = 40
    x = rng.uniform(0.0, 2.0, n)
    cat = ["Low" if i % 2 == 0 else "High" for i in range(n)]
    lam = np.exp(0.4 + 0.6 * x + np.where(np.array(cat) == "High", 0.5, 0.0))
    y = rng.poisson(lam).astype(float).tolist()

    sheet = Worksheet(
        "Counts",
        columns=[
            Column("Defects", "number", y),
            Column("Speed", "number", x.tolist()),
            Column("Shift", "text", cat),
        ],
    )
    for idx, col in enumerate(sheet.columns):
        col.metadata["imported_variable_metadata"] = {"Id": f"pcol-{idx}", "VarId": idx + 1}

    fit_res = fit_poisson_regression(
        response=y,
        continuous_predictors=[x.tolist()],
        categorical_predictors=[cat],
        continuous_names=["Speed"],
        categorical_names=["Shift"],
        response_name="Defects",
        confidence=0.95,
    )
    coefs = fit_res["coefficients"]

    def var_ref(idx, role):
        return {
            "id": f"pcol-{idx}",
            "variable_id": float(idx + 1),
            "name": sheet.columns[idx].name,
            "type": role,
            "data_type": "text" if sheet.columns[idx].kind == "text" else "numeric",
        }

    factors = [var_ref(1, "continuous"), var_ref(2, "categorical")]
    factors[1]["classes"] = ["High", "Low"]

    pred_defs = [
        {"predictor_type": "constant", "predictor_id": -1.0, "column_id": 0.0},
        {
            "predictor_type": "continuous",
            "predictor_id": 0.0,
            "column_id": 2.0,
            "was_predictor_fit": True,
            "is_random": False,
            "is_hard_to_change": False,
            "nesting_predictor_ids": [],
        },
        {
            "predictor_type": "categorical",
            "predictor_id": 1.0,
            "column_id": 3.0,
            "text_levels": ["High", "Low"],
            "was_predictor_fit": True,
            "is_random": False,
            "is_hard_to_change": False,
            "nesting_predictor_ids": [],
        },
    ]
    post_terms = [
        {
            "predictor_ids": [-1.0],
            "coefficients": [float(coefs[0]["coef"])],
            "standard_error_coefficients": [float(coefs[0]["se_coef"])],
        },
        {
            "predictor_ids": [0.0],
            "coefficients": [float(coefs[1]["coef"])],
            "standard_error_coefficients": [float(coefs[1]["se_coef"])],
        },
        {
            "predictor_ids": [1.0],
            "coefficients": [float(coefs[2]["coef"])],
            "standard_error_coefficients": [float(coefs[2]["se_coef"])],
        },
    ]
    obj = {
        "model_object_type": "poisson_regression",
        "model_analysis_type": "poisson_regression",
        "link_function_type": "log",
        "lambda": 1.0,
        "has_weights": False,
        "weights_column_id": 0.0,
        "has_offset": False,
        "offset_column_id": 0.0,
        "overdispersion": False,
        "is_categorical_response": False,
        "is_event_trial": False,
        "is_mle": True,
        "confidence": 0.95,
        "model_term_list": {"model_predictors": pred_defs, "model_terms": post_terms},
        "rows_to_use": {"rows": {"use_all_rows": True, "row_count": float(n)}},
        "log_likelihood": float(fit_res["log_likelihood"]),
        "deviance": float(fit_res["deviance"]),
        "error_degrees_of_freedom": float(fit_res["df_residual"]),
    }
    state = {
        "include_constant_term": True,
        "coding": "reference",
        "standardized": False,
        "link_function_type": "log",
        "confidence_interval": "two_sided",
        "selection_method": "none",
        "validation_type": "none",
        "confidence": 0.95,
        "termlist": {
            "fixed_factor_columns": factors,
            "model_terms": [{"term_columns": [factors[0]]}, {"term_columns": [factors[1]]}],
        },
    }
    model = {
        "metadata": {
            "command_id": "cmd-pois",
            "worksheet_id": "ws-p",
            "model_id": 2.0,
            "model_type": "poisson_regression",
            "tables": {},
            "graphs": {},
        },
        "variables": {"target": var_ref(0, "continuous"), "predictors": factors},
        "model_information": {"input_state": state},
        "post_analysis_data": {"model_object": obj},
    }
    project = SimpleNamespace(
        metadata={
            "Models": {"Items": [{"Type": "PoissonRegression", "Items": [{"Id": 2, "Data": "/models/2/"}]}]},
            "Commands": {"Items": [{"Id": "cmd-pois", "InputWorksheet": "ws-p", "OutputWorksheet": "ws-p"}]},
        },
        retained_members={"/models/2/.json": json.dumps({"Model": model}).encode()},
        worksheets=[sheet],
        worksheet_ids=["ws-p"],
    )
    return project, model, fit_res


class SharedBlobCopyOnWriteTests(unittest.TestCase):
    def test_shared_numeric_blob_copy_on_write_preserves_other_column(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            source = Path(tmp) / "in.mpx"
            target = Path(tmp) / "out.mpx"
            write_blob_fixture(source)

            def share_col(members):
                for idx, (info, raw) in enumerate(members):
                    if info.filename == "/sheets/0/sheet.json":
                        doc = json.loads(raw)
                        col_copy = copy.deepcopy(doc["Data"]["Columns"][0])
                        col_copy["WorksheetVarBody"]["Name"] = "SharedCopy"
                        doc["Data"]["Columns"].append(col_copy)
                        members[idx] = (info, json.dumps(doc).encode("utf-8"))

            _rewrite_zip(source, share_col)
            p = Presenter()
            p.load(source)
            p.set_cell(0, 0, "99")
            p.save(target)

            reloaded = load_mpx(target)
            self.assertEqual(reloaded.active_worksheet.columns[0].values, [99.0, 2.0, 3.0])
            self.assertEqual(reloaded.active_worksheet.columns[1].values, [1.0, 2.0, 3.0])
            with zipfile.ZipFile(target) as out:
                doc = json.loads(out.read("/sheets/0/sheet.json"))
                ref0 = doc["Data"]["Columns"][0]["WorksheetVarBody"]["VarData"]["VarDataBody"]["NumericData"]
                ref1 = doc["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"]["NumericData"]
                self.assertEqual(ref1, "/blobs/blob1?size=3")
                self.assertNotEqual(ref0, ref1)
                self.assertTrue(ref0.startswith("/blobs/blob"))
                self.assertTrue(ref0.endswith("?size=3"))
                self.assertEqual(struct.unpack("<3d", out.read("/blobs/blob1")), (1.0, 2.0, 3.0))
                new_member = ref0.split("?", 1)[0]
                self.assertEqual(struct.unpack("<3d", out.read(new_member)), (99.0, 2.0, 3.0))

    def test_shared_date_blob_copy_on_write_and_resize(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            source = Path(tmp) / "date_in.mpx"
            target = Path(tmp) / "date_out.mpx"
            _date_blob_fixture(source)

            project = load_mpx(source)
            s0_idx = project.worksheet_uris.index("/sheets/0/sheet")
            s1_idx = project.worksheet_uris.index("/sheets/1/sheet")
            project.worksheets[s0_idx].columns[2].values = [44000.0, 44001.0, 44002.0]
            save_mpx(project, target)

            reloaded = load_mpx(target)
            self.assertEqual(reloaded.worksheets[s0_idx].columns[2].values, [44000.0, 44001.0, 44002.0])
            self.assertEqual(reloaded.worksheets[s1_idx].columns[1].values, [43831.0, 43832.0])
            with zipfile.ZipFile(target) as out:
                doc0 = json.loads(out.read("/sheets/0/sheet.json"))
                doc1 = json.loads(out.read("/sheets/1/sheet.json"))
                ref0 = doc0["Data"]["Columns"][2]["WorksheetVarBody"]["VarData"]["VarDataBody"]["NumericData"]
                ref1 = doc1["Data"]["Columns"][1]["WorksheetVarBody"]["VarData"]["VarDataBody"]["NumericData"]
                self.assertEqual(ref1, "/blobs/blob2?size=2")
                self.assertNotEqual(ref0.split("?", 1)[0], "/blobs/blob2")
                self.assertTrue(ref0.endswith("?size=3"))

    def test_editing_two_columns_sharing_same_blob_allocates_distinct_blobs(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            source = Path(tmp) / "two_in.mpx"
            target = Path(tmp) / "two_out.mpx"
            write_blob_fixture(source)

            def share_col(members):
                for idx, (info, raw) in enumerate(members):
                    if info.filename == "/sheets/0/sheet.json":
                        doc = json.loads(raw)
                        col_copy = copy.deepcopy(doc["Data"]["Columns"][0])
                        col_copy["WorksheetVarBody"]["Name"] = "SharedCopy"
                        doc["Data"]["Columns"].append(col_copy)
                        members[idx] = (info, json.dumps(doc).encode("utf-8"))

            _rewrite_zip(source, share_col)
            project = load_mpx(source)
            project.active_worksheet.columns[0].values = [10.0, 20.0, 30.0]
            project.active_worksheet.columns[1].values = [40.0, 50.0, 60.0]
            save_mpx(project, target)

            reloaded = load_mpx(target)
            self.assertEqual(reloaded.active_worksheet.columns[0].values, [10.0, 20.0, 30.0])
            self.assertEqual(reloaded.active_worksheet.columns[1].values, [40.0, 50.0, 60.0])


class NativeLogisticAndPoissonRecoveryTests(unittest.TestCase):
    def test_recover_binary_logistic_and_alias_and_refit(self):
        for family in ("BinaryLogisticRegression", "LogisticRegression"):
            with self.subTest(family=family):
                project, _, fit_res = _logistic_project_fixture(family)
                recovered = read_native_models(project)
                desc = recovered["cmd-log"]
                self.assertTrue(desc["supported"], desc.get("error"))
                self.assertEqual(desc["family"], "binary_logistic")
                self.assertEqual(desc["recipe"]["action"], "fit_binary_logistic")
                params = desc["recipe"]["parameters"]
                self.assertEqual(params["response_index"], 0)
                self.assertEqual(params["continuous_indices"], [1])
                self.assertEqual(params["categorical_indices"], [2])
                self.assertEqual(params["event"], "Pass")
                self.assertIsNone(params["trials_index"])

                # Test resolve_model_recipe after column move
                sheet = project.worksheets[0]
                moved = sheet.columns.pop(2)
                moved.name = "GroupRenamed"
                sheet.columns.insert(0, moved)
                resolved = resolve_model_recipe(project, desc)
                self.assertEqual(resolved["parameters"]["categorical_indices"], [0])
                self.assertEqual(resolved["parameters"]["response_index"], 1)
                self.assertEqual(resolved["parameters"]["continuous_indices"], [2])

                # Test Presenter.refit_native_model
                p = Presenter()
                p.native_project = SimpleNamespace(
                    worksheets=project.worksheets,
                    worksheet_ids=project.worksheet_ids,
                    active_index=0,
                )
                p.worksheet = project.worksheets[0]
                entry = {"origin": "native", "native_model": desc}
                p.history.append(entry)
                fresh = p.refit_native_model(entry)
                self.assertEqual(fresh["result"]["analysis"], "binary_logistic")
                self.assertTrue(fresh["native_model_source"]["comparison"]["matches_saved_native"])

    def test_binary_logistic_unsupported_guards(self):
        cases = [
            ("weighted", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_weights", True)),
            ("event_trial", lambda m: m["post_analysis_data"]["model_object"].__setitem__("is_event_trial", True)),
            ("probit_link", lambda m: m["post_analysis_data"]["model_object"].__setitem__("link_function_type", "probit")),
            ("subset", lambda m: m["post_analysis_data"]["model_object"]["rows_to_use"]["rows"].__setitem__("use_all_rows", False)),
            ("no_intercept", lambda m: m["model_information"]["input_state"].__setitem__("include_constant_term", False)),
            ("incomplete_terms", lambda m: m["post_analysis_data"]["model_object"]["model_term_list"]["model_terms"].pop()),
        ]
        for label, mutate in cases:
            with self.subTest(case=label):
                project, model, _ = _logistic_project_fixture()
                mutate(model)
                project.retained_members["/models/1/.json"] = json.dumps({"Model": model}).encode()
                desc = read_native_models(project)["cmd-log"]
                self.assertFalse(desc["supported"])

    def test_recover_poisson_regression_and_refit(self):
        project, _, _ = _poisson_project_fixture()
        recovered = read_native_models(project)
        desc = recovered["cmd-pois"]
        self.assertTrue(desc["supported"], desc.get("error"))
        self.assertEqual(desc["family"], "poisson_regression")
        self.assertEqual(desc["recipe"]["action"], "poisson_regression")
        params = desc["recipe"]["parameters"]
        self.assertEqual(params["response_index"], 0)
        self.assertEqual(params["continuous_indices"], [1])
        self.assertEqual(params["categorical_indices"], [2])
        self.assertIsNone(params["offset_index"])

        # Test resolve_model_recipe after column move
        sheet = project.worksheets[0]
        moved = sheet.columns.pop(1)
        sheet.columns.append(moved)
        resolved = resolve_model_recipe(project, desc)
        self.assertEqual(resolved["parameters"]["continuous_indices"], [2])
        self.assertEqual(resolved["parameters"]["categorical_indices"], [1])

        # Test Presenter.refit_native_model
        p = Presenter()
        p.native_project = SimpleNamespace(
            worksheets=project.worksheets,
            worksheet_ids=project.worksheet_ids,
            active_index=0,
        )
        p.worksheet = project.worksheets[0]
        entry = {"origin": "native", "native_model": desc}
        p.history.append(entry)
        fresh = p.refit_native_model(entry)
        self.assertEqual(fresh["result"]["analysis"], "poisson_regression")
        self.assertTrue(fresh["native_model_source"]["comparison"]["matches_saved_native"])

    def test_poisson_unsupported_guards(self):
        cases = [
            ("weighted", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_weights", True)),
            ("has_offset", lambda m: m["post_analysis_data"]["model_object"].__setitem__("has_offset", True)),
            ("offset_var", lambda m: m["variables"].__setitem__("offset", {"id": "pcol-1", "variable_id": 2.0})),
            ("overdispersion", lambda m: m["post_analysis_data"]["model_object"].__setitem__("overdispersion", True)),
            ("quasi_poisson", lambda m: m["post_analysis_data"]["model_object"].__setitem__("is_quasi_poisson", True)),
            ("dispersion_param", lambda m: m["post_analysis_data"]["model_object"].__setitem__("dispersion_parameter", 2.5)),
            ("identity_link", lambda m: m["post_analysis_data"]["model_object"].__setitem__("link_function_type", "identity")),
            ("incomplete_terms", lambda m: m["post_analysis_data"]["model_object"]["model_term_list"]["model_terms"].pop()),
        ]
        for label, mutate in cases:
            with self.subTest(case=label):
                project, model, _ = _poisson_project_fixture()
                mutate(model)
                project.retained_members["/models/2/.json"] = json.dumps({"Model": model}).encode()
                desc = read_native_models(project)["cmd-pois"]
                self.assertFalse(desc["supported"])
