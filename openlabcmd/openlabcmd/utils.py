from collections import OrderedDict

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
        ("updated_at", "Updated_At"),
        ("created_at", "Created_At")
    ]),
    'service': OrderedDict([
        ("name", "Name"),
        ("node_name", "Node_Name"),
        ("node_role", "Node_Role"),
        ("alarmed", "Alarmed"),
        ("alarmed_at", "Alarmed_At"),
        ("updated_at", "Updated_At"),
        ("restarted", "Restarted"),
        ("restarted_at", "Restarted_At"),
        ("is_necessary", "Is_Necessary"),
        ("status", "Status"),
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
                if isinstance(obj[k], list):
                    values.append(','.join(obj[k]))
                else:
                    values.append(obj[k])
            t.add_row(values)
    return t
