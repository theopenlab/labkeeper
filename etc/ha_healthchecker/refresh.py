#!/usr/bin/python3

import os
import socket
import subprocess
import datetime
import iso8601
import six
import configparser
from openlabcmd import zk
import logging

logging.basicConfig(filename="/etc/openlab/ha_healthchecker/ha_healthchecker.log",
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)
LOG = logging.getLogger("refresh.py")

# ZK client config file
ZK_CLI_CONF = "{{ zk_cli_conf }}"

# Heartbeat Internal timeout(seconds)
HEARTBEAT_INTERNAL_TIMEOUT = {{heartbeat_internal}}

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
    # (TODO) remove after labkeeper vm instance name is the same with the
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

    # (TODO) remove after fix in openlabcmd
    # currently, mysql only run on zuul node.
    # nodepool node runs nodepool services and zookeeper
    if node_type == 'nodepool' and service == 'mysql':
        return 'up'

    if service == 'apache':
        service = service + '2'
    return run_systemctl_command(command, service)


def service_restart(command, service):
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


def ping(ipaddr):
    cli = ['ping', '-c1', '-w1']
    cli.append(ipaddr)
    proc = subprocess.Popen(cli,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    proc.communicate()

    return proc.returncode == 0


def is_service_abnormal(service_obj, node_obj):
    cur_status = service_check(SYSTEMCTL_STATUS, service_obj.name,
                               node_obj.role, node_obj.type)
    LOG.debug("Service %(name)s check result: %(status)s",
              {'name': service_obj.name, 'status': cur_status})
    if service_obj.status != cur_status:

        if service_obj.restarted:
            if cur_status == 'down' and service_obj.status == 'restarting':
                service_obj.status = 'error'
                LOG.debug("Service %(name)s set %(status)s status.",
                          {'name': service_obj.name,
                           'status': service_obj.status.upper()})
            elif cur_status == 'down' and service_obj.status == 'error':
                service_obj.status = cur_status
                LOG.debug("Service %(name)s set %(status)s status.",
                          {'name': service_obj.name,
                           'status': service_obj.status.upper()})
            else:
                service_obj.status = cur_status
        else:
            service_obj.status = cur_status
        zk_cli = get_zk_cli()
        kwargs = {}
        if service_obj.status == 'up':
            if service_obj.restarted:
                kwargs['restarted'] = False
                kwargs['restarted_at'] = None
                service_obj.restarted = False
                service_obj.restarted_at = None
            if service_obj.alarmed:
                kwargs['alarmed'] = False
                kwargs['alarmed_at'] = None
                service_obj.alarmed = False
                service_obj.alarmed_at = None
        zk_cli.update_service(service_obj.name, node_obj.role, node_obj.type,
                              status=service_obj.status, **kwargs)
        LOG.info("Service %(name)s updated with %(status)s status.",
                 {'name': service_obj.name,
                  'status': service_obj.status.upper()})
    return service_obj.status != 'up'


def post_restarted_if_possible(service_obj, node_obj):
    if not service_obj.restarted:
        zk_cli = get_zk_cli()
        updated_svc = zk_cli.update_service(
            service_obj.name, node_obj.role, node_obj.type,
            restarted=True, status='restarting')
        LOG.info("Service %(name)s updated with %(status)s status "
                 "and restarted=True",
                 {'name': service_obj.name,
                  'status':'restarting'.upper()})
        service_obj.restarted = True
        service_obj.restarted_at = updated_svc.restarted_at


def report_heart_beat(node_obj):
    hb = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    zk_cli = get_zk_cli()
    update_dict = {'heartbeat': hb}
    if node_obj.status == 'initializing':
        update_dict['status'] = 'up'
    zk_cli.update_node(node_obj.name, **update_dict)
    LOG.debug("Report node %(name)s heartbeat %(hb)s",
              {'name': node_obj.name, 'hb':hb})
    node_obj.heartbeat = hb


def is_check_heart_beat_overtime(node_obj):
    try:
        over_time = parse_isotime(
            node_obj.heartbeat) + datetime.timedelta(
            seconds=HEARTBEAT_INTERNAL_TIMEOUT)
    except ValueError:
        # The heartbeat is not formatted, this must be the kp on the node
        # is not finish the first loop. We just return False, as we are in
        # the initializing process.
        return False
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
        GLOBAL_NODE = zk_cli.get_node(get_local_hostname())
    return GLOBAL_NODE


def refresh():
    local_node = get_local_node()
    # script_load_pre_check(local_node)
    if local_node.status in ['maintaining', 'down']:
        LOG.debug('Node %(name)s status is %(status)s, Skipping refresh.',
                  {'name': local_node.name,
                   'status': local_node.status.upper()})
        return
    local_node_service_process(local_node)
    if local_node.role != 'zookeeper':
        oppo_node_process()

    # At the end of the script, we'd better to close zk session.
    zk_cli = get_zk_cli()
    zk_cli.disconnect()


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


def oppo_node_process():
    op_nodes = get_the_oppo_nodes()
    oppo_node_check(op_nodes)


def local_node_service_process(node_obj):
    zk_cli = get_zk_cli()
    service_objs = zk_cli.list_services(
        node_name_filter=str(node_obj.name),
        node_role_filter=str(node_obj.role))
    for service_obj in service_objs:
        treat_single_service(service_obj, node_obj)

    report_heart_beat(node_obj)


def treat_single_service(service_obj, node_obj):
    if is_service_abnormal(service_obj, node_obj):
        LOG.debug("Service %(name)s is abnormal. It's status is %(status)s.",
                  {'name': service_obj.name,
                   'status': service_obj.status.upper()})
        if service_obj.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                    'nodepool-timer-tasks']:
            post_restarted_if_possible(service_obj, node_obj)


def oppo_node_check(oppo_node_objs):
    for oppo_node_obj in oppo_node_objs:
        # check pingable and heartbeat is OK
        # Case clean:
        # Case 1: If the oppo node can pingable but heartbeat is overtime
        #      -- This case must be the kp error, as no heartbeat upload, but
        #      -- the host is alived.
        # Case 2: If the oppo node can not pingable and heartbeart is not
        #         overtime.
        #      -- This case must be network error, it makes this script can not
        #      -- access the opposite node.

        # Case 1
        if (not ping(oppo_node_obj.ip) and
              is_check_heart_beat_overtime(oppo_node_obj)):
            if oppo_node_obj.role == 'master' and oppo_node_obj.status == 'up':
                # Report the issue towards deployment as oppo host is master
                # Master/Slave Switch
                # So current node is slave, we need to set the oppo side ones
                # to down
                zk_cli = get_zk_cli()
                for oppo in oppo_node_objs:
                    zk_cli.update_node(oppo.name, status='down')
                    LOG.info("OPPO %(role)s node %(name)s updated with "
                             "%(status)s status.",
                             {'role': oppo.role, 'name': oppo.name,
                              'status': 'down'.upper()})
            break


if __name__ == '__main__':
    refresh()
