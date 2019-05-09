#!/usr/bin/python3
import configparser
import datetime
import json
import logging
import socket
import subprocess
import time
import os

from github import Github
import iso8601
from openlabcmd import zk
import requests


logging.basicConfig(
    filename="/etc/openlab/ha_healthchecker/ha_healthchecker.log",
    filemode='a',
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.DEBUG)
LOG = logging.getLogger(__name__)


# Post user info
{% if use_test_account %}
ISSUE_USER_TOKEN = "{{ test_github_token }}"
REPO_NAME = "{{ test_repo_name }}"
{% else %}
ISSUE_USER_TOKEN = "{{ github_token }}"
REPO_NAME = 'theopenlab/openlab'
{% endif %}

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


class Base(object):
    def __init__(self, zk, heartbeat_timeout):
        self.zk = zk
        self.heartbeat_timeout = heartbeat_timeout
        self.node = self.zk.get_node(socket.gethostname())
        self.oppo_node = self._get_oppo_node()

    def _get_oppo_node(self):
        for zk_node in self.zk.list_nodes():
            if (zk_node.role != self.node.role and
                    zk_node.type == self.node.type):
                return zk_node

    def _is_check_heart_beat_overtime(self, node_obj):
        try:
            over_time = iso8601.parse_date(
                node_obj.heartbeat) + datetime.timedelta(
                seconds=self.heartbeat_timeout)
        except (iso8601.ParseError, TypeError, ValueError):
            # The heartbeat is not formatted, this must be the kp on the node
            # is not finish the first loop. We just return False, as we are in
            # the initializing process.
            return False
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def _ping(self, ipaddr):
        cli = ['ping', '-c1', '-w1', ipaddr]
        proc = subprocess.Popen(cli, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        proc.communicate()

        return proc.returncode == 0


class Refresher(Base):
    def __init__(self, zk, heartbeat_timeout):
        super(Refresher, self).__init__(zk, heartbeat_timeout)

    def _local_node_service_process(self, node_obj):
        service_objs = self.zk.list_services(node_name_filter=node_obj.name)
        for service_obj in service_objs:
            self._refresh_service(service_obj, node_obj)

        self._report_heart_beat(node_obj)

    def _get_service_status(self, service):
        # gearman is controlled by zuul itself. It's not under systemd.
        if service == 'gearman':
            return 'up' if os.path.exists(
                '/run/gearman/server.pid') else 'down'

        # timer tasks are handled by crontab
        if service in ['zuul-timer-tasks', 'nodepool-timer-tasks']:
            service = 'cron'

        cmd = "systemctl status {srvc}".format(srvc=service)
        try:
            # 0 means OK
            # if using status command, 0 means active, non-zero means error
            # status.
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            LOG.debug("Run CMD: %(cmd)s", {'cmd': cmd})
            return 'up'
        except subprocess.CalledProcessError as e:
            LOG.error("Failed to check %(srvc)s service: "
                      "%(err)s %(out)s", {'srvc': service, 'err': e,
                                          'out': e.output})
            return 'down'

    def _refresh_service(self, service_obj, node_obj):
        cur_status = self._get_service_status(service_obj.name)
        LOG.debug("Service %(name)s check result: %(status)s",
                  {'name': service_obj.name, 'status': cur_status})
        update_dict = {}
        if cur_status == 'up':
            if service_obj.status != 'up':
                update_dict['status'] = 'up'
                update_dict['restarted'] = False
                update_dict['alarmed'] = False
        else:
            if not service_obj.restarted:
                update_dict['status'] = 'restarting'
                update_dict['restarted'] = True
            else:
                update_dict['status'] = 'down'
        if update_dict:
            self.zk.update_service(service_obj.name, node_obj.name,
                                   **update_dict)

        if cur_status != 'up':
            LOG.debug(
                "Service %(name)s is abnormal. It's status is %(status)s.",
                {'name': service_obj.name,
                 'status': service_obj.status.upper()})

    def _report_heart_beat(self, node_obj):
        hb = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        update_dict = {'heartbeat': hb}
        if node_obj.status == 'initializing':
            update_dict['status'] = 'up'
        self.zk.update_node(node_obj.name, **update_dict)
        LOG.debug("Report node %(name)s heartbeat %(hb)s",
                  {'name': node_obj.name, 'hb': hb})

    def _oppo_node_check(self, oppo_node_obj):
        if self.node.type == 'zookeeper':
            return
        if oppo_node_obj.status == 'maintaining':
            return
        if (not self._ping(oppo_node_obj.ip) and
                self._is_check_heart_beat_overtime(oppo_node_obj)):
            if oppo_node_obj.role == 'master' and oppo_node_obj.status == 'up':
                # Report the issue towards deployment as oppo host is master
                # Master/Slave Switch
                # So current node is slave, we need to set the oppo side ones
                # to down
                self.zk.update_node(oppo_node_obj.name, status='down')
                LOG.info("OPPO %(role)s node %(name)s updated with "
                         "%(status)s status.",
                         {'role': oppo_node_obj.role,
                          'name': oppo_node_obj.name,
                          'status': 'down'.upper()})

    def run(self):
        if self.node.status in ['maintaining', 'down']:
            LOG.debug(
                'Node %(name)s status is %(status)s, Skipping refresh.',
                {'name': self.node.name,
                 'status': self.node.status.upper()})
            return
        self._local_node_service_process(self.node)
        self._oppo_node_check(self.oppo_node)


class Fixer(Base):
    def __init__(self, zk, heartbeat_timeout):
        super(Fixer, self).__init__(zk, heartbeat_timeout)

    def _service_restart(self, service):
        cmd = "systemctl restart {srvc}".format(srvc=service)
        try:
            # 0 means OK
            # if using status command, 0 means active, non-zero means error status.
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            LOG.debug("Run CMD: %(cmd)s", {'cmd': cmd})
        except subprocess.CalledProcessError as e:
            LOG.error("Failed to restart %(srvc)s service: "
                      "%(err)s %(out)s", {'srvc': service,
                                          'err': e, 'out': e.output})

    def _fix_service(self, service_obj, node_obj):
        if service_obj.status == 'restarting':
            if service_obj.name == 'gearman':
                return
            if service_obj.name in ['zuul-timer-tasks','nodepool-timer-tasks']:
                service_name = 'cron'
            else:
                service_name = service_obj.name
            self._service_restart(service_name)
            LOG.info("Service %(name)s restarted already.",
                     {'name': service_obj.name})
        elif service_obj.status == 'down':
            if not service_obj.alarmed:
                self._notify_issue(xxxx)
                self.zk.update_service(service_obj.name, self.node.name,
                                       alarmed=True)

    def _local_node_service_process(self, node_obj):
        service_objs = self.zk.list_services(node_name_filter=node_obj.name)
        for service_obj in service_objs:
            self._fix_service(service_obj, node_obj)

    def _format_body_for_issue(self, issuer_node, node_obj,
                               affect_services=None,
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
                body += "The affected services including:\n %s\n" % " ".join(
                    svcs)
                body += "\nSuggestion:\n" \
                        "===============\n" \
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
                        "===============\n" \
                        "ssh ubuntu@%s\n" \
                        "cd go-to-labkeeper-directory\n" \
                        "./deploy.sh -d new-slave\n" % node_obj.ip
            elif more_specific in ['healthchecker_error', 'network_error']:
                if more_specific == 'healthchecker_error':
                    title += "%s node %s - ha_healthchecker are dead." % (
                        node_obj.role, node_obj.name)
                    body += "ha_healthchecker not working anymore, please " \
                            "login to fix it.\n"
                    body += "\nSuggestion:\n" \
                            "===============\n" \
                            "ssh ubuntu@%s\n" \
                            "systemctl status ha_healthchecker.timer\n" \
                            "systemctl status ha_healthchecker.service\n" \
                            "systemctl enable ha_healthchecker.service\n" \
                            "systemctl enable ha_healthchecker.timer\n" \
                            "systemctl start ha_healthchecker.timer\n" \
                            "systemctl list-timers --all\n" % node_obj.ip
                elif more_specific == 'network_error':
                    title += "%s node %s - Hit network error." % (
                        node_obj.role, node_obj.name)
                    body += "Can not access node %s by ip %s using PING, " \
                            "but ha_healthchecker on it still works.\n" % (
                                node_obj.name, node_obj.ip)
                    body += "\nSuggestion:\n" \
                            "===============\n" \
                            "Please check its security group setting.\n"
            elif affect_range == 'service':
                if more_specific == 'unecessary_svc':
                    body += "A unecessary serivce %(service_name)s on the node " \
                            "%(name)s (IP %(ip)s) has done. Please go ahead to " \
                            "check.\n" % (
                            {'service_name': affect_services.name,
                             'name': node_obj.name,
                             'ip': node_obj.ip})
                    body += "\nSuggestion:\n" \
                            "===============\n" \
                            "ssh ubuntu@%s\n" \
                            "systemctl %s %s\n" \
                            "journalctl -u %s\n" % (
                            node_obj.ip, SYSTEMCTL_STATUS,
                            affect_services.name,
                            affect_services.name)
                    title += "%s node - %s 's unnecessary services %s are dead, " \
                             "need to recover manually." % (
                                 node_obj.role, node_obj.name,
                                 affect_services.name)
            return title, body

    def _notify_issue(self, issuer_node, affect_node, affect_services=None,
                     affect_range=None, more_specific=None):
        title, body = self._format_body_for_issue(
            issuer_node, affect_node, affect_services=affect_services,
            affect_range=affect_range, more_specific=more_specific)
        g = Github(login_or_token=ISSUE_USER_TOKEN)
        repo = g.get_repo(REPO_NAME)
        repo.create_issue(
            title=title % (
                datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            body=body)
        LOG.info("Post a Issue for %(title)s with reason %(reason)s.",
                 {'title': title % (
                     datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
                  'reason': more_specific})

    def _oppo_node_check(self, oppo_node_obj):
        if (self._ping(oppo_node_obj.ip) and
                self._is_check_heart_beat_overtime(oppo_node_obj)):
            if not oppo_node_obj.alarmed:
                self._notify_issue(self.node, oppo_node_obj,
                                   affect_range='node',
                                   more_specific='healthchecker_error')
        elif (not self._ping(oppo_node_obj.ip) and
              self._is_check_heart_beat_overtime(oppo_node_obj)):
            if not oppo_node_obj.alarmed:
                self._notify_issue(self.node, oppo_node_obj,
                                   affect_range='node',
                                   more_specific='network_error')
        elif (not self._ping(oppo_node_obj.ip) and
              self._is_check_heart_beat_overtime(oppo_node_obj)):
            if not oppo_node_obj.alarmed:
                self._notify_issue(self.node, oppo_node_obj,
                                   affect_range='node',
                                   more_specific='oppo_check')

    def run(self):
        if self.node.status in ['maintaining', 'down']:
            LOG.debug('Node %(name)s status is %(status)s, Skipping fix.',
                      {'name': self.node.name,
                       'status': self.node.status.upper()})
            return
        self._local_node_service_process(self.node)
        if self.node.role != 'zookeeper':
            self._oppo_node_check(self.oppo_node)


class Switcher(Base):
    def __init__(self, zk, heartbeat_timeout):
        super(Switcher, self).__init__(zk, heartbeat_timeout)

    def _check_service_pid_exist(self, service):
        if service == 'rsync' and os.path.exists(RSYNCD_PID_PATH):
            return 'up'
        elif service == 'gearman' and os.path.exists(GEARMAN_PID_PATH):
            return 'up'
        return 'down'

    def _service_check(self, command, service, node_role, node_type):
        if (
                node_role == 'slave' and service == 'rsync') or service == 'gearman':
            return self._check_service_pid_exist(service)
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

        return self._run_systemctl_command(command, service)

    def _service_action(self, command, service):
        return self._run_systemctl_command(command, service)

    def _run_systemctl_command(self, command, service):
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

    def _is_alarmed_timeout(self, svc_obj):
        over_time = parse_isotime(
            svc_obj.alarmed_at) + datetime.timedelta(
            days=2)
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def _local_node_service_process(self, node_obj):
        service_objs = self.zk.list_services(
            node_name_filter=str(node_obj.name),
            node_role_filter=str(node_obj.role))
        for service_obj in service_objs:
            self._treat_single_service(service_obj, node_obj)

    def _treat_single_service(self, service_obj, node_obj):
        if service_obj.status == 'down':
            if service_obj.restarted:
                if service_obj.is_necessary:
                    # Report an issue towards deployment as a necessary
                    # service down
                    # Master/Slave Switch
                    self._switch_process(node_obj)
                else:
                    # Have report the issue yet?
                    # Yes
                    if service_obj.alarmed:

                        # --- the issue is timeout ?
                        # -- Yes
                        if self._is_alarmed_timeout(service_obj):

                            # $$ this node is master ?
                            # $$ Yes
                            # Report an issue towards deployment as a unnecessary
                            # service issue timeout.
                            # Master/Slave Switch
                            if node_obj.role == 'master':
                                self._switch_process(node_obj)

    def _shut_down_all_services(self, node_obj):
        service_objs = self.zk.list_services(
            node_name_filter=str(node_obj.name),
            node_role_filter=str(node_obj.role))
        for service in service_objs:
            if service.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                    'nodepool-timer-tasks']:
                self._service_action(SYSTEMCTL_STOP, service.name)

    def _setup_necessary_services_and_check(self, node_obj):
        service_objs = self.zk.list_services(
            node_name_filter=str(node_obj.name),
            node_role_filter=str(node_obj.role))
        for service in service_objs:
            if service.is_necessary:
                if service.name not in ['rsync', 'gearman', 'zuul-timer-tasks',
                                        'nodepool-timer-tasks']:
                    self._service_action(SYSTEMCTL_START, service)
                    LOG.info("Start Service %(name)s.", {'name': service.name})

        # local deplay 5 seconds
        time.sleep(5)

        # Then we check all services status in 'SLAVE' env.
        result = {}
        for service in service_objs:
            result[service.name] = self._service_check(
                SYSTEMCTL_STATUS, service.name, node_obj.role, node_obj.type)
            LOG.info("Started Service %(name)s status checking: %(status)s",
                     {'name': service.name,
                      'status': result[service.name].upper()})

        for svc_name, res in result.items():
            if res != 0:
                LOG.error("%s is failed to start with return code %s" % (
                    svc_name, res))

    def _check_opp_master_is_good(self):
        oppo_nodes = self._get_the_oppo_nodes()
        all_result = 0
        for node in oppo_nodes:
            if node.status == 'down':
                all_result += 1
        if all_result > 0 or (all_result == 0 and len(oppo_nodes) < 2):
            return False
        return True

    def _check_and_process_orphan_master(self):
        orphans = []
        for zk_node in self.zk.list_nodes():
            if (zk_node.role == 'master' and
                    zk_node.status == 'down'):
                orphans.append(zk_node)

        for orphan in orphans:
            self.zk.update_node(orphan.name, role='slave')
            LOG.info("M/S switching: orphan node, %(role)s node %(name)s is "
                     "finishd from master to slave. And update it with "
                     "role=slave.",
                     {'role': orphan.role, 'name': orphan.name})

    def _script_load_pre_check(self, node_obj):
        if (node_obj.status == 'up' and node_obj.role == 'slave' and
                not self._check_opp_master_is_good()):
            # setup local services and check services status
            # at the end of process, we will set this node status to up and
            # role to MASTER
            self._setup_necessary_services_and_check(node_obj)
            self._change_dns()
            self.zk.update_node(node_obj.name, role='master', status='up')
            LOG.info("M/S switching: local node, %(role)s node %(name)s is "
                     "finishd from slave to master. And update it with "
                     "role=master and status=up.",
                     {'role': node_obj.role, 'name': node_obj.name})

        elif node_obj.status == 'down' and node_obj.role == 'master':
            # This is the first step when other master nodes, when check
            # self status is down, that means there must be 1 master node is
            # failed and hit the M/S switch. So what we gonna do is shuting down
            # local services and set self role from master to slave.
            self._shut_down_all_services(node_obj)
            self.zk.update_node(node_obj.name, role='slave')
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
            self._check_and_process_orphan_master()

    def _switch_process(self, node_obj):
        if node_obj.role == 'master':
            # Now, we must hit the services error, not host poweroff,
            # as the kp is alived, so we need to shut down all the necessary
            # and unecessary services.
            self._shut_down_all_services(node_obj)
            same_nodes = self._get_the_same_nodes()
            self.zk.update_node(node_obj.name, role='slave', status='down')
            LOG.info("M/S switching: local node, %(role)s node %(name)s is "
                     "finishd from master to slave. And update it with "
                     "role=slave and status=down.",
                     {'role': node_obj.role, 'name': node_obj.name})
            for node in same_nodes:
                self.zk.update_node(node.name, status='down')
                LOG.info("M/S switching: remote same node,"
                         "%(role)s node %(name)s begins from master to slave. "
                         "And update it with status=down.",
                         {'role': node.role, 'name': node.name})

    def _get_the_same_nodes(self):
        same_nodes = []
        for zk_node in self.zk.list_nodes():
            if (zk_node.role != self.node.role or
                    zk_node.name == self.node.name):
                continue
            elif zk_node.role in ['master', 'slave']:
                same_nodes.append(zk_node)

        return same_nodes

    def _get_the_oppo_nodes(self):
        oppo_nodes = []
        for zk_node in self.zk.list_nodes():
            if zk_node.role == self.node.role:
                continue
            elif (zk_node.role in ['master', 'slave'] and
                  zk_node.status != 'down'):
                oppo_nodes.append(zk_node)

        return oppo_nodes

    def _match_record(self, name, res):
        if res['name'] in ['logs-bak', 'test-logs-bak']:
            return (name == res['name'] and res['type'] == "A" and
                    TARGET_ORI_BK_IP == res['content'])
        return (name == res['name'] and
                res['type'] == "A" and TARGET_ORI_IP == res['content'])

    def _change_dns(self):
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
                account_id, DOMAIN_NAME,
                target_domain.split(DOMAIN_NAME)[0][:-1]),
                               headers=headers)
            if res.status_code != 200:
                LOG.error(
                    "Failed to get the records by name %s" % target_domain)
                LOG.error("Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
                return
            records = json.loads(s=res.content.decode('utf8'))['data']
            record_id = None
            for record in records:
                if self._match_record(target_domain.split(DOMAIN_NAME)[0][:-1],
                                record):
                    record_id = record['id']
                    target_dict[target_domain]['id'] = record_id
                    break
            if not record_id:
                LOG.error(
                    "Failed to get the record_id by name %s" % target_domain)
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
                    LOG.error(
                        "Details: code-status %s\n         message: %s" % (
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
                    LOG.error(
                        "Details: code-status %s\n         message: %s" % (
                            res.status_code, res.reason))
                    return
        LOG.info("Finish update DNS entry.")
    def _need_switch(self):
        pass
    def run(self):
        if self._need_switch():
            self._switch()
        self._local_node_service_process(self.node)


class HealthChecker(object):
    def __init__(self, config_file, heartbeat_timeout):
        cfg = configparser.ConfigParser().read(config_file)
        self.zk = zk.ZooKeeper(cfg)
        self.heartbeat_timeout = heartbeat_timeout

    def run(self):
        self.zk.connect()

        Refresher(self.zk, self.heartbeat_timeout).run()
        Fixer(self.zk, self.heartbeat_timeout).run()
        Switcher(self.zk, self.heartbeat_timeout).run()

        self.zk.disconnect()


if __name__ == '__main__':
    # ZK client config file
    conf = "{{ zk_cli_conf }}"
    # Heartbeat Internal timeout(seconds)
    heartbeat_timeout = {{heartbeat_internal}}

    HealthChecker(conf, heartbeat_timeout).run()
