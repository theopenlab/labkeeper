#!/usr/bin/python3
import base64
import configparser
import logging
from logging import handlers
import os

from apscheduler.schedulers import blocking
from openlabcmd import zk

from ha_healthchecker.action import refresher
from ha_healthchecker.action import fixer
from ha_healthchecker.action import switcher


class ClusterConfig(object):
    BASE64_ENCODED_OPTIONS = ['github_user_password', 'dns_provider_token',
                              'github_user_token']

    def __init__(self, zk_client):
        self._init_options(zk_client)
        self._set_log()

    def _init_options(self, zk_client):
        for attr, value in zk_client.list_configuration().items():
            if value is None:
                raise Exception("Openlab HA related options haven't been "
                                "initialized, try 'openlab ha config list'"
                                " to get more detail.")
            if attr in self.BASE64_ENCODED_OPTIONS:
                value = base64.b64decode(value).decode("utf-8").split('\n')[0]
            setattr(self, attr, value)

    def _set_log(self):
        file_dir = os.path.split(self.logging_path)[0]
        if not os.path.isdir(file_dir):
            os.makedirs(file_dir)
        if not os.path.exists(self.logging_path):
            os.system('touch %s' % self.logging_path)
        if not self.logging_level.upper() in ['DEBUG', 'INFO', 'ERROR']:
            # use the default level
            self.logging_level = 'DEBUG'
        rt_handler = handlers.RotatingFileHandler(
            self.logging_path, maxBytes=10*1024*1024, backupCount=5)
        logging.basicConfig(
            format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
            datefmt='%H:%M:%S',
            level=getattr(logging, self.logging_level.upper()),
            handlers=[rt_handler])
        self.LOG = logging.getLogger("OpenLab HA HealthChecker")

    def refresh(self, zk_client):
        for attr, value in zk_client.list_configuration().items():
            if attr in self.BASE64_ENCODED_OPTIONS:
                value = base64.b64decode(value).decode("utf-8").split('\n')[0]
            setattr(self, attr, value)
        self._set_log()


class HealthChecker(object):
    def __init__(self, config_file):
        zk_cfg = configparser.ConfigParser()
        zk_cfg.read(config_file)
        self.zk_client = zk.ZooKeeper(zk_cfg)
        self.cluster_config = None

    def _action(self):
        if self.zk_client.client is None:
            self.zk_client.connect()
        self.cluster_config.refresh(self.zk_client)
        refresher.Refresher(self.zk_client, self.cluster_config).run()
        fixer.Fixer(self.zk_client, self.cluster_config).run()
        switcher.Switcher(self.zk_client, self.cluster_config).run()
        self.zk_client.disconnect()

    def run(self):
        self.zk_client.connect()
        self.cluster_config = ClusterConfig(self.zk_client)

        job_scheduler = blocking.BlockingScheduler()
        job_scheduler.add_job(self._action, 'interval', seconds=120)
        job_scheduler.start()
