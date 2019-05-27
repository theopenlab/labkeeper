import subprocess

from openlabcmd.plugins.base import Plugin
from openlabcmd.plugins.recover import Recover


class ImagePlugin(Plugin):

    ptype = 'jobs'
    name = 'image'

    def check(self):
        self.failed = False
        self.reasons = []
        # find 'cirros' in openstack image list
        image_check = 'openstack --os-cloud %s image list ' \
                      '-c "Name" -c "Status" -f value | grep cirros' % self.cloud
        res = subprocess.getoutput(image_check)
        if "cirros-0.3.5" not in res:
            self.failed = True
            self.reasons.append(Recover.IMAGE_CIRROS_035)
        if "cirros-0.4.0" not in res:
            self.failed = True
            self.reasons.append(Recover.IMAGE_CIRROS_040)
