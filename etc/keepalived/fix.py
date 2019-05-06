#!/usr/bin/python2

import socket
import subprocess
import datetime
import iso8601
import six
import configparser
from github import Github
from openlabcmd import zk

# ZK client config file
ZK_CLI_CONF = "{{ zk_cli_conf }}"

# Heartbeat Internal timeout(seconds)
HEARTBEAT_INTERNAL_TIMEOUT = {{ heartbeat_internal }}

# Post user info
{% if use_test_account %}
ISSUE_USER_TOKEN = "{{ test_github_token }}"
REPO_NAME = "{{ test_repo_name }}"
{% else %}
ISSUE_USER_TOKEN = "{{ github_token }}"
REPO_NAME = 'theopenlab/openlab'
{% endif %}

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


def get_local_hostname():
    #(TODO) remove after labkeeper vm instance name is the same with the
    # openlabcmd node name format, like {cloud}-openlab-{role}.
    return socket.gethostname()

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
        if command == SYSTEMCTL_STATUS:
            return 'up'
    except subprocess.CalledProcessError as e:
        print("Failed to %(cmd)s %(srvc)s service: "
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

def is_alarmed_timeout(svc_obj):
    over_time = parse_isotime(
        svc_obj.alarmed_at) + datetime.timedelta(
        days=2)
    current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
    return current_time > over_time


def post_alarmed_if_possible(obj):
    if not obj.alarmed:
        zk_cli = get_zk_cli()
        if 'node' in obj.__name__.lower():
            zk_cli.update_node(obj.name, alarmed=True)
            obj.alarmed = True
        elif 'service' in obj.__name__.lower():
            local_node = get_local_node()
            updated_svc = zk_cli.update_service(
                obj.name, local_node.role, local_node.type, alarmed=True)
            obj.alarmed = True
            obj.alarmed_at = updated_svc['alarmed_at']

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

def get_the_same_nodes():
    zk_cli = get_zk_cli()
    same_nodes = []
    local_node_obj = get_local_node()
    for zk_node in zk_cli.list_nodes():
        if (zk_node.role != local_node_obj.role or
                zk_node.name == local_node_obj.name):
            continue
        elif zk_node['role'] in ['master', 'slave']:
            same_nodes.append(zk_node)

    return same_nodes


def format_body_for_issue(issuer_node, node_obj, affect_services=None,
                          affect_range=None, more_specific=None):
    title = "[OPENLAB HA][%s] "
    body = "Issuer Host Info:\n" \
           "===============\n" \
           "  name: %(name)s\n" \
           "  role: %(role)s\n" \
           "  ip: %(ip)s\n" % {
        "name": issuer_node.name,
        "role": issuer_node.role,
        "ip": issuer_node.ip
    }

    body += "\nReason:\n" \
            "===============\n"
    if affect_range == 'node':
        if more_specific == 'oppo_check':
            body += "The target node %(name)s in %(role)s deployment is " \
                    "failed to be accessed with IP %(ip)s or fetching its " \
                    "heartbeat.\n" % (
                {'name': node_obj.name,
                 'role': node_obj.role,
                 'ip': node_obj.ip})
            if node_obj.role == 'MASTER':
                body += "HA tools already switch to slave deployment, " \
                        "please try a simple job to check whether " \
                        "everything is OK.\n"
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "ssh ubuntu@%s\n" % node_obj.ip
            body += "And try to login the cloud to check whether the " \
                    "resource exists.\n"
            title += "%s check %s failed, need to recover manually." % (
                issuer_node.role, node_obj.role)
        elif more_specific == 'slave_error':
            body += "The data plane services of node %s in slave " \
                    "deployment hit errors.\n" % node_obj.name
            svcs = []
            for svc in node_obj.services:
                svcs.append(svc.name)
            body += "The affected services including:\n %s\n" % " ".join(svcs)
            body += "\nSuggestion:\n" \
                    "ssh ubuntu@%s\n" % node_obj.ip
            for s in svcs:
                body += "systemctl %s %s\n" % (SYSTEMCTL_RESTART, s)
            title += "slave node %s has down, need to recover manually." % (
                node_obj.name)
        elif more_specific in ['slave_switch', 'necessary_error']:
            body += "HA tools already switch to slave deployment, please " \
                    "try a simple job to check whether everything is OK.\n"
            body += "Currently, the slave deployment has changed to master.\n"
            body += "Please check original master deployment to check " \
                    "whether it is good for recovery or use labkeeper to " \
                    "re-create an new slave deployment.\n"
            if more_specific == 'necessary_error':
                body += "This switch happened by necessary service check " \
                        "error.\n"
                body += "Error service:\n"
                body += "%s\n" % affect_services.name
                title += "%s node - %s 's necessary services %s are dead. HA " \
                         "switch going." % (node_obj.role, node_obj.name,
                                            affect_services.name)
            else:
                title += "%s node - %s is dead. HA " \
                         "switch going." % (node_obj.role, node_obj.name)
            body += "\nSuggestion:\n" \
                    "ssh ubuntu@%s\n" \
                    "cd go-to-labkeeper-directory\n" \
                    "./deploy.sh -d new-slave\n" % node_obj.ip
        elif affect_range == 'service':
            if more_specific == 'unecessary_svc':
                body += "A unecessary serivce %(service_name)s on the node " \
                        "%(name)s (IP %(ip)s) has done. Please go ahead to " \
                        "check.\n" % ({'service_name': affect_services.name,
                                       'name': node_obj.name,
                                       'ip': node_obj.ip})
                body += "\nSuggestion:\n" \
                        "ssh ubuntu@%s\n" \
                        "systemctl %s %s\n" \
                        "journalctl -u %s\n" % (node_obj.ip, SYSTEMCTL_STATUS,
                                                affect_services.name,
                                                affect_services.name)
                title += "%s node - %s 's unnecessary services %s are dead, " \
                         "need to recover manually." % (
                             node_obj.role, node_obj.name,
                             affect_services.name)
        return title, body

def notify_issue(issuer_node, affect_node, affect_services=None,
                 affect_range=None, more_specific=None):
    title, body = format_body_for_issue(
        issuer_node, affect_node, affect_services=affect_services,
        affect_range=affect_range, more_specific=more_specific)
    g = Github(login_or_token=ISSUE_USER_TOKEN)
    repo = g.get_repo(REPO_NAME)
    repo.create_issue(
        title= title % (
                  datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        body=body)


def script_load_pre_check(node_obj):
    if (node_obj.status == 'up' and node_obj.role == 'slave' and
            not check_opp_master_is_good()):

        # setup local services and check services status
        # at the end of process, we will set this node status to up and
        # role to MASTER
        same_nodes = get_the_same_nodes()
        is_alarmed_nodes = [node for node in same_nodes if node.alarmed]
        if len(is_alarmed_nodes) == 0 and not node_obj.alarmed:

            notify_issue(node_obj, node_obj, affect_range='node',
                         more_specific='slave_switch')
            post_alarmed_if_possible(node_obj)


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
        node_name_filter=node_obj.name, node_role_filter=node_obj.role)
    for service_obj in service_objs:
        treat_single_service(service_obj, node_obj)


def treat_single_service(service_obj, node_obj):
    if service_obj.restarted:
        if service_obj.status == 'restarting':
            if service_obj.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                        'nodepool-timer-tasks']:
                # restart the specific service
                service_restart(SYSTEMCTL_RESTART, service_obj.name)
        elif service_obj.status == 'down':
            if service_obj.is_necessary:
                if not node_obj.alarmed:
                    notify_issue(node_obj, node_obj,
                                 affect_services=service_obj,
                                 affect_range='node',
                                 more_specific='necessary_error')
                    post_alarmed_if_possible(service_obj)
                    post_alarmed_if_possible(node_obj)
            else:
                if service_obj.alarmed:
                    if is_alarmed_timeout(service_obj):
                        if node_obj.role == 'master' and not node_obj.alarmed:
                            notify_issue(node_obj, node_obj,
                                         affect_range='node',
                                         more_specific='slave_switch')
                            post_alarmed_if_possible(node_obj)

                else:
                    notify_issue(node_obj, node_obj,
                                 affect_services=service_obj,
                                 affect_range='service',
                                 more_specific='unecessary_svc')
                    post_alarmed_if_possible(service_obj)

def check_opp_master_is_good():
    oppo_nodes = get_the_oppo_nodes()
    all_result = 0
    for node in oppo_nodes:
        if node.status == 'down':
            all_result += 1
    if all_result > 0 or (all_result == 0 and len(oppo_nodes) < 2):
        return False
    return True


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


def oppo_node_check(oppo_node_objs):
    local_node = get_local_node()
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
        if (ping(oppo_node_obj.ip) and
                is_check_heart_beat_overtime(oppo_node_obj)):
            raise Exception("keepalived error.")
        elif (not ping(oppo_node_obj.ip) and
              is_check_heart_beat_overtime(oppo_node_obj)):
            raise Exception("network error.")
        elif (not ping(oppo_node_obj.ip) and
              is_check_heart_beat_overtime(oppo_node_obj)):
            if not oppo_node_obj.alarmed:
                notify_issue(local_node, oppo_node_obj,
                             affect_range='node',
                             more_specific='oppo_check')
            break


def fix():
    local_node = get_local_node()
    script_load_pre_check(local_node)
    if local_node.status in ['maintaining', 'down']:
        return
    local_node_service_process(local_node)
    if local_node.role != 'zookeeper':
        oppo_node_process()

    # At the end of the script, we'd better to close zk session.
    zk_cli = get_zk_cli()
    zk_cli.disconnect()


if __name__ == '__main__':
    fix()