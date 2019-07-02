import copy
import subprocess

from openlabcmd.plugins.base import Plugin

SERVER_WHITE_LIST = [
    '%s-openlab-zuul', '%s-openlab-nodepool', '%s-openlab-zookeeper']


class OrphanResourcePlugin(Plugin):

    # This Plugin is only for checking, as it's a dangerous action for each.
    ptype = 'nodepool'
    name = 'OrphanResource'

    def check(self):
        self.failed = False
        if self.reasons:
            self.reasons.pop()
        server_white_list = [elemnt % self.cloud
                             for elemnt in copy.deepcopy(SERVER_WHITE_LIST)]

        # For floatingip, we will check whether a fip didn't associated with a
        # neutron port.
        get_fip_cmd = ("openstack --os-cloud %s floating ip list "
                       "-c 'ID' -c 'Floating IP Address' -c 'Port' | "
                       "egrep '[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-"
                       "[a-z0-9]{4}-[a-z0-9]{12}' | awk '{print $2, $4, $6}' "
                       "| grep None | awk '{print $1}'")
        # For volume, we just check the available status volumes, as we cannot
        # know whether a in-use volume is used for any purpose.
        get_volume_cmd = (
            "openstack --os-cloud %s volume list -c 'ID' -c 'Status' | "
            "egrep '[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-"
            "[a-z0-9]{12}' | grep available | awk '{print $2}'")
        # For servers, we will get all servers for a provider, and skip the
        # online openlab env servers.
        get_server_cmd = (
            "openstack --os-cloud %s server list -c 'ID' -c 'Name' | "
            "egrep '[a-z0-9]{8}-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}-"
            "[a-z0-9]{12}' | awk '{print $2, $4}'")
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
                mapping[elements[1]] = {
                    'nodepool_compute_mapping':
                        [{'nodepool_id': elements[0],
                          'compute_id': elements[2],
                          'floatingip': elements[3]}],
                    'compute_ids': [elements[2]],
                    'floatingips': [elements[3]]}
            else:
                mapping[elements[1]]['nodepool_compute_mapping'].append(
                    {'nodepool_id': elements[0], 'compute_id': elements[2],
                     'floatingip': elements[3]})
                mapping[elements[1]]['compute_ids'].append(elements[2])
                mapping[elements[1]]['floatingips'].append(elements[3])

        if self.cloud+'-openlab' not in mapping:
            # That means we disable the cloud provider in nodepool
            return

        ret, res = subprocess.getstatusoutput(get_server_cmd % self.cloud)
        real_compute_ids = []
        real_compute_id_name_tuples = res.split('\n') if res else []
        for real_compute_id_name in real_compute_id_name_tuples:
            compute_id, name = real_compute_id_name.split(' ')
            if name in server_white_list:
                continue
            real_compute_ids.append(compute_id)
        orphan_servers = set(real_compute_ids) - set(
            mapping[self.cloud+'-openlab']['compute_ids'])

        ret, res = subprocess.getstatusoutput(get_volume_cmd % self.cloud)
        orphan_volumes = res.split('\n') if res else []

        ret, res = subprocess.getstatusoutput(get_fip_cmd % self.cloud)
        orphan_fips = res.split('\n') if res else []

        if orphan_servers or orphan_volumes or orphan_fips:
            self.failed = True
            info = "=============================\n" \
                   "Provider Cloud Name -- %(cloud_name)s - %(result)s\n" \
                   "=============================\n" % {
                'cloud_name': self.cloud, 'result': 'FAIL'}
            if orphan_servers:
                info += "---------------------\n" \
                        "Found Orphan Servers:\n" \
                        "ids: %(orphan_servers)s\n" \
                        "count: %(orphan_servers_count)s\n" \
                        "---------------------\n" % {
                    'orphan_servers': orphan_servers,
                    'orphan_servers_count': len(orphan_servers)}
            if orphan_volumes:
                info += "---------------------\n" \
                        "Found Orphan Volumes:\n" \
                        "ids: %(orphan_volumes)s\n" \
                        "count: %(orphan_volume_count)s\n" \
                        "---------------------\n" % {
                    'orphan_volumes': orphan_volumes,
                    'orphan_volume_count': len(orphan_volumes)
                }
            if orphan_fips:
                info += "---------------------\n" \
                        "Found Orphan FIPs:\n" \
                        "ids: %(orphan_fips)s\n" \
                        "count: %(orphan_fip_count)s\n" \
                        "---------------------\n" % {
                    'orphan_fips': orphan_fips,
                    'orphan_fip_count': len(orphan_fips)
                }
            self.reasons.append(info)
