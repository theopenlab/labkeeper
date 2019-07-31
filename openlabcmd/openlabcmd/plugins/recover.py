from enum import Enum


class Recover(Enum):
    SECURITY_GROUP = 1
    SECURITY_GROUP_19885 = 2
    SECURITY_GROUP_22 = 3
    SECURITY_GROUP_ICMP = 4
    NETWORK = 5
    NETWORK_SUBNET = 6
    NETWORK_SUBNET_CIDR = 7
    ROUTER = 8
    ROUTER_SUBNET_INTERFACE = 9
    ROUTER_EXTERNAL_GW = 10


RECOVER_MAPS = {
    Recover.SECURITY_GROUP: {
        "recover": "openstack --os-cloud %s security group create openlab-sg",
        "reason": "- SecGroup: The openlab-sg is not found.",
    },
    Recover.SECURITY_GROUP_19885: {
        "recover": "openstack --os-cloud %s security group rule create openlab-sg "
                   "--ingress --ethertype IPv4 --dst-port 19885:19885 --protocol tcp",
        "reason": "- Rule: TCP ingress 19885 rule is not set.",
    },
    Recover.SECURITY_GROUP_22: {
        "recover": "openstack --os-cloud %s security group rule create openlab-sg "
                   "--ingress --ethertype IPv4 --dst-port 22:22 --protocol tcp",
        "reason": "- Rule: TCP ingress 22 rule is not set.",
    },
    Recover.SECURITY_GROUP_ICMP: {
        "recover": "openstack --os-cloud %s security group rule create openlab-sg "
                   "--ingress --ethertype IPv4 --protocol icmp",
        "reason": "- Rule: ICMP rule is not set.",
    },
    Recover.NETWORK: {
        "recover": "openstack --os-cloud %s network create openlab-net",
        "reason": "- Network: openlab-net is not found.",
    },
    Recover.NETWORK_SUBNET: {
        "recover": "openstack --os-cloud %s subnet create openlab-subnet "
                   "--network openlab-net --subnet-range=192.168.0.0/24",
        "reason": "- Subnet: openlab-subnet is not found.",
    },
    Recover.NETWORK_SUBNET_CIDR: {
        "recover": "openstack --os-cloud %s subnet create openlab-subnet "
                   "--network openlab-net --subnet-range=192.168.0.0/24",
        "reason": "- Subnet cidr: 192.168.0.0/24 is not found.",
    },
    Recover.ROUTER: {
        "recover": "openstack --os-cloud %s router create openlab-router "
                   "--ha --enable",
        "reason": "- Router: openlab-router is not found.",
    },
    Recover.ROUTER_SUBNET_INTERFACE: {
        "recover": "openstack --os-cloud %s router add subnet openlab-router "
                   "openlab-subnet",
        "reason": "- Router subnet interface: openlab-subnet doesn't attach "
                  "on openlab-router.",
    },
    Recover.ROUTER_EXTERNAL_GW: {
        "recover": "openstack --os-cloud %s openstack router set "
                   "openlab-router --external-gateway %s ",
        "reason": "- Router external gateway: openlab-subnet doesn't attach "
                  "on openlab-router.",
    },
}
