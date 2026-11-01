"""Offline original-plot generation and lightweight, read-only cache serving.

Build: python -m gaia_stats.legacy_cache --cache /tmp/gaia-classic \
    --csv 4=data/remote_four_players_data.csv
No dataframe loading or figure generation occurs in an HTTP request.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .__main__ import atomic_json

FACTIONS = ('terrans', 'lantids', 'hadsch-hallas', 'ivits', 'baltaks', 'geodens',
            'xenos', 'gleens', 'ambas', 'taklons', 'bescods', 'firaks', 'itars', 'nevlas')


ORIGINAL_PLOT_PATHS = {
    'adv_techs_analysis/taken_freq': 'advanced-tech-frequency',
    'adv_techs_analysis/pos_on_score': 'advanced-tech-score',
    'base_tech_analysis/taken_freq': 'basic-tech-frequency',
    'base_tech_analysis/pos_on_score': 'basic-tech-score',
    'r1_structs_analysis/freq_and_score': 'round-one-structures',
    'final_scoring/heatmap_v1': 'final-scoring',
    'round_scoring/heatmap_v1': 'round-scoring',
    'scoring/dist_on_pos': 'point-sources',
}


def is_classic_path(path):
    return (path.startswith('/classic/') or re.match(r'/[234]p/', path) is not None
            or path in ('/view_plot/index.html', '/view_tables/index.html')
            or path in ('/data/two_players_data.csv', '/data/three_players_data.csv',
                        '/data/four_players_data.csv'))


def build_cache(cache_root, csv_paths, comparison_path=None):
    """Build sequentially, then publish a complete cache by atomic pointer swap.

    Only one player-count dataframe and one figure are live at a time. Builds
    that fail never replace the current cache. Prior builds are kept for recovery.
    """
    from .legacy_plots import PLOTS, make_plot
    from .corrected_plots import observations
    import pandas as pd
    from plotly.offline import get_plotlyjs

    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='build-', dir=root))
    manifest = {'schema_version': 1, 'ruleset': 'base', 'source': 'Tim Gladyshev original notebooks',
                'methodology': 'corrected-v1 (six families); explicitly labelled legacy structure/source views',
                'datasets': {}, 'plots': list(PLOTS), 'factions': list(FACTIONS)}
    try:
        (stage / 'plots').mkdir()
        (stage / 'data').mkdir()
        (stage / 'plotly.min.js').write_text(get_plotlyjs())
        for players, source in sorted(csv_paths.items()):
            if players not in (2, 3, 4):
                raise ValueError('CSV player counts must be 2, 3 or 4')
            source = Path(source)
            frame = pd.read_csv(source)
            if frame.empty or not frame['num_players'].eq(players).all():
                raise ValueError(f'{source}: expected nonempty {players}-player data')
            record = {'games': len(frame), 'columns': len(frame.columns),
                      'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                      'download': f'/classic/data/{players}.csv', 'available': {}}
            shutil.copyfile(source, stage / 'data' / f'{players}.csv')
            try:
                prepared = observations(frame, players)
            except KeyError as error:
                raise ValueError(f"Missing historical column: {error}") from error
            for faction in FACTIONS:
                if not frame[[f'pos_{p}_faction' for p in range(1, players + 1)]].eq(faction).any(axis=None):
                    continue
                record['available'][faction] = []
                for kind in PLOTS:
                    figure = make_plot(kind, frame, players=players, faction=faction, _observations=prepared)
                    figure.write_html(stage / 'plots' / f'{players}-{faction}-{kind}.html',
                                      include_plotlyjs='/classic/assets/plotly.min.js', full_html=True)
                    record['available'][faction].append(kind)
                    del figure
            manifest['datasets'][str(players)] = record
            del frame
        if not manifest['datasets']:
            raise ValueError('Supply at least one historical CSV')
        if comparison_path is not None:
            from .legacy_comparison import validate_aggregates
            comparison_source = Path(comparison_path)
            aggregates = json.loads(comparison_source.read_text())
            validate_aggregates(aggregates)
            if set(aggregates) - set(manifest['datasets']):
                raise ValueError('Comparison player counts require matching imported CSVs')
            shutil.copyfile(comparison_source, stage / 'comparisons.json')
            manifest['comparisons'] = {'player_counts': sorted(aggregates),
                'sha256': hashlib.sha256(comparison_source.read_bytes()).hexdigest(),
                'source': 'https://gpstats.dev/dat.json',
                'kind': 'historical-marginal-aggregates'}
        atomic_json(stage / 'manifest.json', manifest)
        atomic_json(root / 'current.json', {'build': stage.name})
        return manifest
    except BaseException:
        shutil.rmtree(stage)
        raise


def _current(cache_root):
    root = Path(cache_root)
    pointer = json.loads((root / 'current.json').read_text())
    name = pointer['build']
    if not isinstance(name, str) or not re.fullmatch(r'build-[A-Za-z0-9_-]+', name):
        raise ValueError('Invalid cache pointer')
    return root / name


def cache_response(cache_root, path, query):
    """Return bytes/type/download name; strict allowlists prevent path traversal."""
    pages = {'/classic/': 'index.html', '/classic/view_plot': 'plot.html',
             '/view_plot/index.html': 'plot.html',
             '/classic/compare': 'compare.html', '/view_tables/index.html': 'compare.html'}
    csv_aliases = {'/data/two_players_data.csv': '2', '/data/three_players_data.csv': '3',
                   '/data/four_players_data.csv': '4'}
    if path in csv_aliases:
        path = '/classic/data/' + csv_aliases[path] + '.csv'
    original = re.fullmatch(r'/([234])p/(.+)/([a-z-]+)\.html', path)
    if original:
        players, chart_path, faction = original.groups()
        if chart_path not in ORIGINAL_PLOT_PATHS:
            raise FileNotFoundError(path)
        query = dict(query, players=players, faction=faction, plot=ORIGINAL_PLOT_PATHS[chart_path])
        path = '/classic/plot'
    if path in pages:
        page = Path(__file__).resolve().parents[1] / 'web/classic' / pages[path]
        return page.read_bytes(), 'text/html; charset=utf-8', None
    if path == '/classic/assets/comparison.js':
        script = Path(__file__).resolve().parents[1] / 'web/classic/comparison.js'
        return script.read_bytes(), 'application/javascript', None
    base = _current(cache_root)
    if path == '/classic/api/catalog':
        return (base / 'manifest.json').read_bytes(), 'application/json', None
    if path == '/classic/api/comparison':
        from .legacy_comparison import compare
        data = json.loads((base / 'comparisons.json').read_text())
        return json.dumps(compare(data, query), allow_nan=False).encode(), 'application/json', None
    if path == '/classic/assets/plotly.min.js':
        return (base / 'plotly.min.js').read_bytes(), 'application/javascript', None
    match = re.fullmatch(r'/classic/data/([234])\.csv', path)
    if match:
        players = match.group(1)
        return (base / 'data' / f'{players}.csv').read_bytes(), 'text/csv', f'gaia-base-{players}-players.csv'
    if path == '/classic/plot':
        from .legacy_plots import PLOTS  # module itself has no heavy imports
        players, faction, kind = query.get('players'), query.get('faction'), query.get('plot')
        if players not in ('2', '3', '4') or faction not in FACTIONS or kind not in PLOTS:
            raise ValueError('Choose a supported player count, base faction and original plot')
        filename = f'{players}-{faction}-{kind}.html'
        body = (base / 'plots' / filename).read_bytes()
        download = None
        if query.get('download') == '1':
            javascript = (base / 'plotly.min.js').read_bytes()
            body = re.sub(rb'<script[^>]+src="/classic/assets/plotly.min.js"[^>]*></script>',
                          lambda match: b'<script>' + javascript + b'</script>', body)
            download = 'gaia-base-' + filename
        return body, 'text/html; charset=utf-8', download
    raise FileNotFoundError(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--csv', action='append', required=True, metavar='PLAYERS=PATH')
    parser.add_argument('--comparisons', help='Original published dat.json aggregates')
    args = parser.parse_args()
    sources = {}
    for value in args.csv:
        players, path = value.split('=', 1)
        if int(players) in sources:
            parser.error('Duplicate player count')
        sources[int(players)] = path
    manifest = build_cache(args.cache, sources, args.comparisons)
    print(json.dumps({players: data['games'] for players, data in manifest['datasets'].items()}))


if __name__ == '__main__':
    main()
