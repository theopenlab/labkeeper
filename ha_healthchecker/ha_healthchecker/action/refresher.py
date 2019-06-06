import datetime

from ha_healthchecker.action import base


class Refresher(base.Action):
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
            if (service_obj.status != 'up' and
                    service_obj.restarted_count <
                    self.cluster_config.service_count_allow_to_raise):
                update_dict['status'] = 'up'
                update_dict['restarted'] = False
                update_dict['alarmed'] = False
                update_dict['restarted_account'] = 0
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
                if (service_obj.restarted_count >
                        self.cluster_config.service_count_allow_to_raise):
                    update_dict['status'] = 'down'
                    self.LOG.debug("Service %(name)s is Down.",
                                   {'name': service_obj.name})
                else:
                    update_dict[
                        'restarted_account'] = service_obj.restarted_count + 1
                    self.LOG.debug("Service %(name)s continue in Restarting, "
                                   "tried %(count)s times",
                                   {'name': service_obj.name,
                                    'count': service_obj.restarted_count})
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
