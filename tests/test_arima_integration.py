import unittest

import numpy as np

from statcraft.arima import difference_series, undifference_forecasts, fit_arima


class ArimaIntegrationTests(unittest.TestCase):
    def test_manual_fit_rejects_gaps_without_compacting_time(self):
        for missing in (None, float('nan'), float('inf'), '', 'bad'):
            values = list(range(30))
            values[12] = missing
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'row 13'):
                fit_arima(values)

    def test_manual_fit_rejects_invalid_settings(self):
        for settings in ({'p': -1}, {'d': 1.5}, {'q': True}, {'D': -1},
                         {'S': 0}, {'S': 1, 'P': 1}, {'forecasts': -1},
                         {'conf_level': 100}, {'conf_level': float('nan')}, {'max_iter': 0}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                fit_arima(list(range(30)), **settings)

    def test_rejected_analysis_preserves_worksheet_and_history(self):
        from statcraft.app import Presenter
        from statcraft.model import Column, Worksheet
        presenter = Presenter()
        values = list(range(30))
        values[12] = None
        presenter.worksheet = Worksheet('Series', [Column('Response', values=values)])
        with self.assertRaisesRegex(ValueError, 'row 13'):
            presenter.arima(settings={'series_index': 0, 'store_fits': True,
                                      'store_residuals': True, 'store_forecasts': True, 'forecasts': 3})
        self.assertEqual(len(presenter.worksheet.columns), 1)
        self.assertEqual(presenter.worksheet.columns[0].values, values)
        self.assertEqual(presenter.history, [])

    def test_reconstructs_future_values_for_all_dialog_orders(self):
        values = np.random.default_rng(42).normal(size=100)
        for d in range(6):
            for D in range(4):
                for period in (1, 4, 12):
                    with self.subTest(d=d, D=D, period=period):
                        future = difference_series(values, d=d, D=D, S=period)[-8:]
                        actual = undifference_forecasts(values[:-8], future, d=d, D=D, S=period)
                        np.testing.assert_allclose(actual, values[-8:], atol=1e-7)

    def test_empty_forecast_returns_no_history(self):
        self.assertEqual(undifference_forecasts(np.arange(20.), [], d=1), [])

    def test_insufficient_history_has_clear_error(self):
        with self.assertRaisesRegex(ValueError, 'history'):
            undifference_forecasts(np.arange(3.), [1.], d=2, D=1, S=4)
