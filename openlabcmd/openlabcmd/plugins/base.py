import subprocess
import six

from openlabcmd.plugins.recover import RECOVER_MAPS
from openlabcmd.utils import _color



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
    ptype = 'Base'
    name = 'Base Check'
    failed = False
    reasons = []
    nocolor = False

    def register_signals(self):
        # print("%s has been loaded." % self.__class__.__name__)
        pass

    def check_begin(self):
        pass

    def check(self):
        pass

    def _print_info(self, header='Reason'):
        if not self.reasons:
            return
        print(header+":")
        for r_code in self.reasons:
            # Translate the r_code to fail reason
            message = RECOVER_MAPS[r_code]['reason'] if r_code in RECOVER_MAPS else r_code
            print('%s' % message)

    def _print_check_line(self, item, passed, width=40):
        if passed:
            print(_color(item + (width - len(item)) * "-") + _color(" PASSED", "g"))
        else:
            print(_color(item + (width - len(item)) * "-") + _color(" FAILED ", "r"))

    def _print_recover_line(self, passed, recover_cmd, res=""):
        if passed:
            print(_color(" PASSED ", "g") + " %s" % recover_cmd)
        else:
            print(_color(" FAILED ", "r") + " %s" % recover_cmd)
        if res:
            print(res)

    def check_end(self, recheck=False):
        item = "[%s] %s" % (self.ptype, self.name)
        if recheck:
            item = "%s (recheck)" % item
        if self.failed:
            self._print_check_line(item, False)
            self._print_info()
        else:
            self._print_check_line(item, True)
            self._print_info(header='Info')

    def recover(self):
        print("Recover:")
        for r_code in self.reasons:
            if r_code in RECOVER_MAPS:
                recover_cmd = RECOVER_MAPS[r_code]['recover'] % self.cloud
                ret, res = subprocess.getstatusoutput(recover_cmd)
                if not ret:
                    self._print_recover_line(True, recover_cmd)
                else:
                    self._print_recover_line(False, recover_cmd, res)

        print("Recheck:")
        self.check()
        self.check_end(recheck=True)
