# openlabcmd ha cluster repair requests
RSYNCD_HA_PORT = 873
ZOOKEEPER_HA_PORTS = [2181, 2888, 3888]
MYSQL_HA_PORT = 3306

HA_PORTS = []
for ports in [RSYNCD_HA_PORT, ZOOKEEPER_HA_PORTS, MYSQL_HA_PORT]:
    if isinstance(ports, list):
        HA_PORTS.extend(ports)
    else:
        HA_PORTS.append(ports)

HA_SGs = ['openlab-ha-ports']
