import datetime
import json

import pytz

# NOTE(wxy): Add more if needed.
service_mapping = {
    'master': {
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
    'slave': {
        'zuul': {
            'necessary': [],
            'unnecessary': ['mysql', 'rsync']
        },
        'nodepool': {
            'necessary': [],
            'unnecessary': ['zookeeper', 'rsync']
        }
    },
    'zookeeper': {
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
    ERROR = 'error'

    @property
    def all_status(self):
        return [self.INITIALIZING, self.UP, self.DOWN, self.RESTARTING,
                self.ERROR]


class Service(object):
    def __init__(self, name, node_name, alarmed=None,
                 alarmed_at=None, restarted=None, restarted_at=None,
                 is_necessary=None, status=None, created_at=None,
                 updated_at=None, **kwargs):
        self.name = name
        self.node_name = node_name
        self.alarmed = alarmed or False
        self.alarmed_at = alarmed_at
        self.restarted = restarted or False
        self.restarted_at = restarted_at
        self.is_necessary = is_necessary
        self.status = status or ServiceStatus.INITIALIZING
        self.created_at = created_at
        self.updated_at = updated_at

    def to_zk_bytes(self):
        node_dict = {
            'name': self.name,
            'node_name': self.node_name,
            'alarmed': self.alarmed,
            'alarmed_at': self.alarmed_at,
            'restarted': self.restarted,
            'restarted_at': self.restarted_at,
            'is_necessary': self.is_necessary,
            'status': self.status
        }
        return json.dumps(node_dict).encode('utf8')

    def to_dict(self):
        return self.__dict__

    def update(self, update_dict):
        for k, v in update_dict.items():
            try:
                getattr(self, k)
                setattr(self, k, v)
            except AttributeError:
                pass

    @classmethod
    def from_zk_bytes(cls, zk_bytes):
        service_dict = json.loads(zk_bytes[0].decode('utf8'))
        # mtime is millisecond in zk. Convert to second.
        mtime = zk_bytes[1].mtime / 1000
        service_dict['updated_at'] = datetime.datetime.fromtimestamp(
                mtime, pytz.utc).isoformat()
        return cls(**service_dict)


class NecessaryService(Service):
    def __init__(self, name, node_name):
        super(NecessaryService, self).__init__(name, node_name)
        self.is_necessary = True


class UnnecessaryService(Service):
    def __init__(self, name, node_name):
        super(UnnecessaryService, self).__init__(name, node_name)
        self.is_necessary = False
