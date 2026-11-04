"""Importable adapter for Tim Gladyshev's original base-game Plotly figures.

Only definitions and literal constants from six checked-in notebooks are loaded.
Notebook imports, data loads, display settings and top-level invocations never run.
The sole function-body change captures ``fig.show()`` as a returned figure.
Historical calculations are available explicitly via methodology="historical".
The default corrects six affected plot families without modifying source notebooks. This module
is separate from the production WSGI app and requires requirements-plotting.txt.
"""
import ast
from dataclasses import dataclass
from pathlib import Path
import json

from .eligibility import eligible_frame, excluded_csv_game

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PlotSpec:
    notebook: str
    function: str
    data_first: bool = False


PLOTS = {
    'basic-tech-frequency': PlotSpec('basic_tech', 'plot_base_freq_remote'),
    'basic-tech-score': PlotSpec('basic_tech', 'plot_base_track_remote'),
    'advanced-tech-frequency': PlotSpec('advanced_techs', 'plot_adv_freq_remote'),
    'advanced-tech-score': PlotSpec('advanced_techs', 'plot_adv_track_remote'),
    'round-one-structures': PlotSpec('r1_structs', 'plot_r1_structs_remote'),
    'round-scoring': PlotSpec('round_scoring', 'make_round_scoring_heatmap', True),
    'final-scoring': PlotSpec('final_scorings_deltas', 'make_final_scoring_heatmap', True),
    'point-sources': PlotSpec('scoring_methods', 'make_corr_plots', True),
}


class LegacyPlotError(ValueError):
    """Historical input is incompatible or original code cannot plot this subset."""


class _CaptureFigures(ast.NodeTransformer):
    def visit_Expr(self, node):
        call = node.value
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == 'fig' and call.func.attr == 'show'
                and not call.args and not call.keywords):
            return ast.copy_location(ast.Expr(value=ast.Call(
                func=ast.Attribute(value=ast.Name(id='_figures', ctx=ast.Load()),
                                   attr='append', ctx=ast.Load()),
                args=[ast.Name(id='fig', ctx=ast.Load())], keywords=[])), node)
        return self.generic_visit(node)


def _load_namespace(spec, *, capture=True):
    # Imports are lazy so production/test environments need no plotting packages.
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    path = ROOT / (spec.notebook + '.ipynb')
    notebook = json.loads(path.read_text())
    source = '\n'.join(''.join(cell['source']) for cell in notebook['cells']
                       if cell['cell_type'] == 'code')
    tree = ast.parse(source, filename=str(path))
    namespace = {'pd': pd, 'np': np, 'numpy': np, 'px': px, 'go': go,
                 'make_subplots': make_subplots, '_figures': []}
    definitions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            definitions.append(node)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            namespace[node.targets[0].id] = value
    module = ast.Module(body=definitions, type_ignores=[])
    if capture:
        module = _CaptureFigures().visit(module)
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), namespace)
    return namespace


def load_historical_csv(path=None):
    """Load the committed 5,687-game four-player CSV; never deserialize pickle.

    Other CSV paths are allowed for explicit offline work, but must carry Tim's
    wide schema. No conversion from the new explorer's JSON schema is implicit.
    """
    import pandas as pd
    return pd.read_csv(path or ROOT / 'data/remote_four_players_data.csv')


def make_plot(kind, data, *, players=4, faction, methodology="corrected", min_elo=None, _observations=None):
    """Return one Plotly figure, corrected by default or explicitly historical.

    Does not open a browser, write files, mutate input or load data implicitly.
    Corrected empty cohorts show no observations; missing columns fail explicitly.
    Use fig.to_html()/write_html() to export the result from an offline caller.
    """
    eligible = eligible_frame(data)
    if _observations is not None:
        # Prepared observations may predate the policy. Remove the whole game
        # based on either the dataframe or the prepared provenance.
        blocked = set(data['id']) - set(eligible['id']) if 'id' in data else set()
        blocked.update(r['game'] for r in _observations
                       if excluded_csv_game(r['values']))
        _observations = [r for r in _observations if r['game'] not in blocked]
    data = eligible
    if kind not in PLOTS:
        raise ValueError('Unknown plot: ' + str(kind))
    if players not in (2, 3, 4):
        raise ValueError('Choose 2, 3 or 4 players')
    if 'num_players' not in data or not data['num_players'].eq(players).all():
        raise LegacyPlotError('Data must contain only the requested player count')
    if data.empty:
        raise LegacyPlotError('No historical games supplied')
    if methodology not in ('corrected', 'historical'):
        raise ValueError('Unknown methodology')
    from .corrected_plots import CORRECTED, make_corrected
    if methodology == 'corrected' and kind in CORRECTED:
        try:
            return make_corrected(kind, data, players, faction, min_elo=min_elo, prepared_rows=_observations)
        except KeyError as error:
            raise LegacyPlotError(f'{kind} requires missing historical column {error}') from error
    if min_elo is not None:
        raise LegacyPlotError('Elo filtering is implemented for the six corrected plot families only')
    spec = PLOTS[kind]
    namespace = _load_namespace(spec)
    if faction not in namespace['factions']:
        raise LegacyPlotError('Unknown historical base-game faction: ' + str(faction))
    columns = [f'pos_{i}_faction' for i in range(1, players + 1)]
    missing = set(columns) - set(data.columns)
    if missing:
        raise LegacyPlotError('Missing historical columns: ' + ', '.join(sorted(missing)))
    if not data[columns].eq(faction).any(axis=None):
        raise LegacyPlotError('No historical games for faction: ' + faction)
    namespace['factions'] = [faction]
    # Retain caller data even if a historical function mutates its dataframe.
    args = (data.copy(deep=True), players) if spec.data_first else (players, data.copy(deep=True))
    try:
        namespace[spec.function](*args)
    except KeyError as error:
        raise LegacyPlotError(f'{kind} requires missing historical column {error}') from error
    except (ZeroDivisionError, IndexError) as error:
        raise LegacyPlotError(f'{kind}: original calculation cannot handle this subset ({error})') from error
    figures = namespace['_figures']
    if len(figures) != 1:
        raise LegacyPlotError(f'Expected one original figure, received {len(figures)}')
    figure = figures[0]
    if methodology == 'corrected':
        figure.update_layout(title=str(figure.layout.title.text) + ' · legacy bid-restored scores; historical score/quantile cutoffs')
        for trace in figure.data:
            if trace.name and trace.name.startswith('rank '):
                trace.name = trace.name.replace('rank ', 'bid-restored order ') + ' (ties broken by original player order)'
    return figure
