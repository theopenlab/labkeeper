from labcheck import Plugin
import commands


class ImagePlugin(Plugin):

    type = 'provider'
    name = 'Image Check'
    failed = False
    reasons = []

    def check(self):
        clouds = self.get_clouds()
        for cloud in clouds:
            self.failed = False
            self.reasons = []
            image_check = 'openstack --os-cloud %s image list ' \
                          '-c "Name" -c "Status" -f value | grep cirros' % cloud
            res = commands.getoutput(image_check)
            if "cirros" not in res:
                self.failed = True
                self.reasons.append("Cirros image not found.")
            self.print_result(cloud)