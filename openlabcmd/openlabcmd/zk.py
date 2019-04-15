import configparser
import datetime
import json
import logging
import time

from kazoo.client import KazooClient, KazooState
from kazoo import exceptions as kze
from kazoo.handlers.threading import KazooTimeoutError

from openlabcmd import exceptions
from openlabcmd import node
from openlabcmd import service


class ZooKeeper(object):

    log = logging.getLogger("OpenLabCMD.ZooKeeper")

    # Log zookeeper retry every 10 seconds
    retry_log_rate = 10

    def __init__(self, config=None):
        """
        Zookeeper Client for OpenLab HA management.

        :param config: The config object.
        :type: configparser.ConfigParser.
        """
        self.client = None
        self.config = config
        if self.config and not isinstance(self.config,
                                          configparser.ConfigParser):
            raise exceptions.ClientError("config should be a ConfigParser "
                                         "object.")
        self._last_retry_log = 0

    def _bytesToDict(self, data):
        return json.loads(data.decode('utf8'))

    def _connection_listener(self, state):
        if state == KazooState.LOST:
            self.log.debug("ZooKeeper connection: LOST")
        elif state == KazooState.SUSPENDED:
            self.log.debug("ZooKeeper connection: SUSPENDED")
        else:
            self.log.debug("ZooKeeper connection: CONNECTED")

    def logConnectionRetryEvent(self):
        now = time.monotonic()
        if now - self._last_retry_log >= self.retry_log_rate:
            self.log.warning("Retrying zookeeper connection")
            self._last_retry_log = now

    @property
    def connected(self):
        if self.client is None:
            return False
        return self.client.state == KazooState.CONNECTED

    @property
    def suspended(self):
        if self.client is None:
            return True
        return self.client.state == KazooState.SUSPENDED

    @property
    def lost(self):
        if self.client is None:
            return True
        return self.client.state == KazooState.LOST

    def connect(self, hosts=None, read_only=False):
        if not hosts:
            if not self.config:
                raise exceptions.ClientError('Either config object or hosts '
                                             'string should be provided.')
            else:
                try:
                    hosts = self.config.get('ha', 'zookeeper_hosts')
                except configparser.NoOptionError:
                    raise exceptions.ClientError(
                        "The config doesn't [ha]zookeeper_hosts option.")
        if self.client is None:
            self.client = KazooClient(hosts=hosts, read_only=read_only)
            self.client.add_listener(self._connection_listener)
            # Manually retry initial connection attempt
            while True:
                try:
                    self.client.start(1)
                    break
                except KazooTimeoutError:
                    self.logConnectionRetryEvent()

    def disconnect(self):
        if self.client is not None and self.client.connected:
            self.client.stop()
            self.client.close()
            self.client = None

    def _client_check_wrapper(func):
        def wrapper(self, *args, **kwargs):
            if not self.client:
                raise exceptions.ClientError(
                    "Should call connect function first to initialise "
                    "zookeeper client")
            return func(self, *args, **kwargs)
        return wrapper

    @_client_check_wrapper
    def list_nodes(self):
        path = '/ha'
        try:
            nodes = []
            for exist_node in self.client.get_children(path):
                node_info = self.get_node(exist_node)
                nodes.append(node_info)
        except kze.NoNodeError:
            return []
        return sorted(nodes)

    @_client_check_wrapper
    def get_node(self, node_name):
        try:
            node_info = self.client.get('/ha/%s' % node_name)
            # ctime and mtime is millisecond in zk.
            ctime, mtime = node_info[1].ctime, node_info[1].mtime
            node_info = self._bytesToDict(node_info[0])
            node_info['created_at'] = datetime.datetime.fromtimestamp(
                ctime/1000).isoformat()
            node_info['updated_at'] = datetime.datetime.fromtimestamp(
                mtime/1000).isoformat()
            return node_info
        except kze.NoNodeError:
            raise exceptions.ClientError('Node %s not found.' % node_name)

    @_client_check_wrapper
    def create_node(self, name, role, type, ip):
        path = '/ha/%s' % name
        new_node = node.Node(name, role, type, ip)
        try:
            # TODO(wxy): Add unique check.
            self.client.create(path,
                               value=new_node.to_zk_data(),
                               makepath=True)
        except kze.NodeExistsError:
            raise exceptions.ClientError("The node %s is already existed."
                                         % name)

        master_service_path = path + '/master_service'
        slave_service_path = path + '/slave_service'
        zookeeper_service_path = path + '/zookeeper_service'

        self.client.create(master_service_path)
        self.client.create(slave_service_path)
        self.client.create(zookeeper_service_path)

        for node_role, node_services in service.service_mapping.items():
            new_service_path = path + '/%s' % node_role
            for service_type, service_names in node_services.items():
                service_class = (service.NecessaryService if
                                 service_type == 'necessary' else
                                 service.UnnecessaryService)
                for service_name in service_names:
                    new_service = service_class(service_name, role)
                    self.client.create(
                        new_service_path + '/%s' % service_name,
                        value=new_service.to_zk_data())

        node_info = self.get_node(name)
        return node_info

    @_client_check_wrapper
    def update_node(self, node_name, maintain=None, role=None, **kwargs):
        path = '/ha/%s' % node_name
        node_info = self.get_node(node_name)
        if maintain is not None:
            if maintain:
                if node_info['status'] == node.NodeStatus.UP:
                    node_info['status'] = node.NodeStatus.MAINTAINING
                else:
                    raise exceptions.ClientError(
                        "The node must be in 'up' status when trying to "
                        "maintain it.")
            else:
                if node_info['status'] == node.NodeStatus.MAINTAINING:
                    node_info['status'] = node.NodeStatus.UP
                else:
                    raise exceptions.ClientError(
                        "The node must be in 'maintaining' status when trying "
                        "to un-maintain it.")
        if role:
            node_info['role'] = role

        node_info.update(kwargs)
        new_node = node.Node.from_dict(**node_info)
        self.client.set(path, value=new_node.to_zk_data())

        node_info = self.get_node(node_name)
        return node_info

    @_client_check_wrapper
    def delete_node(self, node_name):
        self.get_node(node_name)
        path = '/ha/%s' % node_name
        self.client.delete(path, recursive=True)

    @_client_check_wrapper
    def list_services(self):
        result = []
        for exist_node in self.list_nodes():
            path = '/ha/%s/%s_service' % (exist_node['name'],
                                          exist_node['role'])
            for service_name in self.client.get_children(path):
                service_path = path + '/' + service_name
                service_info = self.client.get(service_path)
                service_info = self._bytesToDict(service_info[0])
                result.append(service_info)
        return sorted(result)

    @_client_check_wrapper
    def get_service(self, service_name, role=None):
        if not role:
            if (service_name in
                    service.service_mapping['master_service']['necessary'] +
                    service.service_mapping['master_service']['unnecessary']):
                role = 'master'
            elif (service_name in
                  service.service_mapping['slave_service']['necessary'] +
                  service.service_mapping['slave_service']['unnecessary']):
                role = 'slave'
            else:
                exceptions.ClientError("Can't find service %s" % service_name)

        for exist_node in self.list_nodes():
            if exist_node['role'] == role:
                path = '/ha/%s/%s_service/%s' % (exist_node['name'], role,
                                                 service_name)
                result = self.client.get(path)
                result = self._bytesToDict(result[0])
                return result
        raise exceptions.ClientError("Can't find service %s" % service_name)
