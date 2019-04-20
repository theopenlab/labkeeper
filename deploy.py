#!/usr/bin/env python
import os
import subprocess
import sys

import argparse


def add_cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('type',
                        choices=["allinone", "allinone-ha", "openlab",
                                 "openlab-ha"],
                        help='OpenLab deployment type',
                        )
    parser.add_argument('-u', '--user',
                        default='ubuntu',
                        help='the Ansible remote user performing deployment',
                        )
    parser.add_argument('--switch-role',
                        action='store_true',
                        help='switch the master/slave role of current deployment, '
                             'this will re-config a existing OpenLab environment to '
                             'switch the "master/slave" role of hosts',
                        )
    parser.add_argument('--new-slave',
                        action='store_true',
                        help='deploy the slave part of a CI cluster freshly, you need '
                             'to specify the new slave hosts IP addresses with "--new-ip" '
                             'argument, for example: '
                             '--new-ip zuul02=192.168.5.5 --new-ip nodepool02=192.168.6.6',
                        )
    parser.add_argument('-e', '--extra-vars',
                        metavar="<key=value>",
                        action='append',
                        default=[],
                        help='extra vars passed to Ansible command',
                        )
    parser.add_argument('--new-ip',
                        metavar="<key=value>",
                        action='append',
                        help='specify new ip address for current inventory, this argument '
                             'need to use with key-value pairs combined with "=", the key '
                             'must be the host name defined in the inventory yaml files, '
                             'e.g. zuul01, nodepool02, allinone01.',
                        )
    parser.add_argument('--with-vars',
                        action='store_true',
                        help='show the hosts graph of ansible inventory with vars, specify with '
                             'key-value pairs combined with "="',
                        )
    parser.add_argument('--graph',
                        action='store_true',
                        help='show the hosts graph of ansible inventory',
                        )
    parser.add_argument('--show-old-ips',
                        action='store_true',
                        help='show the old hosts ip address',
                        )
    parser.add_argument('--show-new-ips',
                        action='store_true',
                        help='show the new hosts ip address',
                        )
    return parser


def main(argv=sys.argv[1:]):
    parsed_args = add_cli_args().parse_args()
    os.environ['OL_TYPE'] = parsed_args.type
    cmd = ['ansible-playbook', '-i', 'inventory/inventory.py', 'playbooks/site.yaml']

    if parsed_args.user:
        cmd += ['-u', parsed_args.user]

    if parsed_args.new_ip:
        specified_ips = dict([(d.partition('=')[::2]) for d in parsed_args.new_ip])
        for host, ip in specified_ips.items():
            os.environ['OL_%s_IP' % host.upper()] = ip

    if parsed_args.new_slave:
        if not parsed_args.new_ip:
            sys.exit("ERROR: Must specify the new slave hosts IPs with --new-ip")
        os.environ['OL_SWITCH_MASTER_SLAVE'] = True
        cmd += ['-l', '*-slave']
        parsed_args.extra_vars.append('config_new_slave=true')

    if parsed_args.extra_vars:
        cmd += ['-e', ' '.join(parsed_args.extra_vars)]

    if parsed_args.switch_role:
        os.environ['OL_SWITCH_MASTER_SLAVE'] = True
        cmd = ['ansible-playbook', '-i', 'inventory/inventory.py', 'playbooks/conf-new-slave.yaml']

    if parsed_args.graph:
        cmd = ['ansible-inventory', '-i', 'inventory/inventory.py', '--graph']
        if parsed_args.with_vars:
            cmd.append('--vars')

    if parsed_args.with_vars and not parsed_args.graph:
        sys.exit("ERROR: --with-vars must work with --graph")

    if parsed_args.show_new_ips:
        cmd = ['python', 'inventory/inventory.py', '--new-host-ips']

    if parsed_args.show_old_ips:
        cmd = ['python', 'inventory/inventory.py', '--old-host-ips']

    ol_env_msg = '\n'.join(['%s=%s' % (k, os.environ[k]) for k in os.environ if k.startswith('OL_')])
    print ("OpenLab deployment ENV:\n%s" % ol_env_msg)
    print('Ansible command:\n%s' % ' '.join(cmd))
    print("*" * 100)

    subprocess.call(cmd)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
