"""Offline compact SQLite import of Tim's wide CSVs; bounded read-only queries."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile


def number(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None


def convert(game, count):
    if any(game.get(f'pos_{p}_dropped') != 'False' for p in range(1,count+1)):
        return []
    scores=[number(game.get(f'pos_{p}_score')) for p in range(1,count+1)]
    if any(s is None for s in scores):return []
    techs={k.removeprefix('tech_'):v for k,v in game.items() if k.startswith('tech_') and v}
    rounds=[game[f'round_{i}_scoring'] for i in range(1,7)]
    finals=[game[f'final_scoring_{i}'] for i in (1,2)]
    rows=[]
    for p,score in enumerate(scores,1):
        prefix=f'pos_{p}_'
        owned=[{'tile':tile,'slot':slot} for slot,tile in techs.items()
               if game.get(prefix+('adv_tech_taken_' if slot.startswith('adv-') else 'tech_taken_')+tile)=='True']
        structures={kind:number(game.get(prefix+'buildings_r_1_'+kind)) for kind in ('m','ts','lab','PI','ac1','ac2')}
        sources={k.removeprefix(prefix+'score_'):number(v) for k,v in game.items() if k.startswith(prefix+'score_')}
        # Preserve signed CSV contributions verbatim; no claim of ledger reconciliation.
        sources={k:v for k,v in sources.items() if v is not None}
        tech_score=number(game.get(prefix+'tech_score'))
        if tech_score is not None:sources['research']=tech_score
        rows.append({'game_id':game['id'],'ruleset':'base','faction':game[prefix+'faction'],
            'player_count':count,'score':score,'rank':1+sum(s>score for s in scores),
            'win_share':1/scores.count(max(scores)) if score==max(scores) else 0,
            'elo':number(game.get(prefix+'elo')),'layout':game.get('map_layout') or 'unknown',
            'auction':'unknown','faction_variant':game.get('balance_variant') or 'unknown',
            'faction_variant_version':'unknown','official_center_sectors':'unknown',
            'round_scorings':rounds,'final_scorings':finals,'technologies':techs,
            'ship_technologies':{},'owned_technologies':owned,
            'round_one_structures':structures if all(v is not None for v in structures.values()) else None,
            'vp_sources':sources,'score_verified':True,'score_basis':'CSV final score; ledger not reverified',
            'lf_2p_4qic_effective':False,'opponents':[],'table_elo':None,
            'bid':number(game.get(prefix+'score_bid'))})
    return rows


def build(csvs, destination):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='base-cohort-',suffix='.sqlite',dir=destination.parent);os.close(fd)
    counts={};catalog={k:set() for k in ('faction','layout','auction','faction_variant','round_scorings','final_scorings','advanced_technologies')}
    try:
        with sqlite3.connect(temp) as db:
            db.execute('CREATE TABLE observations (game_id TEXT, faction TEXT, player_count INTEGER, elo REAL, layout TEXT, auction TEXT, faction_variant TEXT, payload TEXT, PRIMARY KEY(game_id,faction))')
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
            for count,path in sorted(csvs.items()):
                accepted=rejected=records=0
                with Path(path).open(newline='') as handle:
                    for game in csv.DictReader(handle):
                        if number(game.get('num_players'))!=count:raise ValueError('Wrong CSV player count')
                        rows=convert(game,count)
                        if not rows:rejected+=1;continue
                        for row in rows:
                            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',tuple(row[k] for k in ('game_id','faction','player_count','elo','layout','auction','faction_variant'))+(json.dumps(row,separators=(',',':')),))
                            for key in ('faction','layout','auction','faction_variant'):catalog[key].add(row[key])
                            for key in ('round_scorings','final_scorings'):catalog[key].update(row[key])
                            catalog['advanced_technologies'].update(t for s,t in row['technologies'].items() if s.startswith('adv-'))
                        accepted+=1;records+=len(rows)
                counts[count]={'accepted_games':accepted,'rejected_games':rejected,'records':records,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}
            db.execute('CREATE INDEX selection ON observations(player_count,faction,elo)')
            db.execute('INSERT INTO metadata VALUES (?,?)',('catalog',json.dumps({k:sorted(v) for k,v in catalog.items()})))
            db.execute('INSERT INTO metadata VALUES (?,?)',('imports',json.dumps(counts)))
        os.replace(temp,destination)
    finally:
        if Path(temp).exists():Path(temp).unlink()
    return counts


def connect(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)


def catalog(path):
    with connect(path) as db:return json.loads(db.execute("SELECT value FROM metadata WHERE key='catalog'").fetchone()[0])


def iter_rows(path,filters):
    clauses=[];params=[]
    for key in ('player_count','faction','layout','auction','faction_variant'):
        if filters.get(key):clauses.append(key+' = ?');params.append(filters[key])
    if filters.get('min_elo'):
        value=number(filters['min_elo'])
        if value is None:raise ValueError('Pregame Elo minimum must be finite')
        clauses.append('elo >= ?');params.append(value)
    sql='SELECT payload FROM observations'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY game_id,faction'
    from contextlib import closing
    with closing(connect(path)) as db:
        for record in db.execute(sql,params):
            yield json.loads(record[0])


SCOPE = 'Historical base CSV cohort; dropped games excluded; unknown variant values remain unknown'


def batches(path, filters, size=1024):
    if not 1 <= size <= 1900:raise ValueError('Batch size must fit exact raw-value summaries')
    batch=[]
    for row in iter_rows(path, filters):
        if len(batch)>=size and row['game_id']!=batch[-1]['game_id']:
            yield batch
            batch=[]
        batch.append(row)
    if batch:yield batch


def dataset(path,filters):
    return {'schema_version':1,'rows':list(iter_rows(path,filters)),'scope':SCOPE}


def response(path, route, filters):
    from . import streaming_cohort
    if route=='/cohort/api/stats':
        result=streaming_cohort.statistics(batches(path,filters),filters,SCOPE)
        return json.dumps(result,allow_nan=False).encode(),'application/json'
    if route=='/cohort/api/export':
        return streaming_cohort.csv_export(batches(path,filters),filters),'text/csv; charset=utf-8'
    raise FileNotFoundError(route)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--csv',action='append',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(build({int(x.split('=',1)[0]):x.split('=',1)[1] for x in args.csv},args.output),indent=2))
