from collections import OrderedDict
import json

from prettytable import PrettyTable

NOCOLOR = False


def _color(s, color='b'):
    global NOCOLOR
    if NOCOLOR:
        return s

    if color == 'b':
        return "\033[1;30m" + s + "\033[0m"
    elif color == 'r':
        return "\033[1;31m" + s + "\033[0m"
    elif color == 'g':
        return "\033[1;32m" + s + "\033[0m"


_headers_table_mapping = {
    'node': OrderedDict([
        ("name", "Name"),
        ("type", "Type"),
        ("role", "Role"),
        ("ip", "IP"),
        ("heartbeat", "HeartBeat"),
        ("alarmed", "Alarmed"),
        ("status", "Status"),
        ("switch_status", "Switch_Status"),
        ("updated_at", "Updated_At"),
        ("created_at", "Created_At")
    ]),
    'service': OrderedDict([
        ("name", "Name"),
        ("node_name", "Node_Name"),
        ("alarmed", "Alarmed"),
        ("alarmed_at", "Alarmed_At"),
        ("restarted", "Restarted"),
        ("restarted_at", "Restarted_At"),
        ("is_necessary", "Is_Necessary"),
        ("status", "Status"),
        ("updated_at", "Updated_At")
    ]),
    'repo': OrderedDict([
        ("repo", "Repo")
    ])
}


def format_output(headers_table_name, objs):
    headers_table = _headers_table_mapping[headers_table_name]
    headers = headers_table.values()
    t = PrettyTable(headers)
    t.align = 'l'
    if objs:
        if not isinstance(objs, list):
            objs = [objs]
        for obj in objs:
            values = []
            for k in headers_table:
                val = obj.get(k) if isinstance(obj, dict) else getattr(obj, k)
                if isinstance(val, list):
                    values.append(','.join(val))
                else:
                    values.append(val)
            t.add_row(values)
    return t


def format_dict(d, max_column_width=80):
    pt = PrettyTable(['Option', 'Value'], caching=False)
    pt.align = 'l'
    pt.max_width = max_column_width
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v)
        pt.add_row([k, v])
    return pt.get_string(sortby='Option')
