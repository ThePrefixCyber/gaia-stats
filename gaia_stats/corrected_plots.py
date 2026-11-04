"""Observation-weighted historical plots, retaining the original chart families."""
import math
from collections import defaultdict
from statistics import mean

from .eligibility import eligible_frame
from .score_basis import csv_score, csv_sources
from .technology_locations import location, sources as grouped_sources

CORRECTED = {'basic-tech-frequency','basic-tech-score','advanced-tech-frequency',
             'advanced-tech-score','round-scoring','final-scoring','round-one-structures','point-sources'}


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def observations(data, players, min_elo=None):
    """One row per eligible player-game; all players must be explicitly not dropped."""
    data = eligible_frame(data)
    mask = data[[f'pos_{p}_dropped' for p in range(1,players+1)]].eq(False).all(axis=1)
    clean = data.loc[mask]
    result=[]
    for index, game in enumerate(clean.to_dict(orient="records")):
        scores=[csv_score(game,p) for p in range(1,players+1)]
        if not all(finite(s) for s in scores):
            continue
        best=max(scores); ties=scores.count(best)
        for p,score in enumerate(scores,1):
            prefix=f'pos_{p}_'; elo=game.get(prefix+'elo')
            source_values, source_rank = csv_sources(game, p)
            values = dict(game)
            for key in game:
                if key.startswith(prefix+'score_'):
                    values[key] = source_values.get(key.removeprefix(prefix+'score_'))
            if min_elo is not None and (not finite(elo) or elo<min_elo):continue
            result.append({'game':game.get('id',index),'faction':game[prefix+'faction'],
                           'score':score,'rank':1+sum(s>score for s in scores),
                           'win_share':1/ties if score==best else 0,'elo':elo,
                           'values':values,'prefix':prefix})
    return result


def average(rows, getter):
    values=[getter(r) for r in rows]
    values=[v for v in values if finite(v)]
    return (mean(values) if values else None),len(values)


def mean_score(rows):return average(rows,lambda r:r['score'])


def pair_mean(rows, first, second):
    group=[r for r in rows if {r['values']['final_scoring_1'],r['values']['final_scoring_2']}=={first,second}]
    def total(r):
        a=r['values'].get(r['prefix']+'score_final1'); b=r['values'].get(r['prefix']+'score_final2')
        return a+b if finite(a) and finite(b) else None
    return average(group,total),group


def make_corrected(kind,data,players,faction,min_elo=None,prepared_rows=None):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    rows=observations(data,players,min_elo) if prepared_rows is None else prepared_rows
    selected=[r for r in rows if r['faction']==faction]
    metric = 'tile scoring VP / shared pre-bid-score wins' if kind in ('round-scoring','final-scoring') else 'pre-bid VP'
    title=f'{kind}: {faction} · observation-weighted · {metric} · n={len(selected)}'
    if min_elo is not None:title+=f' · pregame Elo ≥ {min_elo:g}'
    if not selected:
        fig=go.Figure();fig.add_annotation(text='No eligible observations',showarrow=False)
        fig.update_layout(title=title);return fig
    plot_meta = {}
    if kind == 'round-one-structures':
        from .chart_groups import opening_configuration
        groups = defaultdict(list)
        classes = defaultdict(list)
        for row in selected:
            counts = {key: row['values'].get(row['prefix']+'buildings_r_1_'+key) for key in ('m','ts','lab','PI','ac1','ac2')}
            configuration = opening_configuration(counts)
            if configuration is not None:
                category, label, _ = configuration
                groups[(category, label)].append(row)
                classes[category].append(row)
        observed = [row for group in groups.values() for row in group]
        plot_meta = {'structure_observations':len(observed),
                     'unavailable_structure_observations':len(selected)-len(observed)}
        if not observed:
            fig=go.Figure();fig.add_annotation(text='No observed round-one structures',showarrow=False)
        else:
            # Preserve the original faction -> strategy class -> exact opening
            # hierarchy. Calculate every parent from its player observations,
            # never by averaging child means or counting parent copies twice.
            nodes=[(faction,faction,'',observed)]
            for category, group in sorted(classes.items()):
                nodes.append((f'{faction}/{category}',category,faction,group))
            for (category,label), group in sorted(groups.items()):
                nodes.append((f'{faction}/{category}/{label}',label,f'{faction}/{category}',group))
            values=[mean_score(group)[0] for _,_,_,group in nodes]
            from .score_colors import marker
            fig = go.Figure(go.Treemap(ids=[node[0] for node in nodes], labels=[node[1] for node in nodes],
                parents=[node[2] for node in nodes], values=[len(node[3]) for node in nodes], branchvalues='total',
                marker=marker(values), customdata=values,
                hovertemplate='%{label}<br>Player-games=%{value}<br>Mean pre-bid VP=%{customdata}<extra></extra>'))
    elif kind == 'point-sources':
        fig = go.Figure()
        for rank in range(1, players+1):
            xs, ys = [], []
            for row in selected:
                if row['rank'] != rank or row['score'] <= 0:
                    continue
                prefix = row['prefix']+'score_'
                sources = {key.removeprefix(prefix):value for key,value in row['values'].items() if key.startswith(prefix)}
                research = row['values'].get(row['prefix']+'tech_score')
                sources['research'] = research
                for category, keys in [('round',[f'round{i}' for i in range(1,7)]),('final',['final1','final2'])]:
                    values = [sources.pop(key,None) for key in keys]
                    sources[category] = sum(values) if all(finite(value) for value in values) else None
                for source,value in sorted(grouped_sources(sources).items()):
                    if source != 'bid' and finite(value):
                        xs.append(source);ys.append(100*value/row['score'])
            fig.add_trace(go.Box(x=xs,y=ys,name=f'pre-bid-score rank {rank}',boxpoints=False))
        fig.update_layout(boxmode='group',yaxis_title='Signed share of pre-bid score (%)')
    elif 'tech-' in kind:
        advanced=kind.startswith('advanced')
        prefix='adv_tech_taken_' if advanced else 'tech_taken_'
        columns=[c for c in data.columns if c.startswith('pos_1_'+prefix)]
        techs=[c.removeprefix('pos_1_'+prefix) for c in columns]
        slots=[c for c in data.columns if c.startswith('tech_adv-')] if advanced else [c for c in data.columns if c.startswith('tech_') and not c.startswith('tech_adv-')]
        def available(r,t):return any(r['values'].get(s)==t for s in slots)
        def taken(r,t):return r['values'].get(r['prefix']+prefix+t)==True
        fig=go.Figure()
        if kind.endswith('frequency'):
            for rank in range(1,players+1):
                ys=[];counts=[]
                for tech in techs:
                    avail=[r for r in selected if available(r,tech)]
                    numerator=sum(taken(r,tech) and r['rank']==rank for r in avail)
                    # One faction observation per game; denominator is games where available.
                    denominator=len({r['game'] for r in avail})
                    ys.append(100*numerator/denominator if denominator else None)
                    counts.append([numerator,denominator])
                fig.add_trace(go.Bar(x=techs,y=ys,name=f'pre-bid-score rank {rank}',customdata=counts,
                    hovertemplate='%{x}<br>%{y:.2f}%<br>taken=%{customdata[0]}, available games=%{customdata[1]}<extra></extra>'))
            fig.update_layout(barmode='stack',yaxis_title='Acquired / games where available (%)')
        else:
            slot_groups = defaultdict(list)
            for slot in slots:
                slot_groups['tech_' + location(slot.removeprefix('tech_'))].append(slot)
            for slot in [*slot_groups,'not_taken','taken']:
                xs=[];counts=[]
                for tech in techs:
                    group=[r for r in selected if available(r,tech) and
                           ((not taken(r,tech)) if slot=='not_taken' else taken(r,tech)) and
                           (slot in ('taken','not_taken') or any(r['values'].get(source)==tech
                            for source in slot_groups[slot]))]
                    value,n=mean_score(group);xs.append(value);counts.append(n)
                fig.add_trace(go.Scatter(x=xs,y=techs,mode='markers',name=slot,text=counts,
                    hovertemplate='%{y}<br>Mean pre-bid VP=%{x}<br>n=%{text}<extra></extra>'))
            overall,n=mean_score(selected)
            if overall is not None:fig.add_vline(x=overall,line_dash='dot',annotation_text=f'Overall mean {overall:.2f} (n={n})')
            fig.update_layout(xaxis_title='Mean pre-bid VP; descriptive association')
    else:
        final=kind=='final-scoring'
        xs=sorted({r['values'][f'final_scoring_{i}'] for r in rows for i in (1,2)}) if final else list(range(1,7))
        ys=xs if final else sorted({r['values'][f'round_{i}_scoring'] for r in rows for i in range(1,7)})
        z=[];wins=[];counts=[]
        for y in ys:
            zs=[];ws=[];ns=[]
            for x in xs:
                if final:
                    (value,n),group=pair_mean(selected,x,y) if x!=y else ((None,0),[])
                else:
                    group=[r for r in selected if r['values'][f'round_{x}_scoring']==y]
                    value,n=average(group,lambda r:r['values'].get(r['prefix']+f'score_round{x}'))
                zs.append(value);ns.append(n);ws.append(100*mean(r['win_share'] for r in group) if group else None)
            z.append(zs);wins.append(ws);counts.append(ns)
        fig=make_subplots(rows=1,cols=2,subplot_titles=('Observed scoring VP','Shared wins (%)'))
        for col,values in enumerate((z,wins),1):
            fig.add_trace(go.Heatmap(x=xs,y=ys,z=values,customdata=counts,hoverongaps=False,
                hovertemplate='%{x} / %{y}<br>%{z}<br>score observations n=%{customdata}<extra></extra>',
                colorbar={'x':.45 if col==1 else 1.02},colorscale='Greens'),row=1,col=col)
    fig.update_layout(title=title,meta={'methodology':'corrected-prebid-v2','observations':len(selected),
                                      'games':len({r['game'] for r in selected}),'min_elo':min_elo,**plot_meta})
    return fig
