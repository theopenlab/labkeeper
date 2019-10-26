#!/usr/bin/env python
import datetime
import json
import os
import subprocess
import sys

import argparse
from prettytable import PrettyTable
import requests


def add_cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('type',
                        choices=["allinone", "allinone-ha", "openlab",
                                 "openlab-ha"],
                        help='OpenLab deployment type',
                        )
    parser.add_argument('--action',
                        choices=["deploy", "new-slave", "new-zookeeper",
                                 "switch-role", "show-graph", "show-ip",
                                 "list-change", "upgrade", "upgrade-complete"],
                        default="deploy",
                        help="The action that labkeeper supports. Default "
                             "value is 'deploy'.\n"
                             "'deploy': create a new OpenLab CI environment.\n"
                             "'new-slave': create new slave nodes base on "
                             "current master nodes.\n"
                             "'switch-role': switch the master/slave role of "
                             "current deployment. This will re-config the "
                             "existing OpenLab environment.\n"
                             "'show-graph': show the hosts graph of ansible "
                             "inventory. It can be used with --with-vars to "
                             "show more detail.\n"
                             "'show-ip': show hosts ip address.\n"
                             "'list-change': show zuul and nodepool code "
                             "change during last month.\n"
                             "'upgrade': upgrade zuul and nodepool to the "
                             "newest master branch.\n"
                             "'upgrade-complete: after checking upgraded "
                             "environment, if everything works well, run this "
                             "action to complete upgrade. Otherwise all nodes"
                             "will keep being in maintaining status\n '")
    parser.add_argument('-u', '--user',
                        help='the Ansible remote user performing deployment, '
                             'default is "ubuntu" configured in ansible.cfg',
                        )
    parser.add_argument('-e', '--extra-vars',
                        metavar="<key=value>",
                        action='append',
                        default=[],
                        help='extra vars passed to Ansible command',
                        )
    parser.add_argument('--host-ip',
                        metavar="<key=value>",
                        action='append',
                        help='override new ip address for current inventory, '
                             'this argument need to use with key-value pairs '
                             'combined with "=", the key must be the host name'
                             ' defined in the inventory yaml files, e.g. '
                             'zuul01, nodepool02, allinone01.',
                        )
    parser.add_argument('--with-vars',
                        action='store_true',
                        help='show the hosts graph of ansible inventory with '
                             'vars. It must be used together with --action '
                             'show-graph.'
                        )
    return parser


def list_changes(project, days):
    from_day = (datetime.date.today() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    response = requests.get(
        'https://review.opendev.org/changes/?q=project:' +
        project + '+status:merged+after:' + from_day)
    changes = json.loads(
        response.content.decode("utf-8")[5:].replace('\n', ''))
    pt = PrettyTable([project, 'change_id'], caching=False)
    pt.align = 'l'
    for change in changes:
        pt.add_row([change['subject'], change['change_id']])
    print(pt.get_string(sortby=project))


def main():
    parsed_args = add_cli_args().parse_args()
    os.environ['OL_TYPE'] = parsed_args.type
    cmd = []

    if parsed_args.action == 'deploy':
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/site.yaml']
    elif parsed_args.action == 'new-slave':
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/site.yaml', '-l', '*-slave']
    elif parsed_args.action == 'new-zookeeper':
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/conf-new-zookeeper.yaml']
    elif parsed_args.action == 'switch-role':
        os.environ['OL_SWITCH_MASTER_SLAVE'] = True
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/switch_role.yaml']
    elif parsed_args.action == 'show-graph':
        cmd = ['ansible-inventory', '-i', 'inventory/inventory.py', '--graph']
        if parsed_args.with_vars:
            cmd.append('--vars')
    elif parsed_args.action == 'show-ip':
        cmd = ['python', 'inventory/inventory.py', '--show-ip']
    elif parsed_args.action == 'list-change':
        list_changes('zuul/zuul', 31)
        list_changes('zuul/nodepool', 31)
    elif parsed_args.action == 'upgrade':
        if parsed_args.type != 'openlab-ha':
            print("upgrade action only support openlab-ha deployment.")
            exit(1)
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/upgrade-ha-deployment.yaml']
    elif parsed_args.action == 'upgrade-complete':
        if parsed_args.type != 'openlab-ha':
            print("upgrade-complete action only support openlab-ha deployment.")
            exit(1)
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py',
               'playbooks/upgrade-complete-ha-deployment.yaml']

    if parsed_args.host_ip:
        specified_ips = dict([(d.partition('=')[::2])
                              for d in parsed_args.new_ip])
        for host, ip in specified_ips.items():
            os.environ['OL_%s_IP' % host.upper()] = ip

    if parsed_args.user and cmd[0] == 'ansible-playbook':
        cmd += ['-u', parsed_args.user]

    if parsed_args.extra_vars:
        cmd += ['-e', ' '.join(parsed_args.extra_vars)]

    ol_env_msg = '\n'.join(['%s=%s' % (k, os.environ[k]) for k in os.environ
                            if k.startswith('OL_')])
    if cmd:
        print("OpenLab deployment ENV:\n%s" % ol_env_msg)
        print('Ansible command:\n%s' % ' '.join(cmd))
        print("*" * 100)
        subprocess.call(cmd)
        if (parsed_args.action == 'new-slave' or
                parsed_args.action == 'new-zookeeper'):
            print("Don't forget to restart zuul and nodepool by hand.")
    if parsed_args.action == 'new-slave':
        subprocess.call(['ansible-playbook', '-i', 'inventory/inventory.py',
                         'playbooks/conf-cluster.yaml'])


if __name__ == '__main__':
    sys.exit(main())
