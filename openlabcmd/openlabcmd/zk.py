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

    def _bytesToDict(self, node_data, include_created_at=False,
                     include_updated_at=False):
        """ Convert zookeeper node data into dict."""
        node_dict = node_data[0]
        # ctime and mtime is millisecond in zk.
        ctime, mtime = node_data[1].ctime, node_data[1].mtime

        return_info = json.loads(node_dict.decode('utf8'))
        if include_created_at:
            return_info['created_at'] = datetime.datetime.fromtimestamp(
                ctime / 1000).isoformat()
        if include_updated_at:
            return_info['updated_at'] = datetime.datetime.fromtimestamp(
                mtime / 1000).isoformat()

        return return_info

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
        return sorted(nodes, key=lambda x: x['name'])

    @_client_check_wrapper
    def get_node(self, node_name):
        try:
            node_info = self.client.get('/ha/%s' % node_name)

            node_info = self._bytesToDict(node_info, include_created_at=True,
                                          include_updated_at=True)
            return node_info
        except kze.NoNodeError:
            raise exceptions.ClientError('Node %s not found.' % node_name)

    @_client_check_wrapper
    def create_node(self, name, role, n_type, ip):
        existed_nodes = self.list_nodes()
        for existed_node in existed_nodes:
            if existed_node['role'] == role and existed_node['type'] == n_type:
                raise exceptions.ClientError(
                    "The role and type of the node should be unique.")

        path = '/ha/%s' % name
        new_node = node.Node(name, role, n_type, ip)
        try:
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

        for node_role, all_services in service.service_mapping.items():
            new_service_path = path + '/%s' % node_role
            try:
                node_services = all_services[n_type]
            except KeyError:
                continue
            for service_type, service_names in node_services.items():
                service_class = (service.NecessaryService if
                                 service_type == 'necessary' else
                                 service.UnnecessaryService)
                for service_name in service_names:
                    new_service = service_class(service_name,
                                                node_role.split('_')[0])
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
        new_node = node.Node.from_dict(node_info)
        self.client.set(path, value=new_node.to_zk_data())

        node_info = self.get_node(node_name)
        return node_info

    @_client_check_wrapper
    def delete_node(self, node_name):
        self.get_node(node_name)
        path = '/ha/%s' % node_name
        self.client.delete(path, recursive=True)

    @_client_check_wrapper
    def list_services(self, node_name_filter=None, node_role_filter=None):
        """
        List the services in the HA deployment.
        :param node_name_filter: The node filter.
        :type node_name_filter: list or string.
        :param node_role_filter: The node filter.
        :type node_role_filter: list or string.
        :return: the services list.
        """
        if node_name_filter:
            if isinstance(node_name_filter, str):
                node_name_filter = [node_name_filter]
            if not isinstance(node_name_filter, list):
                raise exceptions.ValidationError("node_name_filter should be "
                                                 "a list or string.")
        if node_role_filter:
            if isinstance(node_role_filter, str):
                node_role_filter = [node_role_filter]
            if not isinstance(node_role_filter, list):
                raise exceptions.ValidationError("node_role_filter should be "
                                                 "a list or string.")

        result = []
        for exist_node in self.list_nodes():
            if node_name_filter and exist_node['name'] not in node_name_filter:
                continue
            if node_role_filter and exist_node['role'] not in node_role_filter:
                continue
            path = '/ha/%s/%s_service' % (exist_node['name'],
                                          exist_node['role'])
            for service_name in self.client.get_children(path):
                service_path = path + '/' + service_name
                service_info = self.client.get(service_path)
                service_info = self._bytesToDict(service_info,
                                                 include_updated_at=True)
                service_info['node_name'] = exist_node['name']
                result.append(service_info)
        return sorted(result, key=lambda x: x['node_name'])

    def _get_service_path_and_node(self, service_name, role, n_type):
        for exist_node in self.list_nodes():
            if exist_node['role'] == role and exist_node['type'] == n_type:
                path = '/ha/%s/%s_service/%s' % (exist_node['name'], role,
                                                 service_name)
                return path, exist_node
        raise exceptions.ClientError("Can't find service %s" % service_name)

    @_client_check_wrapper
    def get_service(self, service_name, role, n_type):
        path, srv_node = self._get_service_path_and_node(service_name, role,
                                                         n_type)
        try:
            result = self.client.get(path)
        except kze.NoNodeError:
            raise exceptions.ClientError('Service %s not found.' %
                                         service_name)
        result = self._bytesToDict(result, include_updated_at=True)
        result['node_name'] = srv_node['name']
        return result

    @_client_check_wrapper
    def update_service(self, service_name, role, n_type, alarmed=None,
                       restarted=None, status=None, **kwargs):
        old_service = self.get_service(service_name, role, n_type)
        path, _ = self._get_service_path_and_node(service_name, role, n_type)
        current_time = datetime.datetime.now().isoformat()

        if alarmed is not None:
            if not isinstance(alarmed, bool):
                raise exceptions.ValidationError('alarmed should be boolean '
                                                 'value.')
            old_service['alarmed'] = alarmed
            old_service['alarmed_at'] = current_time
        if restarted is not None:
            if not isinstance(restarted, bool):
                raise exceptions.ValidationError('restarted should be '
                                                 'boolean value.')
            old_service['restarted'] = restarted
            old_service['restarted_at'] = current_time
        if status:
            if status not in service.ServiceStatus().all_status:
                raise exceptions.ValidationError(
                    'status should be in %s.' %
                    service.ServiceStatus().all_status)
            old_service['status'] = status

        old_service.update(kwargs)
        new_service = service.Service.from_dict(old_service)
        self.client.set(path, value=new_service.to_zk_data())

        new_service = self.get_service(service_name, role, n_type)
        return new_service
