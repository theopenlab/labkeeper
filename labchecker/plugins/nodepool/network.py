from labcheck import Plugin
from plugins.recover import Recover
import commands


class NetworkPlugin(Plugin):
    ptype = 'nodepool'
    name = 'network'

    def check(self):
        self.failed = False
        self.reasons = []
        net = 'openstack --os-cloud %s network list -f value -c Name | grep openlab-net' % self.cloud
        res = commands.getoutput(net)
        if "openlab-net" not in res:
            self.failed = True
            self.reasons.append(Recover.NETWORK)
            self.reasons.append(Recover.NETWORK_SUBNET)
            return

        subnet = 'openstack --os-cloud %s subnet list --network openlab-net ' \
                 '-f value -c Name -c Subnet' % self.cloud
        res = commands.getoutput(subnet)
        if "openlab-subnet" not in res:
            self.failed = True
            self.reasons.append(Recover.NETWORK_SUBNET)
            return

        if "192.168.199.0/24" not in res:
            self.failed = True
            self.reasons.append(Recover.NETWORK_SUBNET_CIDR)
            return
