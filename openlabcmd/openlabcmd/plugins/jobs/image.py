import subprocess

from openlabcmd.plugins.base import Plugin


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
        if "cirros" not in res:
            self.failed = True
            self.reasons.append("- Image: cirros image not found.")
