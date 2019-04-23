import json

# NOTE(wxy): Add more if needed.
service_mapping = {
    'master_service': {
        'zuul': {
            'necessary': ['zuul-scheduler', 'zuul-executor', 'zuul-web',
                          'gearman', 'mysql', 'apache'],
            'unnecessary': ['zuul-merger', 'zuul-fingergw', 'zuul-timer-tasks']
        },
        'nodepool': {
            'necessary': ['nodepool-launcher'],
            'unnecessary': ['nodepool-timer-tasks', 'nodepool-builder',
                            'zookeeper']
        }
    },
    'slave_service': {
        'zuul': {
            'necessary': [],
            'unnecessary': ['mysql', 'rsync']
        },
        'nodepool': {
            'necessary': [],
            'unnecessary': ['zookeeper', 'rsync']
        }
    },
    'zookeeper_service': {
        'zookeeper': {
            'necessary': [],
            'unnecessary': ['zookeeper']
        }
    },
}

MIXED_SERVICE = ['mysql', 'zookeeper']


class ServiceStatus(object):
    INITIALIZING = 'initializing'
    UP = 'up'
    DOWN = 'down'
    RESTARTING = 'restarting'

    @property
    def all_status(self):
        return [self.INITIALIZING, self.UP, self.DOWN, self.RESTARTING]


class Service(object):
    def __init__(self, name, node_role, alarmed=None, alarmed_at=None,
                 restarted=None, restarted_at=None, is_necessary=None,
                 status=None, **kwargs):
        self.name = name
        self.node_role = node_role
        self.alarmed = alarmed or False
        self.alarmed_at = alarmed_at
        self.restarted = restarted or False
        self.restarted_at = restarted_at
        self.is_necessary = is_necessary
        self.status = status or ServiceStatus.INITIALIZING

    def to_zk_data(self):
        node_dict = {
            'name': self.name,
            'alarmed': self.alarmed,
            'alarmed_at': self.alarmed_at,
            'restarted': self.restarted,
            'restarted_at': self.restarted_at,
            'is_necessary': self.is_necessary,
            'node_role': self.node_role,
            'status': self.status
        }
        return json.dumps(node_dict).encode('utf8')

    @ classmethod
    def from_dict(cls, d):
        return cls(**d)


class NecessaryService(Service):
    def __init__(self, name, node_role):
        super(NecessaryService, self).__init__(name, node_role)
        self.is_necessary = True


class UnnecessaryService(Service):
    def __init__(self, name, node_role):
        super(UnnecessaryService, self).__init__(name, node_role)
        self.is_necessary = False
