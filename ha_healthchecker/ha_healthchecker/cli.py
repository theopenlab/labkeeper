from ha_healthchecker import process


def main():
    # ZK client config file location.
    conf = "/etc/openlab/openlab.conf"
    process.HealthChecker(conf).run()
