import subprocess

import yaml

from openlabcmd.plugins.base import Plugin


class FlavorPlugin(Plugin):
    ptype = 'nodepool'
    name = 'flavor'

    def check(self):
        self.failed = False
        self.reasons = []
        sg = 'openstack --os-cloud %s flavor list -f yaml -c VCPUs -c RAM -c Disk -c Name' % self.cloud
        res = subprocess.getoutput(sg)
        flavors = yaml.load(res, Loader=yaml.FullLoader)

        # Find 4U8G, 8U8G, 1U2G, 2U2G flavor
        kind = [(4, 8), (8, 8), (1, 2), (2, 2)]
        for k in kind:
            # Generate the flavor names list which VCPUs and RAM match the requirement
            fls = [
                '%s (%sG)' % (fl['Name'], fl['Disk']) for fl in flavors
                if fl['VCPUs'] == k[0] and fl['RAM'] == k[1] * 1024
            ]
            self.reasons.append('- Flavor %sU%sG: %s' % (k[0], k[1], fls if fls else 'not found'))
