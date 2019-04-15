import json


class NodeStatus(object):
    INITIALIZING = 'initializing'
    UP = 'up'
    DOWN = 'down'
    MAINTAINING = 'maintaining'


class Node(object):
    def __init__(self, name, role, type, ip, heartbeat=None, alarmed=None,
                 status=None):
        self.name = name
        self.role = role
        self.type = type
        self.ip = ip
        if not heartbeat:
            self.heartbeat = 0
        if not alarmed:
            self.alarmed = False
        if not status:
            self.status = NodeStatus.INITIALIZING

    def to_zk_data(self):
        node_dict = {
            'name': self.name,
            'role': self.role,
            'type': self.type,
            'ip': self.ip,
            'heartbeat': self.heartbeat,
            'alarmed': self.alarmed,
            'status': self.status
        }
        return json.dumps(node_dict).encode('utf8')

    @classmethod
    def from_dict(cls, name, role, n_type, ip, heartbeat=None, alarmed=None,
                  status=None):
        return cls(name, role, n_type, ip, heartbeat, alarmed, status)
