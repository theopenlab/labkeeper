#!/usr/bin/python3

import os
import socket
import subprocess
import datetime
import time
import iso8601
import six
import requests
import json
import configparser
from openlabcmd import zk
import logging

logging.basicConfig(filename="/etc/openlab/ha_healthchecker/ha_healthchecker.log",
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)
LOG = logging.getLogger("switch.py")

# ZK client config file
ZK_CLI_CONF = "{{ zk_cli_conf }}"

# Simpledns provider
base_api_url = 'https://api.dnsimple.com/v2/'
DOMAIN_NAME = 'openlabtesting.org'
{% if use_test_url %}
DOMAIN_NAME1 = 'test-status.openlabtesting.org'
DOMAIN_NAME2 = 'test-logs.openlabtesting.org'
DOMAIN_NAME_BK = 'test-logs-bak.openlabtesting.org'
{% else %}
DOMAIN_NAME1 = 'status.openlabtesting.org'
DOMAIN_NAME2 = 'logs.openlabtesting.org'
DOMAIN_NAME_BK = 'logs-bak.openlabtesting.org'
{% endif %}
TOKEN = "{{ dns_access_token }}"
ACCOUNT_ID = {{ dns_account_id }}
TARGET_ORI_IP = "{{ ori_master_ip }}"
TARGET_ORI_BK_IP = "{{ ori_backup_ip }}"
TARGET_CHANGE_IP = "{{ slave_ip }}"
TARGET_CHANGE_BK_IP = "{{ slave_backup_ip }}"

# General constants
SYSTEMCTL_STATUS = 'status'
SYSTEMCTL_RESTART = 'restart'
SYSTEMCTL_STOP = 'stop'
SYSTEMCTL_START = 'start'
SYSTEMCTL_ENABLE = 'enable'
SYSTEMCTL_DISABLE = 'disable'

SYSTEMCTL_ACTIONS = (SYSTEMCTL_STATUS, SYSTEMCTL_RESTART, SYSTEMCTL_STOP,
                     SYSTEMCTL_START, SYSTEMCTL_ENABLE, SYSTEMCTL_DISABLE)

GLOBAL_NODE = None
GLOBAL_ZK = None

# rsyncd and gearman pid
GEARMAN_PID_PATH = '/run/gearman/server.pid'
RSYNCD_PID_PATH = '/var/run/rsyncd.pid'


def get_local_hostname():
    #(TODO) remove after labkeeper vm instance name is the same with the
    # openlabcmd node name format, like {cloud}-openlab-{role}.
    return socket.gethostname()


def check_service_pid_exist(service):
    if service == 'rsync' and os.path.exists(RSYNCD_PID_PATH):
        return 'up'
    elif service == 'gearman' and os.path.exists(GEARMAN_PID_PATH):
        return 'up'
    return 'down'


def service_check(command, service, node_role, node_type):
    if (node_role == 'slave' and service == 'rsync') or service == 'gearman':
        return check_service_pid_exist(service)
    if node_role == 'master' and service == 'rsync':
        service = 'cron'
    # Timer service doesn't support health check.
    if service in ['zuul-timer-tasks', 'nodepool-timer-tasks']:
        return 'up'

    #(TODO) remove after fix in openlabcmd
    # currently, mysql only run on zuul node.
    # nodepool node runs nodepool services and zookeeper
    if node_type == 'nodepool' and service == 'mysql':
        return 'up'

    if service == 'apache':
        service = service + '2'
    return run_systemctl_command(command, service)

def service_action(command, service):
    if service == 'apache':
        service = service + '2'
    return run_systemctl_command(command, service)


def run_systemctl_command(command, service):
    cmd = "systemctl {cmd} {srvc}".format(cmd=command, srvc=service)
    try:
        # 0 means OK
        # if using status command, 0 means active, non-zero means error status.
        subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
        LOG.debug("Run CMD: %(cmd)s", {'cmd': cmd})
        if command == SYSTEMCTL_STATUS:
            return 'up'
    except subprocess.CalledProcessError as e:
        LOG.error("Failed to %(cmd)s %(srvc)s service: "
                  "%(err)s %(out)s", {'cmd': command, 'srvc': service,
                                      'err': e, 'out': e.output})
        if command == SYSTEMCTL_STATUS:
            return 'down'


def parse_isotime(timestr):
    try:
        return iso8601.parse_date(timestr)
    except iso8601.ParseError as e:
        raise ValueError(six.text_type(e))
    except TypeError as e:
        raise ValueError(six.text_type(e))


def is_alarmed_timeout(svc_obj):
    over_time = parse_isotime(
        svc_obj.alarmed_at) + datetime.timedelta(
        days=2)
    current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
    return current_time > over_time


def get_zk_cli():
    global GLOBAL_ZK
    if not GLOBAL_ZK:
        cfg = configparser.ConfigParser()
        cfg.read(ZK_CLI_CONF)
        zk_cli = zk.ZooKeeper(cfg)
        zk_cli.connect()
        GLOBAL_ZK = zk_cli
    return GLOBAL_ZK


def get_local_node():
    global GLOBAL_NODE
    if not GLOBAL_NODE:
        zk_cli = get_zk_cli()
        node_name = get_local_hostname()
        GLOBAL_NODE = zk_cli.get_node(node_name)
    return GLOBAL_NODE


def switch():
    local_node = get_local_node()
    script_load_pre_check(local_node)
    if local_node.status in ['maintaining', 'down']:
        LOG.debug('Node %(name)s status is %(status)s, Skipping refresh.',
                  {'name': local_node.name,
                   'status': local_node.status.upper()})
        return
    local_node_service_process(local_node)

    # At the end of the script, we'd better to close zk session.
    zk_cli = get_zk_cli()
    zk_cli.disconnect()


def local_node_service_process(node_obj):
    zk_cli = get_zk_cli()
    service_objs = zk_cli.list_services(
        node_name_filter=str(node_obj.name),
        node_role_filter=str(node_obj.role))
    for service_obj in service_objs:
        treat_single_service(service_obj, node_obj)


def treat_single_service(service_obj, node_obj):
    if service_obj.status == 'down':
        if service_obj.restarted:
            if service_obj.is_necessary:
                # Report an issue towards deployment as a necessary
                # service down
                # Master/Slave Switch
                switch_process(node_obj)
            else:
                # Have report the issue yet?
                # Yes
                if service_obj.alarmed:

                    # --- the issue is timeout ?
                    # -- Yes
                    if is_alarmed_timeout(service_obj):

                        # $$ this node is master ?
                        # $$ Yes
                        # Report an issue towards deployment as a unnecessary
                        # service issue timeout.
                        # Master/Slave Switch
                        if node_obj.role == 'master':
                            switch_process(node_obj)


def shut_down_all_services(node_obj):
    zk_cli = get_zk_cli()
    service_objs = zk_cli.list_services(
        node_name_filter=str(node_obj.name),
        node_role_filter=str(node_obj.role))
    for service in service_objs:
        if service.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                'nodepool-timer-tasks']:
            service_action(SYSTEMCTL_STOP, service.name)


def setup_necessary_services_and_check(node_obj):
    zk_cli = get_zk_cli()
    service_objs = zk_cli.list_services(
        node_name_filter=str(node_obj.name),
        node_role_filter=str(node_obj.role))
    for service in service_objs:
        if service.is_necessary:
            if service.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                    'nodepool-timer-tasks']:
                service_action(SYSTEMCTL_START, service)
                LOG.info("Start Service %(name)s.", {'name': service.name})

    # local deplay 5 seconds
    time.sleep(5)

    # Then we check all services status in 'SLAVE' env.
    result = {}
    for service in service_objs:
        result[service.name] = service_check(
            SYSTEMCTL_STATUS, service.name, node_obj.role, node_obj.type)
        LOG.info("Started Service %(name)s status checking: %(status)s",
                 {'name': service.name,
                  'status': result[service.name].upper()})

    for svc_name, res in result.items():
        if res != 0:
            LOG.error("%s is failed to start with return code %s" % (
                svc_name, res))

def check_opp_master_is_good():
    oppo_nodes = get_the_oppo_nodes()
    all_result = 0
    for node in oppo_nodes:
        if node.status == 'down':
            all_result += 1
    if all_result > 0 or (all_result == 0 and len(oppo_nodes) < 2):
        return False
    return True


def check_and_process_orphan_master():
    zk_cli = get_zk_cli()
    orphans = []
    for zk_node in zk_cli.list_nodes():
        if (zk_node.role == 'master' and
              zk_node.status == 'down'):
            orphans.append(zk_node)

    for orphan in orphans:
        zk_cli = get_zk_cli()
        zk_cli.update_node(orphan.name, role='slave')
        LOG.info("M/S switching: orphan node, %(role)s node %(name)s is "
                 "finishd from master to slave. And update it with "
                 "role=slave.",
                 {'role': orphan.role, 'name': orphan.name})


def script_load_pre_check(node_obj):
    if (node_obj.status == 'up' and node_obj.role == 'slave' and
            not check_opp_master_is_good()):
        # setup local services and check services status
        # at the end of process, we will set this node status to up and
        # role to MASTER
        setup_necessary_services_and_check(node_obj)
        change_dns()
        zk_cli = get_zk_cli()
        zk_cli.update_node(node_obj.name, role='master', status='up')
        LOG.info("M/S switching: local node, %(role)s node %(name)s is "
                 "finishd from slave to master. And update it with "
                 "role=master and status=up.",
                 {'role': node_obj.role, 'name': node_obj.name})

    elif node_obj.status == 'down' and node_obj.role == 'master':
        # This is the first step when other master nodes, when check
        # self status is down, that means there must be 1 master node is
        # failed and hit the M/S switch. So what we gonna do is shuting down
        # local services and set self role from master to slave.
        shut_down_all_services(node_obj)
        zk_cli = get_zk_cli()
        zk_cli.update_node(node_obj.name, role='slave')
        LOG.info("M/S switching: local node, %(role)s node %(name)s is "
                 "finishd from master to slave. And update it with "
                 "role=slave.",
                 {'role': node_obj.role, 'name': node_obj.name})
    # This is for make sure that, once a master node is down(
    # can not ping or keepalived down)
    # A origin master node will still hang on master down status.
    # So this will fit it if any alived keepalived can process it.
    # If not, openlabcmd will hit the duplicated master issue during update
    # service.
    else:
        check_and_process_orphan_master()


def switch_process(node_obj):
    if node_obj.role == 'master':
        # Now, we must hit the services error, not host poweroff,
        # as the kp is alived, so we need to shut down all the necessary
        # and unecessary services.
        zk_cli = get_zk_cli()
        shut_down_all_services(node_obj)
        same_nodes = get_the_same_nodes()
        zk_cli.update_node(node_obj.name, role='slave', status='down')
        LOG.info("M/S switching: local node, %(role)s node %(name)s is "
                 "finishd from master to slave. And update it with "
                 "role=slave and status=down.",
                 {'role': node_obj.role, 'name': node_obj.name})
        for node in same_nodes:
            zk_cli.update_node(node.name, status='down')
            LOG.info("M/S switching: remote same node,"
                     "%(role)s node %(name)s begins from master to slave. "
                     "And update it with status=down.",
                     {'role': node.role, 'name': node.name})


def get_the_same_nodes():
    zk_cli = get_zk_cli()
    same_nodes = []
    local_node_obj = get_local_node()
    for zk_node in zk_cli.list_nodes():
        if (zk_node.role != local_node_obj.role or
                zk_node.name == local_node_obj.name):
            continue
        elif zk_node.role in ['master', 'slave']:
            same_nodes.append(zk_node)

    return same_nodes


def get_the_oppo_nodes():
    zk_cli = get_zk_cli()
    oppo_nodes = []
    local_node_obj = get_local_node()
    for zk_node in zk_cli.list_nodes():
        if zk_node.role == local_node_obj.role:
            continue
        elif (zk_node.role in ['master', 'slave'] and
              zk_node.status != 'down'):
            oppo_nodes.append(zk_node)

    return oppo_nodes


def match_record(name, res):
    if res['name'] in ['logs-bak', 'test-logs-bak']:
        return (name == res['name'] and res['type'] == "A" and
                TARGET_ORI_BK_IP == res['content'])
    return (name == res['name'] and
            res['type'] == "A" and TARGET_ORI_IP == res['content'])


def change_dns():
    headers = {'Authorization': "Bearer %s" % TOKEN,
               'Accept': 'application/json'}
    res = requests.get(base_api_url + 'accounts', headers=headers)
    if res.status_code != 200:
        LOG.error("Failed to get the accounts")
        LOG.error("Details: code-status %s\n         message: %s" % (
            res.status_code, res.reason))
        return
    accounts = json.loads(s=res.content.decode('utf8'))['data']
    account_id = None
    for account in accounts:
        if account['id'] == ACCOUNT_ID:
            account_id = account['id']
            break
    if not account_id:
        LOG.error("Failed to get the account_id")
        return

    target_dict = {DOMAIN_NAME1: {}, DOMAIN_NAME2: {}, DOMAIN_NAME_BK: {}}
    for target_domain in target_dict.keys():
        res = requests.get(base_api_url + "%s/zones/%s/records?name=%s" % (
            account_id, DOMAIN_NAME, target_domain.split(DOMAIN_NAME)[0][:-1]),
                           headers=headers)
        if res.status_code != 200:
            LOG.error("Failed to get the records by name %s" % target_domain)
            LOG.error("Details: code-status %s\n         message: %s" % (
                res.status_code, res.reason))
            return
        records = json.loads(s=res.content.decode('utf8'))['data']
        record_id = None
        for record in records:
            if match_record(target_domain.split(DOMAIN_NAME)[0][:-1], record):
                record_id = record['id']
                target_dict[target_domain]['id'] = record_id
                break
        if not record_id:
            LOG.error("Failed to get the record_id by name %s" % target_domain)
            return

    if not any(target_dict.values()):
        LOG.error("Can't not get any records.")
        return

    headers['Content-Type'] = 'application/json'
    data = {
        "content": TARGET_CHANGE_IP
    }
    for target_domain in target_dict.keys():
        res = requests.patch(base_api_url + "%s/zones/%s/records/%s" % (
            account_id, DOMAIN_NAME, target_dict[target_domain]['id']),
                             data=data,
                             headers=headers)
        result = json.loads(s=res.content.decode('utf8'))['data']
        if result['name'] not in ['logs-bak', 'test-logs-bak']:
            if (res.status_code == 200 and
                    result['content'] == TARGET_CHANGE_IP):
                LOG.info("Success Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_IP, TARGET_CHANGE_IP))
            else:
                LOG.error("Fail Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_IP, TARGET_CHANGE_IP))
                LOG.error("Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
                return
        else:
            if (res.status_code == 200 and
                    result['content'] == TARGET_CHANGE_BK_IP):
                LOG.info("Success Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_BK_IP, TARGET_CHANGE_BK_IP))
            else:
                LOG.error("Fail Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_BK_IP, TARGET_CHANGE_BK_IP))
                LOG.error("Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
                return
    LOG.info("Finish update DNS entry.")

if __name__ == '__main__':
    switch()
