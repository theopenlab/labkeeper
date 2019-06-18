import subprocess

from openlabcmd.plugins.base import Plugin
from openlabcmd.plugins.recover import Recover


class SecurityGroupPlugin(Plugin):

    ptype = 'nodepool'
    name = 'securitygroup'

    def check(self):
        self.failed = False
        self.reasons = []
        sg = 'openstack --os-cloud %s security group show openlab-sg' % self.cloud
        ret, res = subprocess.getstatusoutput(sg)
        if ret != 0:
            self.failed = True
            if "More than one SecurityGroup exists" in res:
                self.reasons.append(res)
            else:
                self.reasons.append(Recover.SECURITY_GROUP)
                self.reasons.append(Recover.SECURITY_GROUP_22)
                self.reasons.append(Recover.SECURITY_GROUP_19885)
                self.reasons.append(Recover.SECURITY_GROUP_ICMP)
            return

        tcp_rule = 'openstack --os-cloud %s security group rule list openlab-sg \
        --ingress -f value \
        -c "IP Protocol" -c "IP Range" -c "Port Range" -c "Ethertype" -c "Remote Security Group" \
        |grep 0.0.0.0 |grep None' % self.cloud
        res = subprocess.getoutput(tcp_rule)
        if "tcp 0.0.0.0/0 19885:19885 None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_19885)
        if "tcp 0.0.0.0/0 22:22 None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_22)
        if "icmp 0.0.0.0/0  None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_ICMP)
