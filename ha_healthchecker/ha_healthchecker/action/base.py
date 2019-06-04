import datetime
import socket
import subprocess

import iso8601
import six


class Action(object):
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
