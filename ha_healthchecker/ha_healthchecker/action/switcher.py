import json
import subprocess
import time

import requests

from ha_healthchecker.action import base

# Simpledns provider
DOMAIN_NAME = 'openlabtesting.org'


class Switcher(base.Action):
    def __init__(self, zk, cluster_config, github):
        super(Switcher, self).__init__(zk, cluster_config)
        self.github = github

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
            if command == 'status':
                return 'up'
        except subprocess.CalledProcessError as e:
            self.LOG.error("Failed to %(cmd)s %(srvc)s service: %(err)s "
                           "%(out)s", {'cmd': command, 'srvc': service,
                                       'err': e, 'out': e.output})
            if command == 'status':
                return 'down'

    def _shut_down_all_services(self, node_obj, force_switch):
        service_objs = self.zk.list_services(
            node_name_filter=node_obj.name)
        exclude_service = ['zuul-timer-tasks', 'nodepool-timer-tasks']
        if force_switch:
            exclude_service.append('zookeeper')
        for service in service_objs:
            if service.name not in exclude_service:
                self._run_systemctl_command('stop', service.name)

    def _setup_necessary_services_and_check(self, node_obj):
        service_objs = self.zk.list_services(
            node_name_filter=node_obj.name)
        for service in service_objs:
            if service.name not in ['zuul-timer-tasks',
                                    'nodepool-timer-tasks']:
                self._run_systemctl_command('start', service)
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

    def _change_dns_and_github_app_webhook(self):
        self._change_dns()
        self.github.update_github_app_webhook()

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
                if not force_switch:
                    self.github.create_issue(self.node, 'switch')
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

        return False

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

        return False

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
