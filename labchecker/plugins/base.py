import six
import yaml

class PluginMount(type):
    """
    A plugin mount point derived from:
        http://martyalchin.com/2008/jan/10/simple-plugin-framework/
    Acts as a metaclass which creates anything inheriting from Plugin
    """

    def __init__(cls, name, bases, attrs):
        """Called when a Plugin derived class is imported"""

        if not hasattr(cls, 'plugins'):
            # Called when the metaclass is first instantiated
            cls.plugins = []
        else:
            # Called when a plugin class is imported
            cls.register_plugin(cls)

    def register_plugin(cls, plugin):
        """Add the plugin to the plugin list and perform any registration logic"""

        # create a plugin instance and store it
        # optionally you could just store the plugin class and lazily instantiate
        instance = plugin()

        # save the plugin reference
        cls.plugins.append(instance)

        # apply plugin logic - in this case connect the plugin to blinker signals
        # this must be defined in the derived class
        instance.register_signals()


@six.add_metaclass(PluginMount)
class Plugin(object):
    """A plugin which must provide a register_signals() method"""
    cloud = 'all'
    type = 'Base'
    name = 'Base Check'

    def register_signals(self):
        print("%s has been loaded." % self.__class__.__name__)

    def check_begin(self):
        print("\033[1;30m" + "-" * 10 + self.type + " - " + self.name + "-" * 10 + "\033[0m")

    def check(self):
        pass

    def get_clouds(self):
        with open('/etc/openstack/clouds.yaml') as f:
            clouds = yaml.load(f)
            op_clouds = [c for c in clouds['clouds']]

        with open('/etc/nodepool/nodepool.yaml') as np:
            clouds = yaml.load(np)
            np_clouds = [c['cloud'] for c in clouds['providers']]

        clouds_list = op_clouds and np_clouds

        if self.cloud not in clouds_list + ['all']:
            print("Error: Cloud %s is not found." % self.cloud)
            print("Please use the cloud in %s." % clouds_list)
            exit(2)

        clouds_list = [self.cloud] if self.cloud in clouds_list else clouds_list
        return clouds_list

    def print_result(self, cloud):
        if self.failed:
            print("(%s) " + (40-len(cloud)) * "-" + " \033[1;31m FAILED \033[0m") % cloud
            print("Reason:")
            for r in self.reasons:
                print('%s' % r)
        else:
            print("(%s) " + (40-len(cloud)) * "-" + " \033[1;32m PASSED \033[0m") % cloud