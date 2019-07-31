import subprocess

from openlabcmd.plugins.base import Plugin
from openlabcmd.plugins.recover import Recover


class RouterPlugin(Plugin):
    ptype = 'nodepool'
    name = 'router'

    def __init__(self, cloud, config):
        super(RouterPlugin, self).__init__(cloud, config)
        self.special_need_mapping = {}

    def special_process(self, recover_cmd):
        ext_id = self.special_need_mapping.get('ext-network-id')
        return recover_cmd % (self.cloud, ext_id)

    def check(self):
        self.failed = False
        self.reasons = []
        net = 'openstack --os-cloud %s router show openlab-router' % self.cloud
        ret, res = subprocess.getstatusoutput(net)
        if ret != 0:
            self.failed = True
            if "More than one Openlab router exists" in res:
                self.reasons.append(res)
            else:
                self.reasons.append(Recover.ROUTER)
                self.reasons.append(Recover.ROUTER_SUBNET_INTERFACE)
                self.reasons.append(Recover.ROUTER_EXTERNAL_GW)
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

        self.special_need_mapping['ext-network-id'] = res
        router_gw = 'openstack --os-cloud %s router show ' \
                    'openlab-router | grep %s' % (self.cloud, res)
        ret, res = subprocess.getstatusoutput(router_gw)
        if ret != 0:
            self.failed = True
            self.reasons.append(Recover.ROUTER_EXTERNAL_GW)
            self.special_case_codes.append(Recover.ROUTER_EXTERNAL_GW)
            return
