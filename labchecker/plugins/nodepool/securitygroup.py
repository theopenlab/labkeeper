from labcheck import Plugin
from plugins.recover import Recover
import commands


class SecurityGroupPlugin(Plugin):

    ptype = 'nodepool'
    name = 'securitygroup'

    def check(self):
        self.failed = False
        self.reasons = []
        sg = 'openstack --os-cloud %s security group list -f value -c Name | grep openlab-sg' % self.cloud
        res = commands.getoutput(sg)
        if "openlab-sg" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP)
            self.reasons.append(Recover.SECURITY_GROUP_22)
            self.reasons.append(Recover.SECURITY_GROUP_19885)
            self.reasons.append(Recover.SECURITY_GROUP_ICMP)
            return

        tcp_rule = 'openstack --os-cloud %s security group rule list openlab-sg \
        --ingress -f value \
        -c "IP Protocol" -c "IP Range" -c "Port Range" -c "Ethertype" -c "Remote Security Group" \
        |grep 0.0.0.0 |grep None' % self.cloud
        res = commands.getoutput(tcp_rule)
        if "tcp 0.0.0.0/0 19885:19885 None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_19885)
        if "tcp 0.0.0.0/0 22:22 None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_22)
        if "icmp 0.0.0.0/0  None" not in res:
            self.failed = True
            self.reasons.append(Recover.SECURITY_GROUP_ICMP)
