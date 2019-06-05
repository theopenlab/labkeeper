import datetime
import subprocess

from ha_healthchecker.action import base


class Fixer(base.Action):
    def __init__(self, zk, cluster_config, github):
        super(Fixer, self).__init__(zk, cluster_config)
        self.github = github

    def _set_alarmed(self, obj, is_service):
        if not obj.alarmed:
            if is_service:
                self.zk.update_service(obj.name, self.node.name, alarmed=True)
                self.LOG.info("Service %(name)s updated with alarmed=True",
                              {'name': obj.name})
            else:
                self.zk.update_node(obj.name, alarmed=True)
                self.LOG.info("%(role)s Node %(name)s updated with "
                              "alarmed=True", {'name': obj.name,
                                               'role': obj.role})

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
                self.github.create_issue(self.node, 'service_down',
                                         affect_node=self.node,
                                         affect_services=service_obj)
                self._set_alarmed(service_obj, is_service=True)
            elif not service_obj.is_necessary and self._is_alarmed_timeout(
                        service_obj):
                self.github.create_issue(self.node, 'service_timeout',
                                         affect_node=self.node,
                                         affect_services=service_obj)

    def _local_node_service_process(self):
        service_objs = self.zk.list_services(node_name_filter=self.node.name)
        for service_obj in service_objs:
            self._fix_service(service_obj)

    def _other_node_check(self, other_node_obj):
        if other_node_obj.status == 'maintaining':
            return
        if (self._ping(other_node_obj.ip) and
                self._is_check_heart_beat_overtime(other_node_obj)):
            if not other_node_obj.alarmed:
                self.github.create_issue(self.node, 'healthchecker_error',
                                         affect_node=other_node_obj)
                self.LOG.info("Posted an Issue to GitHub.")
                self._set_alarmed(other_node_obj, is_service=False)
        elif (not self._ping(other_node_obj.ip) and
              self._is_check_heart_beat_overtime(other_node_obj)):
            if other_node_obj.status == 'down':
                if not other_node_obj.alarmed:
                    self.github.create_issue(self.node, 'other_node_down',
                                             affect_node=other_node_obj)
                    self._set_alarmed(other_node_obj, is_service=False)

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

