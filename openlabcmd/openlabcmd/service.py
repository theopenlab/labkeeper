import json

# NOTE(wxy): Add more if needed.
service_mapping = {
    'master_service': {
        'necessary': ['zuul-scheduler', 'zuul-executor', 'zuul-web', 'gearman',
                      'mysql', 'apache', 'nodepool-launcher'],
        'unnecessary': ['zuul-merger', 'zuul-fingergw', 'zuul-timer-tasks',
                        'nodepool-timer-tasks', 'nodepool-builder',
                        'zookeeper']
    },
    'slave_service': {
        'necessary': [],
        'unnecessary': ['mysql', 'rsync', 'zookeeper']
    },
    'zookeeper_service': {
        'necessary': [],
        'unnecessary': ['zookeeper']
    },
}

MIXED_SERVICE = ['mysql', 'zookeeper']


class ServiceStatus(object):
    INITIALIZING = 'initializing'
    UP = 'up'
    DOWN = 'down'
    Restarting = 'restarting'


class Service(object):
    def __init__(self, name, node_role):
        self.name = name
        self.alarmed = False
        self.alarmed_at = None
        self.updated_at = None
        self.restarted = False
        self.restarted_at = None
        self.is_necessary = None
        self.node_role = node_role
        self.status = ServiceStatus.INITIALIZING

    def to_zk_data(self):
        node_dict = {
            'name': self.name,
            'alarmed': self.alarmed,
            'alarmed_at': self.alarmed_at,
            'updated_at': self.updated_at,
            'restarted': self.restarted,
            'restarted_at': self.restarted_at,
            'is_necessary': self.is_necessary,
            'node_role': self.node_role,
            'status': self.status
        }
        return json.dumps(node_dict).encode('utf8')


class NecessaryService(Service):
    def __init__(self, name, node_role):
        super(NecessaryService, self).__init__(name, node_role)
        self.is_necessary = True


class UnnecessaryService(Service):
    def __init__(self, name, node_role):
        super(UnnecessaryService, self).__init__(name, node_role)
        self.is_necessary = False
