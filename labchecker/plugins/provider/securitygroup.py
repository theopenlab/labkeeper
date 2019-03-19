from labcheck import Plugin
import commands


class SecurityGroupPlugin(Plugin):

    type = 'provider'
    name = 'Security Group Check'
    failed = False
    reasons = []

    def check(self):
        clouds = self.get_clouds()
        for cloud in clouds:
            self.failed = False
            self.reasons = []
            tcp_rule = 'openstack --os-cloud %s security group rule list default \
            --ingress -f value \
            -c "IP Protocol" -c "IP Range" -c "Port Range" -c "Ethertype" -c "Remote Security Group" \
            |grep 0.0.0.0 |grep None' % cloud
            res = commands.getoutput(tcp_rule)
            if "tcp 0.0.0.0/0 19885:19885 None" not in res:
                self.failed = True
                self.reasons.append("IPV4 ingress 19885 port check failed.")
            if "tcp 0.0.0.0/0 22:22 None" not in res:
                self.failed = True
                self.reasons.append("IPV4 ingress 22 port check failed.")
            if "icmp 0.0.0.0/0  None" not in res:
                self.failed = True
                self.reasons.append("ICMP check failed.")
            self.print_result(cloud)
