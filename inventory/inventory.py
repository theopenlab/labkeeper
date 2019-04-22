#!/usr/bin/env python

"""
Environment variable for this inventory script:
OL_TYPE:        required, the openlab deployment type, one of: allinone, allinone-ha, openlab, openlab-ha
OL_{host}_IP:   new ip address specified for the {host}, such as: OL_ZUUL01_IP, OL_NODEPOOL01_IP,
                the {host} must be one of the host name defined in the yaml inventory files.
OL_SWITCH_MASTER_SLAVE: whether switch the master/slave IP address

"""
import os
import sys

import argparse
import json
import subprocess


def parse_inventory():
    inventory_file = 'inventory/%s.yaml' % os.environ.get('OL_TYPE')
    parsed_inventories = subprocess.Popen(
        ['ansible-inventory', '-i', inventory_file, '--list'],
        stdout=subprocess.PIPE).stdout.read()
    updated_inventories = json.loads(parsed_inventories)
    inventory_hosts = updated_inventories['_meta']['hostvars']
    host_names = inventory_hosts.keys()
    host_names.remove('bastion')
    ips_update = dict([(h, os.environ.get("OL_%s_IP" % h.upper())) for h in host_names])

    old_ips = dict([(h, inventory_hosts[h]['ansible_host']) for h in host_names])

    switch_role = os.environ.get('OL_SWITCH_MASTER_SLAVE')

    if switch_role:
        for host in host_names:
            if host.endswith('01') and host[:-2] in ['zuul', 'nodepool']:
                inventory_hosts[host]['ansible_host'] = old_ips[host[:-2] + '02']
            if host.endswith('02') and host[:-2] in ['zuul', 'nodepool']:
                inventory_hosts[host]['ansible_host'] = old_ips[host[:-2] + '01']
    for host in host_names:
        if ips_update[host]:
            inventory_hosts[host]['ansible_host'] = ips_update[host]
    new_ips = dict([(h, inventory_hosts[h]['ansible_host']) for h in host_names])
    return updated_inventories, old_ips, new_ips


def main():
    parser = argparse.ArgumentParser()
    args_group = parser.add_mutually_exclusive_group(required=True)
    args_group.add_argument('--list', action='store_true',
                            help='List inventories')
    args_group.add_argument('--old-host-ips', action='store_true',
                            help='List old host ips')
    args_group.add_argument('--new-host-ips', action='store_true',
                            help='List new host ips')
    parsed_args = parser.parse_args()
    if not os.environ.get('OL_TYPE'):
        raise Exception('ERROR: You must specify a deploy type with "OL_TYPE" '
                        'environment variable!')
    updated_inventories, old_ips, new_ips = parse_inventory()
    if parsed_args.list:
        print(json.dumps(updated_inventories, indent=4))
    elif parsed_args.old_host_ips:
        print(json.dumps(old_ips, indent=4))
    elif parsed_args.new_host_ips:
        print(json.dumps(new_ips, indent=4))


if __name__ == '__main__':
    sys.exit(main())
