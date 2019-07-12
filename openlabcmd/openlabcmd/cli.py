import argparse
import configparser
import os
import subprocess
import sys
import yaml

from openlabcmd import exceptions
from openlabcmd.plugins import base
from openlabcmd import utils
from openlabcmd.utils import _color
from openlabcmd import zk
from openlabcmd import repo
from openlabcmd import hint


class OpenLabCmd(object):
    def __init__(self):
        self.parser = None
        self.args = None
        self.config = None
        self.zk = None

    @staticmethod
    def _str2bool(v):
        if v.lower() in ('yes', 'true', 't', 'y', '1'):
            return True
        elif v.lower() in ('no', 'false', 'f', 'n', '0'):
            return False
        else:
            raise argparse.ArgumentTypeError('Boolean value expected.')

    @staticmethod
    def _node_name_format(v):
        spl_v = v.split('-')
        if (len(spl_v) < 2 or spl_v[-2] != 'openlab' or
                spl_v[-1] not in ['nodepool', 'zuul', 'zookeeper']):
            raise argparse.ArgumentTypeError(
                'Node name should be format like: '
                '{cloud_provider}-openlab-{type}')
        return v

    def _add_check_cmd(self, parser):
        # openlab check
        cmd_check = parser.add_parser('check',
                                      help='Check OpenLab environment.')
        cmd_check.set_defaults(func=self.check)
        cmd_check.add_argument('--type', default='default',
                               help="Specify a plugin type, like 'nodepool', "
                                    "'jobs', 'all'. Default is 'default',"
                                    " will skip the experimental plugins.")
        cmd_check.add_argument('--cloud', default='all',
                               help="Specify a cloud provider, like 'otc', "
                                    "'vexxhost'. Default is 'all'.")
        cmd_check.add_argument('--nocolor', action='store_true',
                               help='Enable the no color mode.')
        cmd_check.add_argument('--recover', action='store_true',
                               help='Enable the auto recover mode.')

    def _add_hint_cmd(self, parser):
        # openlab hint
        cmd_hint = parser.add_parser(
            'hint',
            help='Print hint info.')
        cmd_hint.set_defaults(func=self.hint)
        cmd_hint.add_argument('--type', default='all',
                              help="Specify a hint type, "
                                   "like 'resource', 'redundant'.")

    def _add_repo_cmd(self, parser):
        # openlab repo list
        cmd_repo = parser.add_parser(
            'repo',
            help='The repos which enable the OpenLab.')
        cmd_repo_list_sub = cmd_repo.add_subparsers(title='repo',dest='repo')
        cmd_repo_list = cmd_repo_list_sub.add_parser(
            'list', help='List the repos which enable the OpenLab app.')

        cmd_repo_list.set_defaults(func=self.repo_list)
        cmd_repo_list.add_argument('--server', default='github.com',
                                   help="Specify base server url. Default is "
                                        "github.com")
        cmd_repo_list.add_argument(
            '--app-id', default='6778',
            help="Specify the github APP ID, Default is 6778 (allinone: 7102,"
                 " OpenLab: 6778).")
        cmd_repo_list.add_argument(
            '--app-key', default='/var/lib/zuul/openlab-app-key.pem',
            help='Specify the app key file path. Default is '
                 '/var/lib/zuul/openlab-app-key.pem')

    def _add_ha_node_cmd(self, parser):
        # openlab ha node
        cmd_ha_node = parser.add_parser('node', help='Manage HA node.')
        cmd_ha_node_subparsers = cmd_ha_node.add_subparsers(title='node',
                                                            dest='node')
        # openlab ha node list
        cmd_ha_node_list = cmd_ha_node_subparsers.add_parser(
            'list', help='List all nodes.')
        cmd_ha_node_list.set_defaults(func=self.ha_node_list)
        cmd_ha_node_list.add_argument(
            '--type', action='append',
            choices=['nodepool', 'zuul', 'zookeeper'],
            help='Filter the services with the specified node type.')
        cmd_ha_node_list.add_argument(
            '--role', action='append',
            choices=['master', 'slave', 'zookeeper'],
            help='Filter the services with the specified node role.')
        # openlab ha node get
        cmd_ha_node_get = cmd_ha_node_subparsers.add_parser(
            'get', help='Get a node.')
        cmd_ha_node_get.set_defaults(func=self.ha_node_get)
        cmd_ha_node_get.add_argument('name', help='The node hostname.')
        # openlab ha node create
        cmd_ha_node_create = cmd_ha_node_subparsers.add_parser(
            'init', help='Create a new node. This command usually should be '
                         'called by CI environment deploy tools when creating '
                         'a new system. Operators should be careful for this '
                         'command. One case for this command may like: the '
                         'data in zookeeper is broken or missing, but the '
                         'node works well, so that operators need to rebuild '
                         'the node info.')
        cmd_ha_node_create.set_defaults(func=self.ha_node_create)
        cmd_ha_node_create.add_argument(
            'name', type=self._node_name_format,
            help='The new node hostname, it should be global unique. Format: '
                 '{cloud-provider}-openlab-{type}.')
        cmd_ha_node_create.add_argument(
            '--type', required=True, choices=['nodepool', 'zuul', 'zookeeper'],
            help="The new node type. Choose from 'nodepool', 'zuul' and "
                 "'zookeeper'")
        cmd_ha_node_create.add_argument(
            '--role', required=True, choices=['master', 'slave', 'zookeeper'],
            help="The new node role. It should be 'master', 'slave' or "
                 "'zookeeper'.")
        cmd_ha_node_create.add_argument(
            '--ip', required=True, help="The new node's public IP.")

        # openlab ha node set
        cmd_ha_node_set = cmd_ha_node_subparsers.add_parser(
            'set', help='Update a node.')
        cmd_ha_node_set.set_defaults(func=self.ha_node_update)
        cmd_ha_node_set.add_argument('name', help='The node hostname.')
        cmd_ha_node_set.add_argument('--maintain', metavar='{yes, no}',
                                     type=self._str2bool,
                                     help='Set the node to maintained status.')
        cmd_ha_node_set.add_argument(
            '--role', choices=['master', 'slave'],
            help="Update node role. It should be either 'master' or 'slave'. "
                 "Be careful to update the role, you should not update role "
                 "except emergency situations, because it will impact "
                 "checking scope of HA monitor , HA monitor will check and "
                 "update it with built-in policy automatically.")

        # openlab ha node delete
        cmd_ha_node_delete = cmd_ha_node_subparsers.add_parser(
            'delete', help='Delete a node.')
        cmd_ha_node_delete.set_defaults(func=self.ha_node_delete)
        cmd_ha_node_delete.add_argument('name', help='The node hostname.')

    def _add_ha_service_cmd(self, parser):
        # openlab ha service
        cmd_ha_service = parser.add_parser('service',
                                           help='Manage HA service.')
        cmd_ha_service_subparsers = cmd_ha_service.add_subparsers(
            title='service', dest='service')
        # openlab ha service list
        cmd_ha_service_list = cmd_ha_service_subparsers.add_parser(
            'list', help='List all services.')
        cmd_ha_service_list.set_defaults(func=self.ha_service_list)
        cmd_ha_service_list.add_argument(
            '--node', action='append',
            help='Filter the services with the specified node name.')
        cmd_ha_service_list.add_argument(
            '--role', action='append',
            choices=['master', 'slave', 'zookeeper'],
            help='Filter the services with the specified node role.')
        cmd_ha_service_list.add_argument(
            '--status', action='append',
            choices=['up', 'down', 'restarting'],
            help='Filter the services with the specified status.')
        # openlab ha service get
        cmd_ha_service_get = cmd_ha_service_subparsers.add_parser(
            'get', help='Get a service.')
        cmd_ha_service_get.set_defaults(func=self.ha_service_get)
        cmd_ha_service_get.add_argument('name', help='service name.')
        cmd_ha_service_get.add_argument(
            '--node', required=True, help="The node where the service run.")

    def _add_ha_cluster_cmd(self, parser):
        # openlab ha cluster
        cmd_ha_cluster = parser.add_parser('cluster',
                                           help='Manage HA cluster.')
        cmd_ha_cluster_subparsers = cmd_ha_cluster.add_subparsers(
            title='cluster', dest='cluster')
        # openlab ha cluster switch
        cmd_ha_service_get = cmd_ha_cluster_subparsers.add_parser(
            'switch', help='Switch Master and Slave role.')
        cmd_ha_service_get.set_defaults(func=self.ha_cluster_switch)

        # openlab ha cluster repair
        cmd_ha_cluster_repair = cmd_ha_cluster_subparsers.add_parser(
            'repair', help='HA deployment check and repair.')
        cmd_ha_cluster_repair.set_defaults(func=self.ha_cluster_repair)
        cmd_ha_cluster_repair.add_argument(
            '--security-group',
            help='Repair the Security Group of HA deployment.',
            action='store_true', required=True)
        cmd_ha_cluster_repair.add_argument(
            '--dry-run', help='Only report the check list of HA deployment,'
                              ' not try to repair if there is a check error.',
            action='store_true')

    def _add_ha_config_cmd(self, parser):
        # openlab ha cluster
        cmd_ha_config = parser.add_parser('config',
                                          help='Manage HA cluster '
                                               'configuration.')
        cmd_ha_config_subparsers = cmd_ha_config.add_subparsers(
            title='config', dest='configuration')
        # openlab ha config list
        cmd_ha_config_list = cmd_ha_config_subparsers.add_parser(
            'list', help='List all HA cluster config options.')
        cmd_ha_config_list.set_defaults(func=self.ha_config_list)
        # openlab ha config set
        cmd_ha_config_set = cmd_ha_config_subparsers.add_parser(
            'set', help='Update a HA cluster config option.')
        cmd_ha_config_set.set_defaults(func=self.ha_config_update)
        cmd_ha_config_set.add_argument('name',
                                       help='The name of config option.')
        cmd_ha_config_set.add_argument('value',
                                       help='The value of config option.')

    def _add_ha_cmd(self, parser):
        # openlab ha
        cmd_ha = parser.add_parser('ha',
                                   help='Manage OpenLab HA deployment.')
        cmd_ha_subparsers = cmd_ha.add_subparsers(title='ha', dest='ha')
        self._add_ha_node_cmd(cmd_ha_subparsers)
        self._add_ha_service_cmd(cmd_ha_subparsers)
        self._add_ha_cluster_cmd(cmd_ha_subparsers)
        self._add_ha_config_cmd(cmd_ha_subparsers)

    def create_parser(self):
        parser = argparse.ArgumentParser(
            description='The command line tool for OpenLab management',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        parser.add_argument('-c', dest='config',
                            help='path to config file')
        parser.add_argument('-f', dest='format', choices=['raw', 'pretty'],
                            default='pretty',
                            help='output format')

        subparsers = parser.add_subparsers(title='commands',
                                           dest='command')
        self._add_hint_cmd(subparsers)
        self._add_repo_cmd(subparsers)
        self._add_check_cmd(subparsers)
        self._add_ha_cmd(subparsers)

        return parser

    def _get_cloud_list(self, cloud):
        cloud_conf_location = self.config.get(
            'check', 'cloud_conf', fallback='/etc/openstack/clouds.yaml')
        with open(cloud_conf_location) as f:
            clouds = yaml.load(f, Loader=yaml.FullLoader)
            clouds_list = [c for c in clouds['clouds']]

        if cloud not in clouds_list + ['all']:
            raise exceptions.ClientError(
                "Error: Cloud %(cloud)s is not found. Please use the cloud "
                "in %(clouds_list)s or just use 'all'." % {
                    'cloud': cloud, 'clouds_list': clouds_list})

        clouds_list = clouds_list if cloud == 'all' else [cloud]
        return clouds_list

    def _header_print(self, header):
        print(_color(header))
        print(_color("=" * 48))

    def hint(self):
        h = hint.Hint(self.args.type)
        h.print_hints()

    def repo_list(self):
        r = repo.Repo(self.args.server,
                      self.args.app_id,
                      self.args.app_key)
        repos = r.list()
        print(utils.format_output('repo', repos))
        print("Total: %s" % len(repos))

    def check(self):
        utils.NOCOLOR = self.args.nocolor

        cloud_list = self._get_cloud_list(self.args.cloud)

        if self.args.type == 'default':
            plugins = list(filter(lambda x: not x.experimental,
                                  base.Plugin.plugins))
        elif self.args.type == 'all':
            plugins = base.Plugin.plugins
        else:
            # Filter the plugins with specific ptype
            plugins = list(filter(lambda x: x.ptype == self.args.type,
                                  base.Plugin.plugins))

        cnt = len(cloud_list)
        exit_flag = False
        for index, cloud in enumerate(cloud_list):
            header = "%s/%s. %s cloud check" % (index + 1, cnt, cloud)
            self._header_print(header)
            for plugin_class in plugins:
                plugin = plugin_class(cloud, self.config)
                plugin.check_begin()
                plugin.check()
                plugin.check_end()
                # the failed flag would be record when do check()
                if self.args.recover and plugin.failed:
                    plugin.recover()
                if plugin.failed:
                    exit_flag = True

        if exit_flag:
            raise exceptions.ClientError("Error: cloud check failed.")

    def _zk_wrapper(func):
        def wrapper(self, *args, **kwargs):
            if self.zk is None:
                self.zk = zk.ZooKeeper(config=self.config)
            try:
                self.zk.connect()
                func(self, *args, **kwargs)
            finally:
                self.zk.disconnect()
        return wrapper

    @_zk_wrapper
    def ha_node_list(self):
        result = self.zk.list_nodes(node_role_filter=self.args.role,
                                    node_type_filter=self.args.type)
        if self.args.format == 'pretty':
            print(utils.format_output('node', result))
        else:
            dict_result = []
            for node in result:
                dict_result.append(node.to_dict())
            print(dict_result)

    @_zk_wrapper
    def ha_node_get(self):
        node_name = self.args.name
        result = self.zk.get_node(node_name)
        if self.args.format == 'pretty':
            print(utils.format_output('node', result))
        else:
            print(result.to_dict())

    @_zk_wrapper
    def ha_node_create(self):
        if self.args.type == 'zookeeper':
            if self.args.role != 'zookeeper':
                raise argparse.ArgumentTypeError(
                    'zookeeper node must  be zookeeper type.')
        else:
            if self.args.role == 'zookeeper':
                raise argparse.ArgumentTypeError(
                    'zookeeper node must be zookeeper type.')

        result = self.zk.create_node(self.args.name, self.args.role,
                                     self.args.type, self.args.ip)

        if self.args.format == 'pretty':
            print(utils.format_output('node', result))
        else:
            print(result.to_dict())

    @_zk_wrapper
    def ha_node_update(self):
        node_name = self.args.name
        if self.args.maintain is None and not self.args.role:
            raise exceptions.ClientError("Too few arguments")
        maintain = self.args.maintain
        role = self.args.role
        result = self.zk.update_node(node_name, maintain, role)
        if self.args.format == 'pretty':
            print(utils.format_output('node', result))
        else:
            print(result.to_dict())

    @_zk_wrapper
    def ha_node_delete(self):
        node_name = self.args.name
        self.zk.delete_node(node_name)

    @_zk_wrapper
    def ha_service_list(self):
        result = self.zk.list_services(self.args.node, self.args.role,
                                       self.args.status)
        if self.args.format == 'pretty':
            print(utils.format_output('service', result))
        else:
            print(result.to_dict())

    @_zk_wrapper
    def ha_service_get(self):
        result = self.zk.get_service(self.args.name.lower(), self.args.node)
        if self.args.format == 'pretty':
            print(utils.format_output('service', result))
        else:
            print(result.to_dict())

    @_zk_wrapper
    def ha_cluster_switch(self):
        try:
            self.zk.switch_master_and_slave()
            print("Switch success")
        except exceptions.OpenLabCmdError:
            print("Switch failed")
    
    @_zk_wrapper
    def ha_cluster_repair(self):
        # TODO(bz) This repair may support other function
        if self.args.security_group:
            try:
                self.zk.check_and_repair_deployment_sg(
                    is_dry_run=self.args.dry_run)
                print("Check success")
            except exceptions.OpenLabCmdError:
                print("Check failed")

    @_zk_wrapper
    def ha_config_list(self):
        result = self.zk.list_configuration()
        if self.args.format == 'pretty':
            print(utils.format_dict(result))
        else:
            print(result)

    @_zk_wrapper
    def ha_config_update(self):
        value = self.args.value
        if self.args.name in ['allow_switch']:
            value = self._str2bool(value)
        self.zk.update_configuration(self.args.name, value)

    def run(self):
        # no arguments, print help messaging, then exit with error(1)
        if not self.args.command:
            self.parser.print_help()
            return 1
        if not getattr(self.args, 'func', None):
            help_message = subprocess.getoutput("%s -h" % ' '.join(sys.argv))
            print(help_message)
            return 1
        self.args.func()

    def _initConfig(self):
        self.config = configparser.ConfigParser()
        if self.args.config:
            locations = [self.args.config]
        else:
            locations = ['/etc/openlab/openlab.conf',
                         '~/openlab.conf',
                         '/usr/local/etc/openlab/openlab.conf']

        for fp in locations:
            if os.path.exists(os.path.expanduser(fp)):
                self.config.read(os.path.expanduser(fp))
                return
        raise exceptions.ClientError("Unable to locate config file in "
                                     "%s" % locations)

    def _main(self):
        try:
            self.parser = self.create_parser()
            self.args = self.parser.parse_args()
            self._initConfig()
            return self.run()
        except exceptions.OpenLabCmdError as e:
            print(e)
            return 1

    @classmethod
    def main(cls):
        return cls()._main()


def main():
    return OpenLabCmd.main()


if __name__ == '__main__':
    sys.exit(main())
