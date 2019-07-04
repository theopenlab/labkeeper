import datetime
import iso8601
import json
import requests
import subprocess
import yaml

from openlabcmd.plugins.base import Plugin

SERVER_WHITE_LIST = [
    '%s-openlab-zuul', '%s-openlab-nodepool', '%s-openlab-zookeeper']
OPENSTACK_CLOUD_CFG_PATH = '/etc/openstack/clouds.yaml'
# DAYs
RESOURCE_TIMEOUT = 1


class OrphanResourcePlugin(Plugin):

    # This Plugin is only for checking, as it's a dangerous action for each.
    ptype = 'nodepool'
    name = 'OrphanResource'

    def _get_endpoint_and_token(self):
        ccf = yaml.load(open(OPENSTACK_CLOUD_CFG_PATH))
        auth_dict = ccf['clouds'][self.cloud]['auth']
        keystone_version = ccf['clouds'][self.cloud]['identity_api_version']
        cinder_version = ccf['clouds'][self.cloud]['volume_api_version']
        neutron_version = ccf['clouds'][self.cloud]['network_api_version']
        auth_url = auth_dict['auth_url']

        if '2' not in keystone_version and (
                '/v%s' % keystone_version in auth_url or '/v%s.0' %
                keystone_version in
                auth_url):
            url = auth_url + '/auth/tokens'
        elif '2' in keystone_version:
            if ('/v%s' % keystone_version in auth_url or '/v%s.0' %
                    keystone_version in
                    auth_url):
                url = auth_url + '/tokens'
            else:
                url = auth_url + '/v%s' % \
                      keystone_version + '/tokens'
        else:
            url = auth_url + '/v%s' % \
                  keystone_version + '/auth/tokens'

        headers = {'Content-Type': 'application/json'}
        user_domain = {}
        if auth_dict.get('user_domain_name'):
            user_domain["name"] = auth_dict.get(
                'user_domain_name')
        elif auth_dict.get('user_domain_id'):
            user_domain['id'] = auth_dict.get(
                'user_domain_id')

        project_domain = {}
        if auth_dict.get('project_domain_name'):
            project_domain['name'] = auth_dict.get(
                'project_domain_name')
        elif auth_dict.get('project_domain_id'):
            project_domain['id'] = auth_dict.get(
                'project_domain_id')
        if '2' not in keystone_version:
            data = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": auth_dict['username'],
                                "domain": user_domain,
                                "password": auth_dict['password']
                            }
                        }
                    },
                    "scope": {
                        "project": {
                            "name": auth_dict['project_name'],
                            "domain": project_domain
                        }
                    }
                }
            }
        else:
            data = {
                "auth": {
                    "tenantName": auth_dict['project_name'],
                    "passwordCredentials": {
                        "username": auth_dict['username'],
                        "password": auth_dict['password']
                    }
                }
            }
        json_data = json.dumps(data).encode('utf8')
        resp = requests.post(url=url, data=json_data, headers=headers)
        body = json.loads(resp.text)
        need_info = {}
        if '2' not in keystone_version:
            token = resp.headers['X-Subject-Token']
            for endpoints in body['token']['catalog']:
                if endpoints['name'] in ['cinderv%s' % cinder_version,
                                         'neutron', 'nova']:
                    for endpoint in endpoints['endpoints']:
                        if endpoint['interface'] == 'public' and endpoint[
                            'region'] == ccf['clouds'][self.cloud][
                            'region_name']:
                            public_url = endpoint['url']
                            break
                    if 'cinderv%s' % cinder_version == endpoints['name']:
                        need_info['cinder'] = public_url
                    elif 'neutron' == endpoints['name']:
                        need_info['neutron'] = public_url + '/v%s' % ccf[
                            'clouds'][self.cloud]['network_api_version']
                    elif 'nova' == endpoints['name']:
                        need_info['nova'] = public_url
        else:
            token = body["access"]["token"]["id"]

            for endpoints in body["access"]["serviceCatalog"]:
                if endpoints['name'] in ['cinderv%s' % cinder_version,
                                         'neutron', 'nova']:
                    for endpoint in endpoints['endpoints']:
                        public_url = endpoint['publicURL']
                    if 'cinderv%s' % cinder_version == endpoints['name']:
                        need_info['cinder'] = public_url
                    elif 'neutron' == endpoints['name']:
                        need_info['neutron'] = public_url + '/v%s' % ccf[
                            'clouds'][self.cloud]['network_api_version']
                    elif 'nova' == endpoints['name']:
                        need_info['nova'] = public_url
        need_info['token'] = token
        return need_info

    def _send_request(self, api_info, req_url):
        token = api_info['token']
        headers = {'Accept': 'application/json',
                   'X-Auth-Token': token}
        resp = requests.get(req_url, headers=headers)
        body = json.loads(resp.text)
        return body

    def _get_fip_res(self, api_info):
        req_url = api_info['neutron'] + '/floatingips'
        body = self._send_request(api_info, req_url)
        return body['floatingips']

    def _get_volume_res(self, api_info):
        req_url = api_info['cinder'] + '/volumes/detail'
        body = self._send_request(api_info, req_url)
        return body['volumes']

    def _get_server_res(self, api_info):
        req_url = api_info['nova'] + '/servers/detail'
        body = self._send_request(api_info, req_url)
        return body['servers']

    def _is_check_heart_beat_overtime(self, timestamp):
        if not timestamp:
            return True
        timeout = RESOURCE_TIMEOUT
        over_time = iso8601.parse_date(
            timestamp) + datetime.timedelta(days=timeout)
        current_time = datetime.datetime.utcnow().replace(tzinfo=iso8601.UTC)
        return current_time > over_time

    def check(self):
        self.failed = False
        server_white_list = [elemnt % self.cloud
                             for elemnt in SERVER_WHITE_LIST]

        api_info = self._get_endpoint_and_token()
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
                    'compute_ids': [elements[2]],
                    'floatingips': [elements[3]]}
            else:
                mapping[elements[1]]['compute_ids'].append(elements[2])
                mapping[elements[1]]['floatingips'].append(elements[3])

        if self.cloud+'-openlab' not in mapping:
            # That means we disable the cloud provider in nodepool
            return

        servers = self._get_server_res(api_info)
        real_servers = [(s['id'], s['name'], s['created']) for s in servers
                        if s['name'] not in server_white_list] if servers else []
        real_compute_ids = []
        for server in real_servers:
            if self._is_check_heart_beat_overtime(server[2]):
                real_compute_ids.append(server[0])
        orphan_servers = set(real_compute_ids) - set(
            mapping[self.cloud+'-openlab']['compute_ids'])

        volumes = self._get_volume_res(api_info)
        real_volumes = [(v['id'], v['name'], v['created_at']) for v in volumes
                        if v['status'] == 'available'] if volumes else []
        orphan_volumes = []
        for v in real_volumes:
            if self._is_check_heart_beat_overtime(v[2]):
                orphan_volumes.append(v[0])

        fips = self._get_fip_res(api_info)
        real_fips = [(f['id'], f['floating_ip_address'], f.get('created_at'))
                     for f in fips if not f['port_id']] if fips else []
        orphan_fips = []
        for f in real_fips:
            if self._is_check_heart_beat_overtime(f[2]):
                orphan_fips.append(f[0])

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
