import sys
import datetime

import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output
import requests


def get_stats(cycle, limit):
    url = f"http://127.0.0.1/api/statistics/?cycle={cycle}&limit={limit}"
    return requests.post(url).json()


def get_field(stats, table, field):
    return [e[field] for e in stats['statistics'][table]]


def filter_errors(stats):
    earliest_ts = datetime.datetime.fromisoformat(stats['statistics']['charge'][-1]['timestamp'])
    stats['statistics']['error'] = [
        err for err in stats['statistics']['error']
        if earliest_ts < datetime.datetime.fromisoformat(err['timestamp'])
        ]


def get(cycle, limit):
    stats = get_stats(cycle, limit)
    filter_errors(stats)
    figure = {'layout': {'title': 'Hier sollte irgendein Lückenfüller stehen.'}}
    data = [
        {'x': get_field(stats, 'voltage', 'timestamp'), 'y': get_field(stats, 'voltage', 'voltage'), 'type': 'line', 'name': 'Volt'},
        {'x': get_field(stats, 'current', 'timestamp'), 'y': get_field(stats, 'current', 'current'), 'type': 'line', 'name': 'Ampere'},
        {'x': get_field(stats, 'charge', 'timestamp'), 'y': get_field(stats, 'charge', 'charge'), 'type': 'line', 'name': 'Ladung in Ah'},
        {'x': get_field(stats, 'error', 'timestamp'), 'y': get_field(stats, 'error', 'error'), 'type': 'line', 'name': 'Fehlercode Dezimal'},
    ]
    figure.update({'data': data})
    return figure


# hardcoded -- need to fix
external_stylesheets = ['/vendor/codepen/bWLwgP.css']
app = dash.Dash(__name__, external_stylesheets=external_stylesheets, url_base_pathname='/statistiken/')
app.scripts.config.serve_locally = False
app.css.config.serve_locally = False
app.layout = html.Div(children=[
    html.H1(children='LiFePo4-Akku'),

    html.Div(children='''
        Statistiken über den Akku
    '''),

    dcc.Graph(
        id='graph',
        figure=get(5, 100)
    ),
    dcc.Input(id='cycle', value=5, type='number'),
    dcc.Input(id='limit', value=100, type='number'),
])

@app.callback(
    Output(component_id='graph', component_property='figure'),
    [
        Input(component_id='cycle', component_property='value'),
        Input(component_id='limit', component_property='value'),
    ]
)
def update_output_div(cycle, limit):
    return get(cycle, limit)


if __name__ == '__main__':
    app.run_server(debug=False, host='127.0.0.1')
