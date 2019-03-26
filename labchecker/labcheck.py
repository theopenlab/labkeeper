from plugins.base import Plugin
from utils import _color
import utils
import sys
import getopt
import yaml


def usage():
    print("Usage: labchecker [--type <plugin-type>] [--cloud <cloud-provider-name>] [--nocolor]")
    print("optional arguments:")
    print("\t--help\t\tShow help message and exit.")
    print("\t--type\t\tSpecify a plugin type, like 'provider', 'all'(default)")
    print("\t--cloud\t\tSpecify a cloud provider, like 'otc', 'vexxhost', 'all'(default).")
    print("\t--nocolor\tEnable the no color mode.")
    print("Exmaple:")
    print("labchecker check --type all --cloud all")
    print("labchecker check --type nodepool --cloud vexxhost")
    print("labchecker check --type nodepool --cloud vexxhost --nocolor")


def get_cloud_list(cloud):
    with open('/etc/openstack/clouds.yaml') as f:
        clouds = yaml.load(f, Loader=yaml.FullLoader)
        clouds_list = [c for c in clouds['clouds']]

    if cloud not in clouds_list + ['all']:
        print("Error: Cloud %s is not found." % cloud)
        print("Please use the cloud in %s." % clouds_list)
        exit(2)

    clouds_list = clouds_list if cloud == 'all' else [cloud]
    return clouds_list


def header_print(header):
    print(_color(header))
    print(_color("=" * 48))


def main(argv):
    cloud = 'all'
    ptype = ''

    try:
        opts, args = getopt.getopt(argv, "hnt:c:", ["help", "cloud=", "type=", "nocolor"])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-c", "--cloud"):
            cloud = a
        elif o in ("-t", "--type"):
            ptype = a
        elif o in ("n", "--nocolor"):
            utils.NOCOLOR = True

    cloud_list = get_cloud_list(cloud)

    if ptype:
        # Filter the plugins with specific ptype
        plugins = list(filter(lambda x: x.ptype == ptype,
                              Plugin.plugins))
    else:
        plugins = Plugin.plugins

    cnt = len(cloud_list)
    for i, c in enumerate(cloud_list):
        header = "%s/%s. %s cloud check" % (i+1, cnt, c)
        header_print(header)
        for plugin in plugins:
            plugin.cloud = c
            plugin.check_begin()
            plugin.check()
            plugin.check_end()
            # the failed flag would be record when do check()
            if plugin.failed:
                plugin.recover()


if __name__ == '__main__':
    main(sys.argv[1:])