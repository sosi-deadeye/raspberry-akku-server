import sys


import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
from database import session, Current, Voltage, Charge, Cycle


#def diff_gen(seq):
#    last = seq[0][0]
#    for ts, *rest in seq[1:]:
#        yield (ts - last, ts, *rest)
#        last = ts


#def split_deltas(sequence):
#    diffs = tuple(diff_gen(sequence))
#    last_idx = 0
#    for (idx, (diff, *rest)) in enumerate(diffs):
#        if not 0 < diff.total_seconds() < 60:
#            if last_idx + 1 != idx:
#                yield diffs[last_idx:idx]
#            last_idx = idx


#def get_chunks(sequence):
#    results = []
#    for diff, *data in split_deltas(sequence):
#        results.append(data)
#    return results


#def get_chunks_xy(sequence):
#    results = []
#    for diff, *data in split_deltas(sequence):
#        results.append(tuple(zip(*data))[1:])
#    return results


def get_chunk(idx):
    figure = {'layout': {'title': 'Hier sollte irgendein Lückenfüller stehen.'}}
    voltages = [session.query(Voltage).filter_by(cycle=idx).all()]
    currents = [session.query(Current).filter_by(cycle=idx).all()]
    charges = [session.query(Charge).filter_by(cycle=idx).all()]
    try:
        data = [
            {'x': [v.timestamp for v in voltages], 'y': [v.voltage for v in voltages], 'type': 'line', 'name': 'Volt'},
            {'x': [c.timestanp for c in currents], 'y': [c.current for c in currents], 'type': 'line', 'name': 'Ampere'},
            {'x': [l.timestamp for l in charges], 'y': [l.charge for l in charges], 'type': 'line', 'name': 'Ladung in Ah'},
        ]
    except Exception as e:
        print(e)
        data = []
    figure.update({'data': data})
    return figure


cycles = session.query(Cycle.cycle).count()
#external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash(__name__)#, external_stylesheets=external_stylesheets)
app.layout = html.Div(children=[
    html.H1(children='LiFePo4-Akku'),

    html.Div(children='''
        Statistiken über den Akku
    '''),

    dcc.Graph(
        id='graph',
        figure=get_chunk(0)
    ),
    dcc.Slider(
        id='cycle',
        min=0,
        max=cycles,
        value=0,
        marks={str(cycle): str(cycle) for cycle in range(cycles)},
        step=1
    )
])


@app.callback(
    Output('graph', 'figure'),
    [Input('cycle', 'value')])
def update_figure(cycle):
    return {
        'data': get_chunk(cycle)['data'],
    }



if __name__ == '__main__':
    app.run_server(debug=True, host='0.0.0.0')
