import configparser
import copy
import datetime
import json
import logging
import time

from kazoo.client import KazooClient, KazooState
from kazoo import exceptions as kze
from kazoo.handlers.threading import KazooTimeoutError
import os_client_config

from openlabcmd import constants
from openlabcmd import exceptions
from openlabcmd import node
from openlabcmd import service


CONFIGURATION_DICT = {
    'allow_switch': False,
    'dns_log_domain': 'test-logs.openlabtesting.org',
    'dns_master_public_ip': None,
    'dns_provider_account': None,
    'dns_provider_api_url': 'https://api.dnsimple.com/v2/',
    'dns_provider_token': None,
    'dns_slave_public_ip': None,
    'dns_status_domain': 'test-status.openlabtesting.org',
    'github_app_name': None,
    'github_repo': None,
    'github_user_name': None,
    'github_user_password': None,
    'github_user_token': None,
    'heartbeat_timeout_second': 600,
    'logging_level': 'DEBUG',
    'service_restart_max_times': 3,
    'unnecessary_service_switch_timeout_hour': 48,
}


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

    def connect(self, hosts=None, timeout=None, read_only=False):
        if not hosts:
            if not self.config:
                raise exceptions.ClientError('Either config object or hosts '
                                             'string should be provided.')
            try:
                hosts = hosts or self.config.get('ha', 'zookeeper_hosts')
            except (configparser.NoOptionError, configparser.NoSectionError):
                raise exceptions.ClientError(
                    "The config doesn't contain [ha]zookeeper_hosts option.")

        if not timeout:
            timeout = self.config.get('ha', 'zookeeper_connect_timeout',
                                      fallback=5)
        retry_limit = self.config.get('ha', 'zookeeper_connect_retry_limit',
                                      fallback=5)
        try:
            timeout = int(timeout)
        except ValueError:
            raise exceptions.ClientError("zookeeper_connect_timeout "
                                         "should be int-like format.")
        if timeout <= 0:
            raise exceptions.ClientError("zookeeper_connect_timeout "
                                         "should be larger than 0.")

        if self.client is None:
            self.client = KazooClient(hosts=hosts, timeout=timeout,
                                      read_only=read_only)
            self.client.add_listener(self._connection_listener)
            # Manually retry initial connection attempt
            tried_times = 0
            while tried_times < retry_limit:
                try:
                    self.client.start(1)
                    break
                except Exception:
                    self.logConnectionRetryEvent()
                tried_times += 1
                if tried_times == retry_limit:
                    raise exceptions.ClientError(
                        "Tried %s times, failed connecting "
                        "zookeeper." % retry_limit)

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
    def list_nodes(self, with_zk=True, node_role_filter=None,
                   node_type_filter=None):
        if node_role_filter:
            if isinstance(node_role_filter, str):
                node_role_filter = [node_role_filter]
            if not isinstance(node_role_filter, list):
                raise exceptions.ValidationError("node_role_filter should be "
                                                 "a list or string.")
        if node_type_filter:
            if isinstance(node_type_filter, str):
                node_type_filter = [node_type_filter]
            if not isinstance(node_type_filter, list):
                raise exceptions.ValidationError("node_type_filter should be "
                                                 "a list or string.")

        path = '/ha'
        try:
            nodes_objs = []
            for exist_node in self.client.get_children(path):
                if exist_node == 'configuration':
                    continue
                if not with_zk and 'zookeeper' in exist_node:
                    continue
                node_obj = self.get_node(exist_node)
                if node_role_filter and node_obj.role not in node_role_filter:
                    continue
                if node_type_filter and node_obj.type not in node_type_filter:
                    continue
                nodes_objs.append(node_obj)
        except kze.NoNodeError:
            return []
        return sorted(nodes_objs, key=lambda x: x.name)

    @_client_check_wrapper
    def get_node(self, node_name):
        try:
            node_bytes = self.client.get('/ha/%s' % node_name)
            node_obj = node.Node.from_zk_bytes(node_bytes)
            return node_obj
        except kze.NoNodeError:
            raise exceptions.ClientError('Node %s not found.' % node_name)

    def _init_service(self, node_name, node_type):
        path = '/ha/%s' % node_name
        master_service_path = path + '/master'
        slave_service_path = path + '/slave'
        zookeeper_service_path = path + '/zookeeper'

        self.client.create(master_service_path)
        self.client.create(slave_service_path)
        self.client.create(zookeeper_service_path)

        for node_role, all_services in service.service_mapping.items():
            new_service_path = path + '/%s' % node_role
            try:
                node_services = all_services[node_type]
            except KeyError:
                continue
            for service_type, service_names in node_services.items():
                service_class = (service.NecessaryService if
                                 service_type == 'necessary' else
                                 service.UnnecessaryService)
                for service_name in service_names:
                    new_service = service_class(service_name, node_name)
                    self.client.create(
                        new_service_path + '/%s' % service_name,
                        value=new_service.to_zk_bytes())

    @_client_check_wrapper
    def create_node(self, name, role, n_type, ip):
        existed_nodes = self.list_nodes()
        for existed_node in existed_nodes:
            if existed_node.role == role and existed_node.role == n_type:
                raise exceptions.ClientError(
                    "The role and type of the node should be unique.")

        path = '/ha/%s' % name
        new_node = node.Node(name, role, n_type, ip)
        try:
            self.client.create(path,
                               value=new_node.to_zk_bytes(),
                               makepath=True)
        except kze.NodeExistsError:
            raise exceptions.ClientError("The node %s is already existed."
                                         % name)
        self._init_service(name, n_type)
        node_obj = self.get_node(name)
        return node_obj

    @_client_check_wrapper
    def update_node(self, node_name, maintain=None, role=None, **kwargs):
        path = '/ha/%s' % node_name
        node_obj = self.get_node(node_name)
        if maintain is not None:
            if maintain:
                if node_obj.status == node.NodeStatus.UP:
                    node_obj.status = node.NodeStatus.MAINTAINING
                else:
                    raise exceptions.ClientError(
                        "The node must be in 'up' status when trying to "
                        "maintain it.")
            else:
                if node_obj.status == node.NodeStatus.MAINTAINING:
                    node_obj.status = node.NodeStatus.UP
                    node_obj.heartbeat = datetime.datetime.utcnow().strftime(
                        '%Y-%m-%d %H:%M:%S')
                else:
                    raise exceptions.ClientError(
                        "The node must be in 'maintaining' status when trying "
                        "to un-maintain it.")
        if role:
            node_obj.role = role
        switch_status = kwargs.get('switch_status')
        if switch_status is not None:
            if switch_status.lower() not in ['start', 'end']:
                raise exceptions.ClientError(
                    "switch_status must be 'start', 'end'")
        node_obj.update(kwargs)
        self.client.set(path, value=node_obj.to_zk_bytes())

        node_obj = self.get_node(node_name)
        return node_obj

    @_client_check_wrapper
    def delete_node(self, node_name):
        self.get_node(node_name)
        path = '/ha/%s' % node_name
        self.client.delete(path, recursive=True)

    @_client_check_wrapper
    def list_services(self, node_name_filter=None, node_role_filter=None,
                      status_filter=None):
        """
        List the services in the HA deployment.
        :param node_name_filter: The node filter.
        :type node_name_filter: list or string.
        :param node_role_filter: The node filter.
        :type node_role_filter: list or string.
        :param status_filter: The status filter.
        :type status_filter: list or string.
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
        if status_filter:
            if isinstance(status_filter, str):
                status_filter = [status_filter]
            if not isinstance(status_filter, list):
                raise exceptions.ValidationError("status_filter should be "
                                                 "a list or string.")

        result = []
        for exist_node in self.list_nodes():
            if node_name_filter and exist_node.name not in node_name_filter:
                continue
            if node_role_filter and exist_node.role not in node_role_filter:
                continue
            path = '/ha/%s/%s' % (exist_node.name, exist_node.role)
            for service_name in self.client.get_children(path):
                service_path = path + '/' + service_name
                service_bytes = self.client.get(service_path)
                service_obj = service.Service.from_zk_bytes(service_bytes)
                if status_filter and service_obj.status not in status_filter:
                    continue
                result.append(service_obj)
        return sorted(result, key=lambda x: x.node_name)

    @_client_check_wrapper
    def get_service(self, service_name, node_name):
        service_node = self.get_node(node_name)
        path = '/ha/%s/%s/%s' % (service_node.name, service_node.role,
                                 service_name)
        try:
            service_bytes = self.client.get(path)
        except kze.NoNodeError:
            raise exceptions.ClientError('Service %s not found.' %
                                         service_name)
        service_obj = service.Service.from_zk_bytes(service_bytes)
        return service_obj

    @_client_check_wrapper
    def update_service(self, service_name, node_name, alarmed=None,
                       restarted=None, status=None, **kwargs):
        old_service = self.get_service(service_name, node_name)
        service_node = self.get_node(node_name)
        path = '/ha/%s/%s/%s' % (service_node.name, service_node.role,
                                 service_name)
        current_time = datetime.datetime.utcnow().isoformat()

        if alarmed is not None:
            if not isinstance(alarmed, bool):
                raise exceptions.ValidationError('alarmed should be boolean '
                                                 'value.')
            old_service.alarmed = alarmed
            if alarmed:
                old_service.alarmed_at = current_time
        if restarted is not None:
            if not isinstance(restarted, bool):
                raise exceptions.ValidationError('restarted should be '
                                                 'boolean value.')
            old_service.restarted = restarted
            if restarted:
                old_service.restarted_at = current_time
        if status:
            if status not in service.ServiceStatus().all_status:
                raise exceptions.ValidationError(
                    'status should be in %s.' %
                    service.ServiceStatus().all_status)
            old_service.status = status

        old_service.update(kwargs)
        self.client.set(path, value=old_service.to_zk_bytes())

        new_service = self.get_service(service_name, node_name)
        return new_service

    @_client_check_wrapper
    def switch_master_and_slave(self):
        """Mark node's switch status to start.

        This func is called by labkeeper deploy tool. So that operators can
        switch master-slave role by hand. Once health checker find that all
        nodes' switch status are `start`, it will start to switch cluster.
        """
        for node in self.list_nodes():
            if node.type != 'zookeeper':
                self.update_node(node.name, switch_status='start')

    @_client_check_wrapper
    def check_and_repair_deployment_sg(self, is_dry_run=False):
        """Check and Repair current HA deployment Security Group configuration

        This func is called by labkeeper deploy tool. So that operators can
        check and repair exist deployment from zookeeper. The function is
        for checking Cloud Security Group configuration.
        """
        deploy_map = {}
        cloud_provide_rules = {}
        unexpect_rules = {}
        for node in self.list_nodes():
            ha_ports_cp = copy.deepcopy(constants.HA_PORTS)
            if node.type == 'nodepool':
                ha_ports_cp.remove(constants.MYSQL_HA_PORT)
            elif node.type == 'zuul':
                for p in constants.ZOOKEEPER_HA_PORTS:
                    ha_ports_cp.remove(p)
            elif node.type == 'zookeeper':
                ha_ports_cp.remove(constants.RSYNCD_HA_PORT)
                ha_ports_cp.remove(constants.MYSQL_HA_PORT)
            if node.name.split("-")[0] not in deploy_map:
                deploy_map[node.name.split("-")[0]] = {'nodes': [node]}
                cloud_provide_rules[node.name.split("-")[0]] = {
                    node.ip + '/32': ha_ports_cp}
            else:
                deploy_map[node.name.split("-")[0]]['nodes'].append(node)
                cloud_provide_rules[node.name.split("-")[0]][
                    node.ip + '/32'] = ha_ports_cp

        # Fit current expect_rules
        expect_rules = {}
        sg_map = {}
        cloud_names = list(cloud_provide_rules.keys())
        for cloud_name, ip_dict in cloud_provide_rules.items():
            c_names = copy.deepcopy(cloud_names)
            c_names.remove(cloud_name)
            expect_rules[cloud_name] = copy.deepcopy(ip_dict)
            if len(cloud_provide_rules[cloud_name].keys()) > 1:
                for c_name in c_names:
                    expect_rules[cloud_name].update(
                        copy.deepcopy(cloud_provide_rules[c_name]))
            else:
                for c_name in c_names:
                    for ip in cloud_provide_rules[c_name].keys():
                        if 2888 in cloud_provide_rules[c_name][ip]:
                            zk_ha_ports = copy.deepcopy(
                                constants.ZOOKEEPER_HA_PORTS)
                            expect_rules[cloud_name][ip] = zk_ha_ports
                        else:
                            expect_rules[cloud_name][ip] = [2181]

        for cloud_name, nodes_dict in deploy_map.items():
            net_client = os_client_config.make_rest_client(
                'network', cloud=cloud_name)
            for sg_name in constants.HA_SGs:
                url = "/security-groups?name=%s" % sg_name
                resp = net_client.get(url)
                if resp.status_code != 200:
                    raise exceptions.ClientError(
                        'Security group %(sg_name)s not found on '
                        'cloud %(cloud_name)s.' % {'sg_name': sg_name,
                                                   'cloud_name': cloud_name})
                sgr_data = resp.json()['security_groups'][0]
                if cloud_name not in sg_map:
                    sg_map[cloud_name] = resp.json()[
                        'security_groups'][0]['id']
                for rule in sgr_data['security_group_rules']:
                    if rule['direction'] != 'ingress':
                        continue

                    is_specified_1_port = (
                            rule['port_range_min'] == rule['port_range_max'])
                    is_ipv4 = rule['ethertype'] == 'IPv4'
                    is_tcp = rule['protocol'] == 'tcp'

                    if not expect_rules[cloud_name].get(
                            rule['remote_ip_prefix']):
                        if cloud_name not in unexpect_rules:
                            unexpect_rules[cloud_name] = [
                                (rule['remote_ip_prefix'],
                                 rule['port_range_min'], rule['id'])]
                        else:
                            unexpect_rules[cloud_name].append(
                                (rule['remote_ip_prefix'],
                                 rule['port_range_min'], rule['id']))
                    else:
                        if (is_specified_1_port and is_ipv4 and is_tcp and
                                rule['port_range_min'] in expect_rules[
                                    cloud_name][rule['remote_ip_prefix']]):
                            expect_rules[cloud_name][
                                rule['remote_ip_prefix']].remove(
                                rule['port_range_min'])
                            if len(expect_rules[cloud_name][
                                       rule['remote_ip_prefix']]) ==0:
                                expect_rules[cloud_name].pop(
                                    rule['remote_ip_prefix'])
                        else:
                            if cloud_name not in unexpect_rules:
                                unexpect_rules[cloud_name] = [
                                    (rule['remote_ip_prefix'],
                                     rule['port_range_min'], rule['id'])]
                            else:
                                unexpect_rules[cloud_name].append((
                                    rule['remote_ip_prefix'],
                                    rule['port_range_min'], rule['id']))

        if not is_dry_run:
            # analysis expect_rules
            for cloud_name, ip_dict in expect_rules.items():
                if not ip_dict:
                    print("Cloud %s: PASSED" % cloud_name)
                    continue

                print("Recover security group rules for cloud %s:" %
                      cloud_name)
                # Here means the sg lacks SG_rule settings
                net_client = os_client_config.make_rest_client(
                    'network', cloud=cloud_name)
                for ip, ports in ip_dict.items():
                    req = {
                        "security_group_rule": {
                            "direction": "ingress",
                            "ethertype": "IPv4",
                            "protocol": "tcp",
                            "security_group_id": sg_map[cloud_name],
                            "remote_ip_prefix": ip
                        }
                    }
                    for port in ports:
                        req["security_group_rule"].update({
                            "port_range_min": port,
                            "port_range_max": port
                        })
                        resp = net_client.post('/security-group-rules',
                                               json=req)
                        if resp.status_code != 201:
                            raise exceptions.ClientError(
                                'Failed to create security group rule on '
                                'cloud %(cloud_name)s with summary '
                                '%(ip)s %(port)s'
                                % {'cloud_name': cloud_name, 'ip': ip,
                                   'port': port})
                        print("Create new sg_rule, summary %(ip)s %(port)s" % {
                            "ip": ip,
                            "port": str(port)
                        })

            # remove unexpect sg_rules
            for cloud_name, ip_port_tuple_list in unexpect_rules.items():
                net_client = os_client_config.make_rest_client(
                    'network', cloud=cloud_name)
                print("Unexpect security group rules clean for cloud %s:" %
                      cloud_name)
                for ip_port_tuple in ip_port_tuple_list:
                    url = "/security-group-rules/%s" % ip_port_tuple[2]
                    resp = net_client.delete(url)
                    if resp.status_code != 204:
                        raise exceptions.ClientError(
                            'Failed to delete security group rule '
                            '%(rule_id)s on cloud %(cloud_name)s'
                            % {'cloud_name': cloud_name,
                               'rule_id': ip_port_tuple[2]})
                    print("Remove sg_rule %(rule_id)s, summary %(ip)s "
                          "%(port)s" % {
                        "rule_id": ip_port_tuple[2],
                        "ip": ip_port_tuple[0],
                        "port": str(ip_port_tuple[1])
                    })
        else:
            for cloud_name, ip_dict in expect_rules.items():
                if not ip_dict:
                    print("Cloud %s: PASSED" % cloud_name)
                    continue
                print("Found lack security group rules in cloud %s" %
                      cloud_name)
                for ip, ports in ip_dict.items():
                    print("    Need to create new rule for (ip)s (ports)s" % {
                        "ip": ip,
                        "ports": str(ports)
                    })

            # remove unexpect sg_rules
            for cloud_name, ip_port_tuple_list in unexpect_rules.items():
                print("Found unexpect security group rules clean for "
                      "cloud %s:" % cloud_name)
                for ip_port_tuple in ip_port_tuple_list:
                    print("    Need to remove sg_rule %(rule_id)s, "
                          "summary %(ip)s %(port)s" % {
                        "rule_id": ip_port_tuple[2],
                        "ip": ip_port_tuple[0],
                        "port": str(ip_port_tuple[1])
                    })

    def _init_ha_configuration(self):
        path = '/ha/configuration'
        self.client.create(path,
                           value=json.dumps(CONFIGURATION_DICT).encode('utf8'),
                           makepath=True)

    @_client_check_wrapper
    def list_configuration(self):
        path = '/ha/configuration'
        try:
            config_bytes = self.client.get(path)
        except kze.NoNodeError:
            self._init_ha_configuration()
            config_bytes = self.client.get(path)
        return json.loads(config_bytes[0].decode('utf8'))

    @_client_check_wrapper
    def update_configuration(self, name, value):
        path = '/ha/configuration'
        configs = self.list_configuration()
        if name not in configs.keys():
            raise exceptions.ClientError('There is not option %s' % name)
        configs[name] = value
        self.client.set(path, json.dumps(configs).encode('utf8'))
