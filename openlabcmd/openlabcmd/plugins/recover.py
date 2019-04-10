from enum import Enum


class Recover(Enum):
    SECURITY_GROUP = 1
    SECURITY_GROUP_19885 = 2
    SECURITY_GROUP_22 = 3
    SECURITY_GROUP_ICMP = 4
    NETWORK = 5
    NETWORK_SUBNET = 6
    NETWORK_SUBNET_CIDR = 7


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
                   "--network openlab-net --subnet-range=192.168.199.0/24",
        "reason": "- Subnet: openlab-subnet is not found.",
    },
    Recover.NETWORK_SUBNET_CIDR: {
        "recover": "openstack --os-cloud %s subnet create openlab-subnet "
                   "--network openlab-net --subnet-range=192.168.199.0/24",
        "reason": "- Subnet cidr: 192.168.199.0/24 is not found.",
    },
}
