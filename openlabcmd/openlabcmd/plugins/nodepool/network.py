import subprocess

from openlabcmd.plugins.base import Plugin
from openlabcmd.plugins.recover import Recover


class NetworkPlugin(Plugin):
    ptype = 'nodepool'
    name = 'network'

    def check(self):
        self.failed = False
        self.reasons = []
        net = 'openstack --os-cloud %s network show openlab-net' % self.cloud
        ret, res = subprocess.getstatusoutput(net)
        if ret != 0:
            self.failed = True
            if "More than one Network exists" in res:
                self.reasons.append(res)
            else:
                self.reasons.append(Recover.NETWORK)
                self.reasons.append(Recover.NETWORK_SUBNET)
            return

        subnet = 'openstack --os-cloud %s subnet list --network openlab-net ' \
                 '-f value -c Name -c Subnet' % self.cloud
        ret, res = subprocess.getstatusoutput(subnet)
        if ret != 0 and "More than one Subnet exists" in res:
            self.failed = True
            self.reasons.append(res)
            return

        # get subnet of openlab-net successfully, check subnet
        if "openlab-subnet 192.168.199.0/24" not in res:
            self.failed = True
            self.reasons.append(Recover.NETWORK_SUBNET)
            return
