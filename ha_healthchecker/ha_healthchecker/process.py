#!/usr/bin/python3
import base64
import configparser
import datetime
import json
import logging
from logging import handlers
import socket
import subprocess
import time
import os

from apscheduler.schedulers import blocking
from github import Github
import iso8601
from html.parser import HTMLParser
from openlabcmd import zk
import requests
import six
from urllib import parse


# Simpledns provider
DOMAIN_NAME = 'openlabtesting.org'

# General constants
SYSTEMCTL_STATUS = 'status'
SYSTEMCTL_RESTART = 'restart'
SYSTEMCTL_STOP = 'stop'
SYSTEMCTL_START = 'start'

# Github app update
GLOBAL_SESSION = requests.session()
LOGIN_AUTH_TOKEN = None
APP_UPDATE_AUTH_TOKEN = None


class Base(object):
    def __init__(self, zk, cluster_config):
        self.zk = zk
        self.node = self.zk.get_node(socket.gethostname())
        self.oppo_node, self.zk_node = self._get_oppo_and_zk_node()
        self.cluster_config = cluster_config
        self.LOG = self.cluster_config.LOG

    def _get_oppo_and_zk_node(self):
        oppo_node = None
        zk_node = None
        for node in self.zk.list_nodes():
            if (node.type == self.node.type and
                    node.name != self.node.name):
                oppo_node = node
                continue
            if node.type == node.role:
                zk_node = node
                continue
        return oppo_node, zk_node

    def _is_check_heart_beat_overtime(self, node_obj):
        try:
            timeout = int(self.cluster_config.heartbeat_timeout_second)
            over_time = iso8601.parse_date(
                node_obj.heartbeat) + datetime.timedelta(seconds=timeout)
        except (iso8601.ParseError, TypeError, ValueError):
            # The heartbeat is not formatted, this must be the kp on the node
            # is not finish the first loop. We just return False, as we are in
            # the initializing process.
            raise Exception("heartbeat_timeout_second should be int-like "
                            "format.")
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def _ping(self, ipaddr):
        cli = ['ping', '-c1', '-w1', ipaddr]
        proc = subprocess.Popen(cli, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        proc.communicate()

        return proc.returncode == 0

    def _parse_isotime(self, timestr):
        try:
            return iso8601.parse_date(timestr)
        except iso8601.ParseError as e:
            raise ValueError(six.text_type(e))
        except TypeError as e:
            raise ValueError(six.text_type(e))

    def _is_alarmed_timeout(self, obj):
        if not obj.alarmed_at:
            return False
        try:
            timeout = int(
                self.cluster_config.unnecessary_service_switch_timeout_hour)
        except ValueError:
            raise Exception("unnecessary_service_switch_timeout_hour should be"
                            " int-like format.")
        over_time = self._parse_isotime(
            obj.alarmed_at) + datetime.timedelta(hours=timeout)
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def _get_service_status(self, service):
        # timer tasks are handled by crontab
        if service in ['zuul-timer-tasks', 'nodepool-timer-tasks']:
            service = 'cron'

        cmd = "systemctl status {srvc}".format(srvc=service)
        try:
            # 0 means OK
            # if using status command, 0 means active, non-zero means error
            # status.
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            self.LOG.debug("Service %(name)s runs well.",
                                          {'name': service})
            return 'up'
        except subprocess.CalledProcessError as e:
            self.LOG.error("Service %(name)s runs error: %(err)s %(out)s.",
                           {'name': service, 'err': e, 'out': e.output})
            return 'down'


class Refresher(Base):
    def __init__(self, zk, cluster_config):
        super(Refresher, self).__init__(zk, cluster_config)

    def _local_node_service_process(self, node_obj):
        service_objs = self.zk.list_services(node_name_filter=node_obj.name)
        for service_obj in service_objs:
            self._refresh_service(service_obj, node_obj)

        self._report_heart_beat(node_obj)

    def _refresh_service(self, service_obj, node_obj):
        cur_status = self._get_service_status(service_obj.name)
        update_dict = {}
        if cur_status == 'up':
            if service_obj.status != 'up':
                update_dict['status'] = 'up'
                update_dict['restarted'] = False
                update_dict['alarmed'] = False
                self.LOG.debug("Fix Service %(name)s status from %(orig)s to "
                               "UP.", {'name': service_obj.name,
                                       'orig': service_obj.status})
        else:
            if not service_obj.restarted:
                update_dict['status'] = 'restarting'
                update_dict['restarted'] = True
                self.LOG.debug("Service %(name)s is Restarting.",
                               {'name': service_obj.name})
            else:
                update_dict['status'] = 'down'
                self.LOG.debug("Service %(name)s is Down.",
                               {'name': service_obj.name})
        if update_dict:
            self.zk.update_service(service_obj.name, node_obj.name,
                                   **update_dict)

    def _need_fix_alarmed_status(self, node):
        if not node.alarmed:
            return False

        if node.role == 'slave':
            return True

        for service in self.zk.list_services(node_name_filter=node.name):
            if service.is_necessary:
                continue
            if service.alarmed and self._is_alarmed_timeout(service):
                return False

        return True

    def _report_heart_beat(self, node_obj):
        hb = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        update_dict = {'heartbeat': hb}
        if node_obj.status == 'initializing' or node_obj.status == 'down':
            update_dict['status'] = 'up'
        if self._need_fix_alarmed_status(node_obj):
            update_dict['alarmed'] = False
        self.zk.update_node(node_obj.name, **update_dict)
        self.LOG.debug("Report node %(name)s heartbeat %(hb)s",
                       {'name': node_obj.name, 'hb': hb})

    def _other_node_check(self, other_node_obj):
        if other_node_obj.status == 'maintaining':
            return
        if (not self._ping(other_node_obj.ip) and
                self._is_check_heart_beat_overtime(other_node_obj)):
            if other_node_obj.status == 'up':
                self.zk.update_node(other_node_obj.name, status='down')
                self.LOG.info("%(role)s node %(name)s can not reach, updated "
                              "with %(status)s status.",
                              {'role': other_node_obj.role,
                               'name': other_node_obj.name,
                               'status': 'down'.upper()})

    def run(self):
        if self.node.status == 'maintaining':
            self.LOG.debug(
                'Node %(name)s status is MAINTAINING, Skipping refresh.',
                {'name': self.node.name})
            return
        self._local_node_service_process(self.node)
        if self.oppo_node:
            self._other_node_check(self.oppo_node)

        if self.zk_node:
            self._other_node_check(self.zk_node)


class Fixer(Base):
    def __init__(self, zk, cluster_config):
        super(Fixer, self).__init__(zk, cluster_config)

    def _post_alarmed(self, obj):
        if not obj.alarmed:
            if 'node' in obj.__class__.__name__.lower():
                self.zk.update_node(obj.name, alarmed=True)
                self.LOG.info("%(role)s Node %(name)s updated with "
                              "alarmed=True", {'name': obj.name,
                                               'role': obj.role})
            elif 'service' in obj.__class__.__name__.lower():
                self.zk.update_service(obj.name, self.node.name, alarmed=True)
                self.LOG.info("Service %(name)s updated with alarmed=True",
                              {'name': obj.name})

    def _service_restart(self, service):
        cmd = "systemctl restart {srvc}".format(srvc=service)
        try:
            # 0 means OK
            # if using status command, 0 means active, non-zero means error
            # status.
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            self.LOG.info("Service %(name)s restarted success.",
                          {'name': service})
        except subprocess.CalledProcessError as e:
            self.LOG.error("Service %(name)s restarted failed.: %(err)s "
                           "%(out)s", {'name': service, 'err': e,
                                       'out': e.output})

    def _fix_service(self, service_obj):
        if service_obj.status == 'restarting':
            if service_obj.name in ['zuul-timer-tasks','nodepool-timer-tasks']:
                service_name = 'cron'
            else:
                service_name = service_obj.name
            self._service_restart(service_name)
        elif service_obj.status == 'down':
            if not service_obj.alarmed:
                if service_obj.is_necessary:
                    self._notify_issue(self.node, self.node,
                                       affect_services=service_obj,
                                       affect_range='node',
                                       more_specific='necessary_error')
                    self._post_alarmed(self.node)

                else:
                    self._notify_issue(self.node, self.node,
                                       affect_services=service_obj,
                                       affect_range='service',
                                       more_specific='unecessary_svc')
                self.zk.update_service(service_obj.name, self.node.name,
                                       alarmed=True)
                self._post_alarmed(service_obj)
            else:
                if not service_obj.is_necessary and self._is_alarmed_timeout(
                        service_obj):
                    if self.node.role == 'master' and not self.node.alarmed:
                        self._notify_issue(self.node, self.node,
                                           affect_range='node',
                                           more_specific='slave_switch')
                        self._post_alarmed(self.node)

    def _local_node_service_process(self):
        service_objs = self.zk.list_services(node_name_filter=self.node.name)
        for service_obj in service_objs:
            self._fix_service(service_obj)

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
            if more_specific == 'other_check':
                body += "The target node %(name)s in %(role)s deployment is " \
                        "failed to be accessed with IP %(ip)s or fetching its " \
                        "heartbeat.\n" % (
                            {'name': node_obj.name,
                             'role': node_obj.role,
                             'ip': node_obj.ip})
                title += "%s check %s failed, " % (
                    issuer_node.role, node_obj.role)
                if node_obj.role == 'master':
                    body += "HA tools already switch to slave deployment, " \
                            "please try a simple job to check whether " \
                            "everything is OK.\n"
                    title += "HA Switch Going."
                else:
                    title += "need to recover manually."
                body += "\nSuggestion:\n" \
                        "===============\n" \
                        "ssh ubuntu@%s\n" % node_obj.ip
                body += "And try to login the cloud to check whether the " \
                        "resource exists.\n"
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
                body += "Please check original master deployment " \
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
            elif more_specific == 'healthchecker_error':
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
        g = Github(login_or_token=self.cluster_config.github_user_token)
        repo = g.get_repo(self.cluster_config.github_repo)
        repo.create_issue(
            title=title % (
                datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            body=body)
        self.LOG.info("Post a Issue for %(title)s with reason %(reason)s.",
                      {'title': title % (
                          datetime.datetime.utcnow().strftime(
                              "%Y-%m-%d %H:%M:%S")), 'reason': more_specific})

    def _other_node_check(self, other_node_obj):
        if other_node_obj.status == 'maintaining':
            return
        if (self._ping(other_node_obj.ip) and
                self._is_check_heart_beat_overtime(other_node_obj)):
            if not other_node_obj.alarmed:
                self._notify_issue(self.node, other_node_obj,
                                   affect_range='node',
                                   more_specific='healthchecker_error')
                self._post_alarmed(other_node_obj)
        elif (not self._ping(other_node_obj.ip) and
              self._is_check_heart_beat_overtime(other_node_obj)):
            if other_node_obj.status == 'down':
                if not other_node_obj.alarmed:
                    self._notify_issue(self.node, other_node_obj,
                                       affect_range='node',
                                       more_specific='other_check')
                    self._post_alarmed(other_node_obj)

    def run(self):
        if self.node.status == 'maintaining':
            self.LOG.debug(
                'Node %(name)s status is MAINTAINING, Skipping fix.',
                {'name': self.node.name})
            return
        self._local_node_service_process()

        if self.oppo_node:
            self._other_node_check(self.oppo_node)

        if self.zk_node:
            self._other_node_check(self.zk_node)


class Switcher(Base):
    def __init__(self, zk, cluster_config):
        super(Switcher, self).__init__(zk, cluster_config)

    def _is_need_switch(self):
        all_nodes = self.zk.list_nodes()
        for node in all_nodes:
            if node.status == 'maintaining':
                self.LOG.debug(
                    'Node %(name)s status is MAINTAINING, Skipping switch.',
                    {'name': node.name})
                return False

            if node.role == 'slave' and node.status == 'down':
                self.LOG.info("Global checking: there is a slave node "
                              "%(name)s in DOWN state, can not do switch. "
                              "Skipping..", {'name': node.name})
                return False

            if node.role == 'master':
                if node.status == 'down':
                    self.LOG.info("Global checking: Found %(role)s node "
                                  "%(name)s is in %(status)s. ",
                                  {'name': node.name,
                                   'role': node.role,
                                   'status': 'down'.upper()})
                    return True
                node_services = self.zk.list_services(
                    node_name_filter=node.name)
                err_services = [e for e in node_services if e.status == 'down']
                # Service analysis
                for err_svc in err_services:
                    if err_svc.is_necessary:
                        self.LOG.info(
                            "Global checking: Found a necessary service "
                            "%(service_name)s is in %(service_status)s "
                            "status on %(role)s node %(name)s. ", {
                                'service_name': err_svc.name,
                                'service_status': err_svc.status.upper(),
                                'name': node.name, 'role': node.role})
                        return True
                    elif (not err_svc.is_necessary and
                          self._is_alarmed_timeout(err_svc)):
                        self.LOG.info(
                            "Global checking: Found a necessary service "
                            "%(service_name)s is in %(service_status)s "
                            "status on %(role)s node %(name)s. ", {
                                'service_name': err_svc.name,
                                'service_status': err_svc.status.upper(),
                                'name': node.name, 'role': node.role})
                        return True
        return False

    def _set_switch_status(self):
        if not self.node.switch_status:
            self.zk.update_node(self.node.name, switch_status='start')
            self.node.switch_status = 'start'
            self.LOG.info("Global checking result: setting switch_status "
                          "%(status)s.", {'status': 'start'.upper()})

        if self.node.role == 'slave' and (not self._ping(self.oppo_node.ip) and
                 self._is_check_heart_beat_overtime(self.oppo_node)):
            self.zk.update_node(self.oppo_node.name,
                                switch_status='start')
            self.oppo_node.switch_status = 'start'
            self.LOG.info(
                "Global checking result: setting switch_status "
                "%(status)s and role=slave on OPPO %(role)s "
                "node %(name)s.",
                {'status': 'start'.upper(),
                 'role': self.oppo_node.role,
                 'name': self.oppo_node.name})

    def _run_systemctl_command(self, command, service):
        cmd = "systemctl {cmd} {srvc}".format(cmd=command, srvc=service)
        try:
            # 0 means OK
            # if using status command, 0 means active, non-zero means error status.
            subprocess.check_output(cmd.split(), stderr=subprocess.STDOUT)
            self.LOG.debug("Run CMD: %(cmd)s", {'cmd': cmd})
            if command == SYSTEMCTL_STATUS:
                return 'up'
        except subprocess.CalledProcessError as e:
            self.LOG.error("Failed to %(cmd)s %(srvc)s service: %(err)s "
                           "%(out)s", {'cmd': command, 'srvc': service,
                                       'err': e, 'out': e.output})
            if command == SYSTEMCTL_STATUS:
                return 'down'

    def _shut_down_all_services(self, node_obj, force_switch):
        service_objs = self.zk.list_services(
            node_name_filter=node_obj.name)
        exclude_service = ['zuul-timer-tasks', 'nodepool-timer-tasks']
        if force_switch:
            exclude_service.append('zookeeper')
        for service in service_objs:
            if service.name not in exclude_service:
                self._run_systemctl_command(SYSTEMCTL_STOP, service.name)

    def _setup_necessary_services_and_check(self, node_obj):
        service_objs = self.zk.list_services(
            node_name_filter=node_obj.name)
        for service in service_objs:
            if service.name not in ['zuul-timer-tasks',
                                    'nodepool-timer-tasks']:
                self._run_systemctl_command(SYSTEMCTL_START, service)
                self.LOG.info("Start Service %(name)s.",
                              {'name': service.name})

        # local deplay 5 seconds
        time.sleep(5)

        # Then we check all services status in 'SLAVE' env.
        result = {}
        for service in service_objs:
            result[service.name] = self._get_service_status(service.name)

        for svc_name, res in result.items():
            if res != 0:
                self.LOG.error(
                    "%s is failed to start with return code %s" % (
                        svc_name, res))

    def _match_record(self, name, res):
        return (name == res['name'] and
                res['type'] == "A" and
                self.cluster_config.dns_master_public_ip == res['content'])

    def _get_login_page_authenticity_token(self):
        login_page = GLOBAL_SESSION.get('https://github.com/login')
        login_page_content = login_page.content.decode('utf-8')

        login_page_parser = LoginHTMLParser()
        login_page_parser.feed(login_page_content)
        login_page_parser.close()
        quoted_authenticity_token = parse.quote(LOGIN_AUTH_TOKEN)
        return quoted_authenticity_token

    def _get_github_app_page_authenticity_token(self, app_url, app_name):
        app_page = GLOBAL_SESSION.get(app_url)
        if app_page.status_code == 404:
            self.LOG.error("Not Found Github App: %s" % app_name)
            return
        app_page_content = app_page.content.decode('utf-8')

        app_page_parser = AppUpdateHTMLParser()
        app_page_parser.feed(app_page_content)

        quoted_authenticity_token = parse.quote(APP_UPDATE_AUTH_TOKEN)
        return quoted_authenticity_token

    def _update_github_app_webhook(self):
        login_token = self._get_login_page_authenticity_token()
        login_info = ('authenticity_token=%(token)s&login=%(username)s&'
                      'password=%(password)s' % {
            'token': login_token,
            'username': self.cluster_config.github_user_name,
            'password': self.cluster_config.github_user_password})
        login_response = GLOBAL_SESSION.post(
            'https://github.com/session',
            data=login_info,
        )
        if (login_response.status_code == 200 and
                GLOBAL_SESSION.cookies._cookies['.github.com']['/'][
                    'logged_in'].value == 'yes'):
            self.LOG.info("Github app change: Success Login")
        else:
            self.LOG.error("Github app change: Fail Login")
            return

        app_url = 'https://github.com/settings/apps/%s' % self.cluster_config.github_app_name
        github_app_edit_token = self._get_github_app_page_authenticity_token(
            app_url,
            self.cluster_config.github_app_name)
        if not github_app_edit_token:
            return
        update_response = GLOBAL_SESSION.post(
            app_url,
            data="_method=put&authenticity_token=" +
                 github_app_edit_token +
                 "&integration%5Bhook_attributes%5D%5Burl%5D=http%3A%2F%2F" +
                 self.cluster_config.dns_slave_public_ip + "%3A" + '80' +
                 "%2Fapi%2Fconnection%2Fgithub%2Fpayload"
        )
        if update_response.status_code == 200:
            self.LOG.info(
                "Success Update Github APP: %s" % self.cluster_config.github_app_name)
        else:
            self.LOG.error(
                "Fail Update Github APP: %s" % self.cluster_config.github_app_name)

    def _change_dns_and_github_app_webhook(self):
        self._change_dns()
        self._update_github_app_webhook()

    def _change_dns(self):
        headers = {'Authorization': "Bearer %s" % self.cluster_config.dns_provider_token,
                   'Accept': 'application/json'}
        res = requests.get(self.cluster_config.dns_provider_api_url + 'accounts',
                           headers=headers)
        if res.status_code != 200:
            self.LOG.error("Failed to get the accounts")
            self.LOG.error(
                "Details: code-status %s\n         message: %s" % (
                    res.status_code, res.reason))
            return
        accounts = json.loads(s=res.content.decode('utf8'))['data']
        account_id = None
        for account in accounts:
            if account['id'] == self.cluster_config.dns_provider_account:
                account_id = account['id']
                break
        if not account_id:
            self.LOG.error("Failed to get the account_id")
            return

        target_dict = {self.cluster_config.dns_status_domain: {},
                       self.cluster_config.dns_log_domain: {}}
        for target_domain in target_dict.keys():
            res = requests.get(
                self.cluster_config.dns_provider_api_url + "%s/zones/%s/records?name=%s" % (
                account_id, DOMAIN_NAME,
                target_domain.split(DOMAIN_NAME)[0][:-1]),
                               headers=headers)
            if res.status_code != 200:
                self.LOG.error(
                    "Failed to get the records by name %s" % target_domain)
                self.LOG.error(
                    "Details: code-status %s\n         message: %s" % (
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
                self.LOG.error(
                    "Failed to get the record_id by name %s" % target_domain)
                return

        if not any(target_dict.values()):
            self.LOG.error("Can't not get any records.")
            return

        headers['Content-Type'] = 'application/json'
        data = {
            "content": self.cluster_config.dns_slave_public_ip
        }
        for target_domain in target_dict.keys():
            res = requests.patch(
                self.cluster_config.dns_provider_api_url + "%s/zones/%s/records/%s" % (
                    account_id, DOMAIN_NAME, target_dict[target_domain]['id']),
                data=data, headers=headers)
            result = json.loads(s=res.content.decode('utf8'))['data']
            if (res.status_code == 200 and
                    result['content'] == self.cluster_config.dns_slave_public_ip):
                self.LOG.info(
                    "Success Update -- Domain %s from %s to %s" % (
                        target_domain, self.cluster_config.dns_master_public_ip,
                        self.cluster_config.dns_slave_public_ip))
            else:
                self.LOG.error(
                    "Fail Update -- Domain %s from %s to %s" % (
                        target_domain, self.cluster_config.dns_master_public_ip,
                        self.cluster_config.dns_slave_public_ip))
                self.LOG.error(
                    "Details: code-status %s\n         message: %s" % (
                        res.status_code, res.reason))
                return
        self.zk.update_configuration('dns_master_public_ip',
                                     self.cluster_config.dns_slave_public_ip)
        self.zk.update_configuration('dns_slave_public_ip',
                                     self.cluster_config.dns_master_public_ip)
        self.LOG.info("Finish update DNS entry.")

    def _do_switch(self, force_switch=False):
        if self.node.role == 'master':
            self._shut_down_all_services(self.node, force_switch)
            update_dict = {'role': 'slave', 'switch_status': 'end'}
            self.zk.update_node(self.node.name, **update_dict)
            self.node.switch_status = 'end'
            self.LOG.info(
                "M/S switching: local node, %(role)s node %(name)s is "
                "finishd from master to slave. And update it with "
                "role=slave%(ext_msg)s.",
                {'role': self.node.role, 'name': self.node.name,
                 'ext_msg': ' and status=down' if not force_switch else ''})

        elif self.node.role == 'slave':
            if self.node.type == 'zuul':
                self._change_dns_and_github_app_webhook()
            self.zk.update_node(self.node.name, role='master',
                                switch_status='end')
            self.node.switch_status = 'end'
            self._setup_necessary_services_and_check(self.node)
            self.LOG.info(
                "M/S switching: local node, %(role)s node %(name)s is "
                "finishd from slave to master. And update it with "
                "role=master and switch_status=end.",
                {'role': self.node.role, 'name': self.node.name})
            if (not self._ping(self.oppo_node.ip)
                    and self._is_check_heart_beat_overtime(self.oppo_node)):
                self.zk.update_node(self.oppo_node.name, role='slave',
                                    switch_status='end')
                self.oppo_node.switch_status = 'end'
                self.LOG.info(
                    "Global checking result: setting switch_status "
                    "%(status)s and role=slave on OPPO %(role)s "
                    "node %(name)s.",
                    {'status': 'end'.upper(),
                     'role': self.oppo_node.role,
                     'name': self.oppo_node.name})

    def _can_start_switch(self):
        if self.node.switch_status == 'end':
            return False

        res = []
        for zk_node in self.zk.list_nodes(with_zk=False):
            res.append(zk_node.switch_status)

        if len(set(res)) == 1 and 'start' in set(res):
            # All status is 'start'
            return True

        if len(set(res)) == 2 and 'start' in set(res) and 'end' in set(res):
            # Status contains only 'start' and 'end', no 'None'.
            return True

        return  False

    def _not_switching(self):
        res = []
        for zk_node in self.zk.list_nodes(with_zk=False):
            res.append(zk_node.switch_status)

        if len(set(res)) == 1 and None in set(res):
            # All status is 'None'
            return True

        if len(set(res)) == 2 and 'start' in set(res) and None in set(res):
            # Status contains only 'start' and 'None', no 'end'.
            return True

        return  False

    def _is_end(self):
        for node in self.zk.list_nodes(with_zk=False):
            if node.switch_status == 'start':
                return False
        return True

    def run(self):
        if not self.cluster_config.allow_switch:
            return

        if self.node.type == 'zookeeper':
            # zookeeper node don't need master/slave switch
            return

        is_force_switch = True
        if not self.node.switch_status and self._not_switching():
            if self._is_need_switch():
                self._set_switch_status()
                is_force_switch = False

        if self._can_start_switch():
            self._do_switch(force_switch=is_force_switch)

        if self._is_end():
            if self.node.switch_status == 'end':
                self.zk.update_node(self.node.name, switch_status=None)
            if self.oppo_node.switch_status == 'end':
                if (not self._ping(self.oppo_node.ip)
                        and self._is_check_heart_beat_overtime(
                            self.oppo_node)):
                    self.zk.update_node(self.oppo_node.name,
                                        switch_status=None)
                    self.LOG.info(
                        "Global checking result: setting back switch_status "
                        "from %(status)s to None on %(role)s node %(name)s.",
                        {'status': 'start'.upper(),
                         'role': self.node.role,
                         'name': self.node.name})


class LoginHTMLParser(HTMLParser):
    def handle_startendtag(self, tag, attrs):
        global LOGIN_AUTH_TOKEN
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            for key, value in attrs:
                if key == 'value':
                    LOGIN_AUTH_TOKEN = value


class AppUpdateHTMLParser(HTMLParser):
    token_index = 1

    def handle_startendtag(self, tag, attrs):
        global APP_UPDATE_AUTH_TOKEN
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            if self.token_index == 6:
                for key, value in attrs:
                    if key == 'value':
                        APP_UPDATE_AUTH_TOKEN = value
                self.token_index += 1
            else:
                self.token_index += 1


class ClusterConfig(object):
    BASE64_ENCODED_OPTIONS = ['github_user_password', 'dns_provider_token',
                              'github_user_token']

    def __init__(self, zk_client):
        self._init_options(zk_client)
        self._set_log()

    def _init_options(self, zk_client):
        for attr, value in zk_client.list_configuration().items():
            if value is None:
                raise Exception("Openlab HA related options haven't been "
                                "initialized, try 'openlab ha config list'"
                                " to get more detail.")
            if attr in self.BASE64_ENCODED_OPTIONS:
                value = base64.b64decode(value).decode("utf-8").split('\n')[0]
            setattr(self, attr, value)

    def _set_log(self):
        file_dir = os.path.split(self.logging_path)[0]
        if not os.path.isdir(file_dir):
            os.makedirs(file_dir)
        if not os.path.exists(self.logging_path):
            os.system('touch %s' % self.logging_path)
        if not self.logging_level.upper() in ['DEBUG', 'INFO', 'ERROR']:
            # use the default level
            self.logging_level = 'DEBUG'
        Rthandler = handlers.RotatingFileHandler(
            self.logging_path, maxBytes=10*1024*1024, backupCount=5)
        logging.basicConfig(
            format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
            datefmt='%H:%M:%S',
            level=getattr(logging, self.logging_level.upper()),
            handlers=[Rthandler])
        self.LOG = logging.getLogger("OpenLab HA HealthChecker")

    def refresh(self, zk_client):
        for attr, value in zk_client.list_configuration().items():
            if attr in self.BASE64_ENCODED_OPTIONS:
                value = base64.b64decode(value).decode("utf-8").split('\n')[0]
            setattr(self, attr, value)
        self._set_log()


class HealthChecker(object):
    def __init__(self, config_file):
        zk_cfg = configparser.ConfigParser()
        zk_cfg.read(config_file)
        self.zk_client = zk.ZooKeeper(zk_cfg)
        self.cluster_config = None

    def _action(self):
        if self.zk_client.client is None:
            self.zk_client.connect()
        self.cluster_config.refresh(self.zk_client)
        Refresher(self.zk_client, self.cluster_config).run()
        Fixer(self.zk_client, self.cluster_config).run()
        Switcher(self.zk_client, self.cluster_config).run()
        self.zk_client.disconnect()

    def run(self):
        self.zk_client.connect()
        self.cluster_config = ClusterConfig(self.zk_client)

        job_scheduler = blocking.BlockingScheduler()
        job_scheduler.add_job(self._action, 'interval', seconds=120)
        job_scheduler.start()
