#!/usr/bin/python3

import socket
import subprocess
import datetime
import time
import iso8601
import six
import requests
import json
import configparser
from github import Github
from openlabcmd import zk

# ZK client config file
ZK_CLI_CONF = "{{ zk_cli_conf }}"

# Heartbeat Interanl time(seconds)
HEARTBEAT_INTERNAL = {{ heartbeat_internal }}

# Simpledns provider
base_api_url = 'https://api.dnsimple.com/v2/'
DOMAIN_NAME = 'openlabtesting.org'
DOMAIN_NAME1 = 'status.openlabtesting.org'
DOMAIN_NAME2 = 'logs.openlabtesting.org'
DOMAIN_NAME_BK = 'logs-bak.openlabtesting.org'
TARGET_ORI_IP = "{{ ori_master_ip }}"
TARGET_ORI_BK_IP = "{{ ori_backup_ip }}"
TARGET_CHANGE_IP = "{{ slave_ip }}"
TARGET_CHANGE_BK_IP = "{{ slave_backup_ip }}"
TOKEN = "{{ dns_access_token }}"
ACCOUNT_ID = {{ dns_account_id }}

# Post user info
ISSUE_USER_TOKEN = "{{ github_token }}"
REPO_NAME = 'theopenlab/openlab'

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
    return socket.gethostname()


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
    cli = ['ping', '-c3', '-w1']
    cli.append(ipaddr)
    proc = subprocess.Popen(cli,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    proc.communicate()

    return proc.returncode == 0


class Service(object):
    def __init__(self, name, alarmed, alarmed_at, restarted, restarted_at,
                 is_necessary, node_role, status, **kwargs):
        self.name = name
        self.alarmed = alarmed
        self.alarmed_at = alarmed_at
        self.restarted = restarted
        self.restarted_at = restarted_at
        self.is_necessary = is_necessary
        self.node_role = node_role
        self.status = status

    def is_abnormal(self):
        self.status = run_systemctl_command(SYSTEMCTL_STATUS, self.name)
        zk_cli = get_zk_cli()
        zk_cli.update_service(self.name, role=self.node_role,
                              status=self.status)
        return self.status != 'up'

    def is_alarmed_timeout(self):
        over_time = parse_isotime(
            self.alarmed_at) + datetime.timedelta(
            days=2)
        current_time = datetime.datetime.utcnow()
        return current_time > over_time

    def post_alarmed_if_possible(self):
        if not self.alarmed:
            zk_cli = get_zk_cli()
            updated_svc = zk_cli.update_service(
                self.name, role=self.node_role, alarmed=True)
            self.alarmed = True
            self.alarmed_at = updated_svc['alarmed_at']

    def post_restarted_if_possible(self):
        if not self.alarmed:
            zk_cli = get_zk_cli()
            updated_svc = zk_cli.update_service(
                self.name, role=self.node_role,
                restarted=True, status='restarting')
            self.restarted = True
            self.restarted_at = updated_svc['restarted_at']


class Node(object):
    def __init__(self, name, role, type, ip, heartbeat,
                 alarmed, status, **kwargs):
        self.name = name
        self.role = role
        self.type = type
        self.ip = ip
        self.old_heartbeat = heartbeat
        self.alarmed = alarmed
        self.status = status

        self.hb_interval_time = HEARTBEAT_INTERNAL
        self.services = []
        self.necessary_service_names = []

    def report_heart_beat(self):
        hb = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        zk_cli = get_zk_cli()
        zk_cli.update_node(self.name, heartbeat=hb)
        self.old_heartbeat = hb

    def is_check_heart_beat_overtime(self):
        over_time = parse_isotime(
            self.old_heartbeat) + datetime.timedelta(
            seconds=self.hb_interval_time)
        current_time = datetime.datetime.utcnow()
        return current_time > over_time

    def is_necessary_service(self, service_name):
        return service_name in self.necessary_service_names

    def is_maintained(self):
        return self.status == 'maintaining'

    def post_alarmed_if_possible(self):
        if not self.alarmed:
            zk_cli = get_zk_cli()
            zk_cli.update_node(self.name, alarmed=True)
            self.alarmed = True


def get_zk_cli():
    global GLOBAL_ZK
    if not GLOBAL_ZK:
        cfg = configparser.ConfigParser().read(ZK_CLI_CONF)
        zk_cli = zk.ZooKeeper(cfg)
        zk_cli.connect()
        GLOBAL_ZK = zk_cli
    return GLOBAL_ZK


def load_from_zk():
    zk_cli = get_zk_cli()
    node_name = get_local_hostname()
    zk_cli.connect()
    zk_node = zk_cli.get_node(node_name)
    local_node = Node(zk_node['name'], zk_node['role'],
                      zk_node['type'], zk_node['ip'],
                      zk_node['heartbeat'], zk_node['alarmed'],
                      zk_node['status'])

    for service in zk_cli.list_services(node=node_name):
        local_node.services.append(
            Service(service['name'], service['alarmed'],
                    service['alarmed_at'], service['restarted'],
                    service['restarted_at'], service['is_necessary'],
                    service['node_tole'], service['status']))
        if service['is_necessary']:
            local_node.necessary_service_names.append(service['name'])

    global GLOBAL_NODE
    GLOBAL_NODE = local_node
    return GLOBAL_NODE


def get_local_node():
    global GLOBAL_NODE
    if not GLOBAL_NODE:
        return load_from_zk()
    return GLOBAL_NODE


def process():
    local_node = get_local_node()
    switch_process(local_node, first_run=True)
    local_node_service_process(local_node)
    oppo_node_process()


def local_node_service_process(node_obj):
    for service_obj in node_obj.services:
        treat_single_service(service_obj, node_obj)

    node_obj.report_heart_beat()


def treat_single_service(service_obj, node_obj):
    if node_obj.is_maintained:
        return

    if service_obj.is_abnormal():
        if service_obj.restarted:
            if node_obj.is_necessary_service(service_obj.name):
                # Report an issue towards deployment as a necessary
                # service down
                # Master/Slave Switch
                switch_process(node_obj)
                notify_issue(node_obj, affect_services=service_obj,
                             affect_range='node',
                             more_specific='necessary_error')
            else:
                # Have report the issue yet?
                # Yes
                if service_obj.alarmed:

                    # --- the issue is timeout ?
                    # -- Yes
                    if service_obj.is_alarmed_timeout():

                        # $$ this node is master ?
                        # $$ Yes
                        # Report an issue towards deployment as a unnecessary
                        # service issue timeout.
                        # Master/Slave Switch
                        if node_obj.role == 'master':
                            switch_process(node_obj)
                    # -- No
                    # report node heartbeat
                    else:
                        # We can just return/go through,
                        # as the outside loop will set the node heartbeat
                        pass

                # No
                # Report an issue towards node and service as a
                # unnecessary service down.
                # Then report node heartbeat.
                else:
                    notify_issue(node_obj, affect_services=service_obj,
                                 affect_range='service',
                                 more_specific='unecessary_svc')
        else:
            # restart the specific service
            run_systemctl_command(SYSTEMCTL_RESTART, service_obj.name)
            service_obj.post_restarted_if_possible()


def shut_down_all_services(node_obj):
    for service in node_obj.services:
        run_systemctl_command(SYSTEMCTL_STOP, service.name)
    node_obj.services = []


def setup_necessary_services_and_check(node_obj):
    for service in node_obj.necessary_service_names:
        run_systemctl_command(SYSTEMCTL_START, service)

    # local deplay 5 seconds
    time.sleep(5)

    # Then we check all services status in 'SLAVE' env.
    result = {}
    for service in node_obj.services:
        result[service.name] = run_systemctl_command(
            SYSTEMCTL_STATUS, service.name)

    for svc_name, res in result.items():
        if res != 0:
            print("%s is failed to start with return code %s" % (
                svc_name, res))


def switch_process(node_obj, first_run=False):
    if (first_run and node_obj.status == 'slave_uping' and
            node_obj.role == 'slave'):
        # setup local services and check services status
        # at the end of process, we will set this node status to up and
        # role to MASTER
        setup_necessary_services_and_check(node_obj)
        change_dns()
        zk_cli = get_zk_cli()
        zk_cli.update_node(node_obj.name, role='master', status='up')
        notify_issue(node_obj, affect_range='node',
                     more_specific='slave_switch')

    if (first_run and node_obj.status == 'down' and
            node_obj.role == 'master'):
        # This is the first step when other master nodes, when check
        # self status is down, that means there must be 1 master node is
        # failed and hit the M/S switch. So what we gonna do is shuting down
        # local services and set self role from master to slave.
        shut_down_all_services(node_obj)
        zk_cli = get_zk_cli()
        zk_cli.update_node(node_obj.name, role='slave')

    if not first_run:
        if node_obj.role == 'master':
            # Now, we must hit the services error, not host poweroff,
            # as the kp is alived, so we need to shut down all the necessary
            # and unecessary services.
            zk_cli = get_zk_cli()
            shut_down_all_services(node_obj)
            same_nodes = get_the_same_nodes()
            zk_cli.update_node(node_obj.name, role='slave', status='down')
            for node in same_nodes:
                zk_cli.update_node(node.name, status='down')
            # Set slave env status to 'slave_uping'
            oppo_nodes = get_the_oppo_nodes()
            for node in oppo_nodes:
                zk_cli.update_node(node.name, status='slave_uping')

        elif node_obj.role == 'slave':
            # If we arrive here, that means, slave env call this function
            # actively, but in our case, when we arrive here, but the role
            # is 'SLAVE', we'd better to check the data plane services and
            # post an issue.
            svc_status = []
            for svc in node_obj.services:
                if svc.is_abnormal():
                    svc_status.append(False)
            if not any(svc_status):
                notify_issue(node_obj, affect_range='node',
                             more_specific='slave_error')


def get_the_same_nodes():
    zk_cli = get_zk_cli()
    same_nodes = []
    local_node_obj = get_local_node()
    for zk_node in zk_cli.list_nodes():
        if (zk_node['role'] != local_node_obj.role and
                zk_node['name'] == local_node_obj.name):
            continue
        same_nodes.append(Node(zk_node['name'], zk_node['role'],
                               zk_node['type'], zk_node['ip'],
                               zk_node['heartbeat'], zk_node['alarmed'],
                               zk_node['status']))

    return same_nodes


def get_the_oppo_nodes():
    zk_cli = get_zk_cli()
    oppo_nodes = []
    local_node_obj = get_local_node()
    for zk_node in zk_cli.list_nodes():
        if zk_node['role'] == local_node_obj.role:
            continue
        oppo_nodes.append(Node(zk_node['name'], zk_node['role'],
                               zk_node['type'], zk_node['ip'],
                               zk_node['heartbeat'], zk_node['alarmed'],
                               zk_node['status']))

    return oppo_nodes


def oppo_node_check(oppo_node_objs):
    for oppo_node_obj in oppo_node_objs:
        # check pingable and heartbeat is OK
        if (not ping(oppo_node_obj.ip) or
                oppo_node_obj.is_check_heart_beat_overtime()):
            if oppo_node_obj.role == 'master':
                # Report the issue towards deployment as oppo host is master
                # Master/Slave Switch
                local_node = get_local_node()
                switch_process(local_node)
            # else:
            # Report the issue towards deployment as the oppo host is slave
            notify_issue(oppo_node_obj,
                         affect_range='node',
                         more_specific='oppo_check')
            break


def oppo_node_process():
    op_nodes = get_the_oppo_nodes()
    oppo_node_check(op_nodes)


def format_body_for_issue(node_obj, affect_services=None,
                          affect_range=None, more_specific=None):
    body = "For recover the ENV, you need to do the " \
           "following things manually.\n"
    if affect_range == 'node':
        if more_specific == 'oppo_check':
            body += "The target node %(name)s in %(role)s deployment is " \
                    "failed to be accessed with IP %(ip)s.\n" % (
                {'name': node_obj.name,
                 'role': node_obj.role,
                 'ip': node_obj.ip})
            if node_obj.role == 'MASTER':
                body += "HA tools already switch to slave deployment, " \
                        "please try a simple job to check whether " \
                        "everything is OK.\n"
            body += "Have a try:\n" \
                    "ssh ubuntu@%s\n" % node_obj.ip
            body += "And try to login the cloud to check whether the " \
                    "resource exists.\n"
        elif more_specific == 'slave_error':
            body += "The data plane services of node %(name)s in slave " \
                    "deployment hit errors.\n"
            svcs = []
            for svc in node_obj.services:
                svcs.append(svc.name)
            body += "The affected services including:\n %s\n" % " ".join(svcs)
            body += "Have a try:\n" \
                    "ssh ubuntu@%s\n" % node_obj.ip
            for s in svcs:
                body += "systemctl %s %s\n" % (SYSTEMCTL_RESTART, s)
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
            body += "Have a try:\n" \
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
            body += "Have a try:\n" \
                    "ssh ubuntu@%s\n" \
                    "systemctl %s %s\n" \
                    "journalctl -u %s\n" % (node_obj.ip, SYSTEMCTL_STATUS,
                                            affect_services.name,
                                            affect_services.name)
    return body


def notify_issue(affect_node, affect_services=None, affect_range=None,
                 more_specific=None):
    body = format_body_for_issue(
        affect_node, affect_services=affect_services,
        affect_range=affect_range, more_specific=more_specific)
    g = Github(login_or_token=ISSUE_USER_TOKEN)
    repo = g.get_repo(REPO_NAME)
    repo.create_issue(
        title="[FATAL][%s] The online openlab deployment <%s> has Down, "
              "Please recovery asap!" % (
                  datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                  affect_node.role),
        body=body)


def match_record(name, res):
    if res['name'] == 'logs-bak':
        return (name == res['name'] and res['type'] == "A" and
                TARGET_ORI_BK_IP == res['content'])
    return (name == res['name'] and
            res['type'] == "A" and TARGET_ORI_IP == res['content'])


def change_dns():
    headers = {'Authorization': "Bearer %s" % TOKEN,
               'Accept': 'application/json'}
    res = requests.get(base_api_url + 'accounts', headers=headers)
    if res.status_code != 200:
        print("Failed to get the accounts")
        print("Details: code-status %s\n         message: %s" % (
            res.status_code, res.reason))
        return
    accounts = json.loads(s=res.content.decode('utf8'))['data']
    account_id = None
    for account in accounts:
        if account['id'] == ACCOUNT_ID:
            account_id = account['id']
            break
    if not account_id:
        print("Failed to get the account_id")
        return

    target_dict = {DOMAIN_NAME1: {}, DOMAIN_NAME2: {}, DOMAIN_NAME_BK: {}}
    for target_domain in target_dict.keys():
        res = requests.get(base_api_url + "%s/zones/%s/records?name=%s" % (
            account_id, DOMAIN_NAME, target_domain.split(DOMAIN_NAME)[0][:-1]),
                           headers=headers)
        if res.status_code != 200:
            print("Failed to get the records by name %s" % target_domain)
            print("Details: code-status %s\n         message: %s" % (
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
            print("Failed to get the record_id by name %s" % target_domain)
            return

    if not any(target_dict.values()):
        print("Can't not get any records.")
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
        if result['name'] != 'logs-bak':
            if (res.status_code == 200 and
                    result['content'] == TARGET_CHANGE_IP):
                print("Success Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_IP, TARGET_CHANGE_IP))
            else:
                print("Fail Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_IP, TARGET_CHANGE_IP))
                print("Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
                return
        else:
            if (res.status_code == 200 and
                    result['content'] == TARGET_CHANGE_BK_IP):
                print("Success Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_BK_IP, TARGET_CHANGE_BK_IP))
            else:
                print("Fail Update -- Domain %s from %s to %s" % (
                    target_domain, TARGET_ORI_BK_IP, TARGET_CHANGE_BK_IP))
                print("Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
                return


if __name__ == '__main__':
    process()
