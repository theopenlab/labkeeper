import subprocess

from openlabcmd.plugins.base import Plugin
from openlabcmd.plugins.recover import Recover


class NetworkPlugin(Plugin):
    ptype = 'nodepool'
    name = 'network'

    def __init__(self, cloud, config):
        super(NetworkPlugin, self).__init__(cloud, config)

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
        if "openlab-subnet 192.168.0.0/24" not in res:
            self.failed = True
            self.reasons.append(Recover.NETWORK_SUBNET)
            return

        net = 'openstack --os-cloud %s router show openlab-router' % self.cloud
        ret, res = subprocess.getstatusoutput(net)
        if ret != 0:
            self.failed = True
            if "More than one Openlab router exists" in res:
                self.reasons.append(res)
            else:
                self.reasons.append(Recover.ROUTER)
                self.reasons.append(Recover.ROUTER_SUBNET_INTERFACE)
            return

        subnet_id = 'openstack --os-cloud %s subnet show openlab-subnet -f ' \
                    'value -c id' % self.cloud
        ret, res = subprocess.getstatusoutput(subnet_id)
        if ret != 0 and "More than one Subnet exists" in res:
            self.failed = True
            self.reasons.append(res)
            return

        subnet_interface = 'openstack --os-cloud %s router show ' \
                           'openlab-router | grep %s' % (self.cloud, res)
        ret, res = subprocess.getstatusoutput(subnet_interface)
        if ret != 0:
            self.failed = True
            self.reasons.append(Recover.ROUTER_SUBNET_INTERFACE)
            return

        external_net = 'openstack --os-cloud %s network list --external ' \
                       '-f value -c ID' % self.cloud
        ret, res = subprocess.getstatusoutput(external_net)
        if ret != 0:
            self.failed = True
            self.reasons.append('Failed to get a external network.')
            return

        ext_net_id = res
        router_gw = 'openstack --os-cloud %s router show ' \
                    'openlab-router | grep %s' % (self.cloud, res)
        ret, res = subprocess.getstatusoutput(router_gw)
        if ret != 0:
            self.failed = True
            self.reasons.append(Recover.ROUTER_EXTERNAL_GW)
            self.internal_recover_args_map[Recover.ROUTER_EXTERNAL_GW] = [
                ext_net_id]
            return
