import subprocess

from openlabcmd.plugins.base import Plugin


class AuthPlugin(Plugin):
    ptype = 'nodepool'
    name = 'auth'

    def __init__(self, cloud, config):
        super(AuthPlugin, self).__init__(cloud, config)

    def check(self):
        self.failed = False
        self.reasons = []

        auth_check = 'openstack --os-cloud %s token issue -f value -c id' % self.cloud
        res = subprocess.getoutput(auth_check)
        if "HTTP 401" in res or "not found" in res:
            self.failed = True
            self.reasons.append(res)
