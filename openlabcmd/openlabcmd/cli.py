import argparse
import sys
import yaml

from openlabcmd.plugins import base
from openlabcmd import utils
from openlabcmd.utils import _color


class OpenLabCmd(object):
    def __init__(self):
        self.parser = None
        self.args = None

    def create_parser(self):
        parser = argparse.ArgumentParser(
            description='The command line tool for OpenLab management',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)

        # TODO(wxy): parse config file to make -c work
        parser.add_argument('-c', dest='config',
                            default='/etc/openlab/openlab.yaml',
                            help='path to config file')

        subparsers = parser.add_subparsers(title='commands',
                                           dest='command')

        cmd_check = subparsers.add_parser('check',
                                          help='check openlab environment')
        cmd_check.set_defaults(func=self.check)
        cmd_check.add_argument('--type', default='all',
                               help="Specify a plugin type, like 'nodepool', "
                                    "'jobs'. Default is 'all'.")
        cmd_check.add_argument('--cloud', default='all',
                               help="Specify a cloud provider, like 'otc', "
                                    "'vexxhost'. Default is 'all'.")
        cmd_check.add_argument('--nocolor', action='store_true',
                               help='Enable the no color mode.')
        cmd_check.add_argument('--recover', action='store_true',
                               help='Enable the auto recover mode.')

        return parser

    def _get_cloud_list(self, cloud):
        with open('/etc/openstack/clouds.yaml') as f:
            clouds = yaml.load(f, Loader=yaml.FullLoader)
            clouds_list = [c for c in clouds['clouds']]

        if cloud not in clouds_list + ['all']:
            raise Exception(
                "Error: Cloud %(cloud)s is not found. Please use the cloud "
                "in %(clouds_list)s or just use 'all'." % {
                    'cloud': cloud, 'clouds_list':clouds_list})

        clouds_list = clouds_list if cloud == 'all' else [cloud]
        return clouds_list

    def _header_print(self, header):
        print(_color(header))
        print(_color("=" * 48))

    def check(self):
        utils.NOCOLOR = self.args.nocolor

        cloud_list = self._get_cloud_list(self.args.cloud)

        if self.args.type != 'all':
            # Filter the plugins with specific ptype
            plugins = list(filter(lambda x: x.ptype == self.args.type,
                                  base.Plugin.plugins))
        else:
            plugins = base.Plugin.plugins

        cnt = len(cloud_list)
        for i, c in enumerate(cloud_list):
            header = "%s/%s. %s cloud check" % (i + 1, cnt, c)
            self._header_print(header)
            for plugin in plugins:
                plugin.cloud = c
                plugin.check_begin()
                plugin.check()
                plugin.check_end()
                # the failed flag would be record when do check()
                if self.args.recover and plugin.failed:
                    plugin.recover()

    def run(self):
        # no arguments, print help messaging, then exit with error(1)
        if not self.args.command:
            self.parser.print_help()
            return 1
        self.args.func()

    def _main(self):
        self.parser = self.create_parser()
        self.args = self.parser.parse_args()
        self.run()

    @classmethod
    def main(cls):
        return cls()._main()


def main():
    return OpenLabCmd.main()


if __name__ == '__main__':
    sys.exit(main())
