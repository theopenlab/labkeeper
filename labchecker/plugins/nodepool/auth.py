from labcheck import Plugin
import yaml
import commands


class AuthPlugin(Plugin):

    type = 'nodepool'
    name = 'Auth Check'
    failed = False
    reasons = []

    def check(self):
        with open('/etc/openstack/clouds.yaml') as f:
            clouds = yaml.load(f)
            op_clouds = [c for c in clouds['clouds']]

        with open('/etc/nodepool/nodepool.yaml') as np:
            clouds = yaml.load(np)
            np_clouds = [c['cloud'] for c in clouds['providers']]

        clouds_list = [self.cloud] if self.cloud in np_clouds else np_clouds
        for cloud in clouds_list:
            self.failed = False
            self.reasons = []
            if cloud not in op_clouds:
                self.failed = True
                self.reasons.append("The clouds.yaml is not set.")

            auth_check = 'openstack --os-cloud %s token issue -f value -c id' % cloud
            res = commands.getoutput(auth_check)
            if "HTTP 401" in res or "not found" in res:
                self.failed = True
                self.reasons.append(res)
            self.print_result(cloud)