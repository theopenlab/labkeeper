import subprocess

from openlabcmd.plugins.base import Plugin


class QuotaPlugin(Plugin):

    ptype = 'nodepool'
    name = 'quota'

    def check(self):
        self.failed = False
        self.reasons = []

        # print basic quota info
        quota = 'openstack --os-cloud %s quota show -f yaml ' \
                '-c cores -c ram -c volumes -c networks -c subnets -c floating-ips' % self.cloud
        res = subprocess.getoutput(quota)

        self.reasons.append(res)
