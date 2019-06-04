import datetime
import subprocess

from github import Github

from ha_healthchecker.action import base


class Fixer(base.Action):
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
                    body += "systemctl restart %s\n" % s
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
                        "systemctl status %s\n" \
                        "journalctl -u %s\n" % (
                    node_obj.ip, affect_services.name,
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

