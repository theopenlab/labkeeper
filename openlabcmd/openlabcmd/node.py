import datetime
import json

import pytz


class NodeStatus(object):
    INITIALIZING = 'initializing'
    UP = 'up'
    DOWN = 'down'
    MAINTAINING = 'maintaining'


class Node(object):
    def __init__(self, name, role, type, ip, heartbeat=None, alarmed=None,
                 status=None, created_at=None, updated_at=None,
                 switch_status=None, **kwargs):
        self.name = name
        self.role = role
        self.type = type
        self.ip = ip
        self.heartbeat = heartbeat or '0'
        self.alarmed = alarmed or False
        self.status = status or NodeStatus.INITIALIZING
        self.created_at = created_at
        self.updated_at = updated_at
        self.switch_status = switch_status

    def to_zk_bytes(self):
        node_dict = {
            'name': self.name,
            'role': self.role,
            'type': self.type,
            'ip': self.ip,
            'heartbeat': self.heartbeat,
            'alarmed': self.alarmed,
            'status': self.status,
            'switch_status': self.switch_status
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
        node_dict = json.loads(zk_bytes[0].decode('utf8'))
        # ctime and mtime is millisecond in zk. Convert to second.
        ctime, mtime = zk_bytes[1].ctime / 1000, zk_bytes[1].mtime / 1000
        node_dict['created_at'] = datetime.datetime.fromtimestamp(
                ctime, pytz.utc).isoformat()
        node_dict['updated_at'] = datetime.datetime.fromtimestamp(
                mtime, pytz.utc).isoformat()
        return cls(**node_dict)
