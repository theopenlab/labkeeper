import datetime
import iso8601
import subprocess

import openstack

from openlabcmd.plugins.base import Plugin


class OrphanResourcePlugin(Plugin):
    ptype = 'nodepool'
    name = 'orphan_resource'

    # This Plugin is only for checking, as it's a dangerous action for each.
    def __init__(self, cloud, config):
        super(OrphanResourcePlugin, self).__init__(cloud, config)
        self.openstack_client = openstack.connect(cloud)
        vm_common_white_list = [element % self.cloud
                                for element in ['%s-openlab-zuul',
                                                '%s-openlab-nodepool',
                                                '%s-openlab-zookeeper']]
        vm_addition_white_list = self.config.get(
            'check', 'vm_white_list', fallback='').replace(' ', '').split(',')
        self.vm_white_list = list(set(vm_common_white_list +
                                      vm_addition_white_list))
        self.volume_white_list = self.config.get(
            'check', 'volume_white_list',
            fallback='').replace(' ', '').split(',')

        self.fip_white_list = self.config.get(
            'check', 'fip_white_list', fallback='').replace(' ', '').split(',')
        self.resource_timeout = int(self.config.get(
            'check', 'resource_timeout_hour', fallback='24'))

    def _is_overtime(self, timestamp):
        if not timestamp:
            return True
        over_time = iso8601.parse_date(
            timestamp) + datetime.timedelta(hours=self.resource_timeout)
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def check(self):
        self.failed = False

        # Get the full map servers from nodepool, we will detemine whether a
        # server is orphan based on this data.
        get_nodepool_map_cmd = (
            "nodepool list | grep openlab | awk '{print $2, $4, $8, $10}' "
            "| sort -t ' ' -k2")
        ret, res = subprocess.getstatusoutput(get_nodepool_map_cmd)

        mapping = {}
        for line in res.split('\n'):
            elements = line.split(' ')
            if elements[1] not in mapping:
                mapping[elements[1]] = {'compute_ids': [elements[2]]}
            else:
                mapping[elements[1]]['compute_ids'].append(elements[2])

        if self.cloud+'-openlab' not in mapping:
            # That means we disable the cloud provider in nodepool
            return

        servers = self.openstack_client.list_servers()

        real_servers = []
        for s in servers:
            skip = False
            # if the vm name startswith the name in white list, will skip.
            for w in self.vm_white_list:
                if s['name'].startswith(w):
                    skip = True
                    break
            if not skip:
                real_servers.append((s['id'], s['name'], s['created']))

        orphan_servers = []
        for server in real_servers:
            if server[0] not in mapping[self.cloud+'-openlab']['compute_ids']:
                if self._is_overtime(server[2]):
                    orphan_servers.append(server[:2])

        volumes = self.openstack_client.list_volumes()
        real_volumes = ([(v['id'], v['name'], v['created_at']) for v in volumes
                        if (v['status'] == 'available' and
                            v['name'] not in self.volume_white_list)]
                        if volumes else [])
        orphan_volumes = []
        for v in real_volumes:
            if self._is_overtime(v[2]):
                orphan_volumes.append(v[:2])

        fips = self.openstack_client.list_floating_ips()
        real_fips = ([(f['id'], f['floating_ip_address'], f.get('created_at'))
                      for f in fips
                      if (not f['port_id'] and
                          f['floating_ip_address'] not in self.fip_white_list)]
                     if fips else [])
        orphan_fips = []
        for f in real_fips:
            if self._is_overtime(f[2]):
                orphan_fips.append(f[:2])

        if orphan_servers or orphan_volumes or orphan_fips:
            self.failed = True
            info = "=============================\n" \
                   "Provider Cloud Name -- %(cloud_name)s - %(result)s\n" \
                   "=============================\n" % {
                'cloud_name': self.cloud, 'result': 'FAIL'}
            if orphan_servers:
                info += "---------------------\n" \
                        "Found Orphan Servers:\n" \
                        "(id, name): %(orphan_servers)s\n" \
                        "count: %(orphan_servers_count)s\n" \
                        "---------------------\n" % {
                    'orphan_servers': orphan_servers,
                    'orphan_servers_count': len(orphan_servers)}
            if orphan_volumes:
                info += "---------------------\n" \
                        "Found Orphan Volumes:\n" \
                        "(id, name): %(orphan_volumes)s\n" \
                        "count: %(orphan_volume_count)s\n" \
                        "---------------------\n" % {
                    'orphan_volumes': orphan_volumes,
                    'orphan_volume_count': len(orphan_volumes)
                }
            if orphan_fips:
                info += "---------------------\n" \
                        "Found Orphan FIPs:\n" \
                        "(id, ip): %(orphan_fips)s\n" \
                        "count: %(orphan_fip_count)s\n" \
                        "---------------------\n" % {
                    'orphan_fips': orphan_fips,
                    'orphan_fip_count': len(orphan_fips)
                }
            self.reasons.append(info)
