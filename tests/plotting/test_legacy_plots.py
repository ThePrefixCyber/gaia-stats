"""Optional parity suite: python -m unittest discover -s tests/plotting -v."""
import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from gaia_stats.legacy_plots import (ROOT, PLOTS, LegacyPlotError,
                                    load_historical_csv, make_plot)


def historical_plot(*args, **kwargs):
    return make_plot(*args, methodology="historical", **kwargs)


def original_figure(kind, data, faction):
    """Execute unmodified function bodies, capturing the original display call.

    Independent of the adapter's AST transform. Excludes notebook top-level I/O.
    """
    spec = PLOTS[kind]
    notebook = json.loads((ROOT / (spec.notebook + '.ipynb')).read_text())
    namespace = dict(pd=pd, np=np, numpy=np, px=px, go=go, make_subplots=make_subplots)
    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue
        tree = ast.parse(''.join(cell['source']))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                try:
                    namespace[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(node, ast.FunctionDef):
                exec(compile(ast.Module(body=[node], type_ignores=[]), spec.notebook, 'exec'), namespace)
    namespace['factions'] = [faction]
    results = []
    args = (data.copy(deep=True), 4) if spec.data_first else (4, data.copy(deep=True))
    with patch.object(go.Figure, 'show', lambda figure: results.append(figure)):
        namespace[spec.function](*args)
    return results[0]


def figure_digest(figure):
    canonical = json.dumps(json.loads(figure.to_json()), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


class OriginalPlotParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_historical_csv()
        cls.baseline = json.loads((Path(__file__).parent / 'legacy_baseline.json').read_text())

    def setUp(self):
        self.warning_context = warnings.catch_warnings()
        self.warning_context.__enter__()
        warnings.simplefilter('ignore', FutureWarning)
        warnings.simplefilter('ignore', pd.errors.SettingWithCopyWarning)
        self.addCleanup(self.warning_context.__exit__, None, None, None)

    def test_original_sources_and_csv_match_frozen_baseline(self):
        for name, expected in self.baseline['inputs'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected, name)
        self.assertEqual(self.data.shape, (5687, 489))

    def test_all_eight_views_match_original_terrans_regression(self):
        before = self.data.copy(deep=True)
        for kind, expected in self.baseline['terrans'].items():
            with self.subTest(kind=kind):
                figure = historical_plot(kind, self.data, faction='terrans')
                self.assertEqual(figure_digest(figure), expected['sha256'])
                self.assertEqual(len(figure.data), expected['traces'])
        pd.testing.assert_frame_equal(self.data, before)

    def test_all_views_match_unmodified_functions_for_second_faction(self):
        for kind in PLOTS:
            with self.subTest(kind=kind):
                original = original_figure(kind, self.data, 'xenos')
                adapted = historical_plot(kind, self.data, faction='xenos')
                self.assertEqual(figure_digest(adapted), figure_digest(original))

    def test_basic_frequency_denominator_and_dropped_filter(self):
        clean = self.data.loc[self.data[[f'pos_{p}_dropped' for p in range(1, 5)]].eq(False).all(axis=1)]
        total = sum(clean[f'pos_{p}_faction'].eq('terrans').sum() for p in range(1, 5))
        figure = historical_plot('basic-tech-frequency', self.data, faction='terrans')
        tech = '1q_1o'
        for rank, trace in enumerate(figure.data, 1):
            numerator = (clean[f'pos_{rank}_faction'].eq('terrans')
                         & clean[f'pos_{rank}_tech_taken_{tech}'].eq(True)).sum()
            self.assertEqual(trace.y[0], round(100 * numerator / total, 3))

    def test_point_sources_keep_bid_adjustment_and_strict_score_cutoff(self):
        clean = self.data.loc[self.data[[f'pos_{p}_dropped' for p in range(1, 5)]].eq(False).all(axis=1)].copy()
        figure = historical_plot('point-sources', self.data, faction='terrans')
        for trace, rank in zip(figure.data, (4, 3, 2, 1)):
            score = clean[f'pos_{rank}_score'] + clean[f'pos_{rank}_score_bid'].abs()
            mask = clean[f'pos_{rank}_faction'].eq('terrans') & score.gt(100)
            expected = np.round(-100 * clean.loc[mask, f'pos_{rank}_score_charge'] / score[mask], 2)
            actual = np.asarray(trace.y)[np.asarray(trace.x) == 'charge']
            np.testing.assert_array_equal(actual, expected)

    def test_invalid_player_faction_and_schema_fail_explicitly(self):
        for kwargs in ({'players': 3, 'faction': 'terrans'}, {'faction': 'darkanians'}):
            with self.assertRaises(LegacyPlotError):
                historical_plot('basic-tech-score', self.data, **kwargs)
        with self.assertRaisesRegex(LegacyPlotError, 'missing historical column'):
            historical_plot('point-sources', self.data.drop(columns='pos_1_score_bid'), faction='terrans')
        with self.assertRaisesRegex(LegacyPlotError, 'No historical games'):
            historical_plot('basic-tech-score', self.data.iloc[:0], faction='terrans')

    def test_notebook_top_level_loads_and_display_do_not_run(self):
        with patch.object(pd, 'read_pickle', side_effect=AssertionError('Unpickling forbidden')), \
                patch.object(pd, 'read_csv', side_effect=AssertionError('Implicit loading forbidden')), \
                patch.object(go.Figure, 'show', side_effect=AssertionError('Display forbidden')):
            self.assertEqual(len(historical_plot('basic-tech-frequency', self.data, faction='terrans').data), 4)
