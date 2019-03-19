from plugins.base import Plugin
import sys
import getopt


def usage():
    print("Usage: labchecker [--type <plugin-type>] [--cloud <cloud-provider-name>]")
    print("optional arguments:")
    print("\t--help\t\tShow help message and exit.")
    print("\t--type\t\tSpecify a plugin type, like 'provider', 'all'(default)")
    print("\t--cloud\t\tSpecify a cloud provider, like 'otc', 'vexxhost', 'all'(default).")
    print("Exmaple:")
    print("labchecker check --type all --cloud all")
    print("labchecker check --type provider --cloud vexxhost")


def main(argv):
    cloud = 'all'
    type = ''

    try:
        opts, args = getopt.getopt(argv, "ht:c:", ["help", "cloud=", "type="])
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
            type = a

    if type:
        for plugin in Plugin.plugins:
            if plugin.type == type:
                plugin.cloud = cloud
                plugin.check_begin()
                plugin.check()
    else:
        for plugin in Plugin.plugins:
            plugin.cloud = cloud
            plugin.check_begin()
            plugin.check()



if __name__ == '__main__':
    main(sys.argv[1:])