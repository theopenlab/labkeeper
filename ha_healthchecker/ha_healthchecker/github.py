import datetime
from urllib import parse

from github import Github
from html.parser import HTMLParser
import requests


class GithubAction(object):
    def __init__(self, cluster_config):
        self.cluster_config = cluster_config
        self.token = cluster_config.github_user_token
        self.repo_name = cluster_config.github_repo
        self.app_name = cluster_config.github_app_name
        self.repo = Github(login_or_token=self.token).get_repo(self.repo_name)

    def _format_body_for_issue(self, issuer_node, issue_type, affect_node=None,
                               affect_services=None):
        title = "[OpenLab HA HealthCheck][%s] Alarm" \
                % datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        body = "Issuer Host Info:\n" \
               "===============\n" \
               "  name: %(name)s\n" \
               "  role: %(role)s\n" \
               "  ip: %(ip)s\n" % {
                   "name": issuer_node.name,
                   "role": issuer_node.role,
                   "ip": issuer_node.ip
               }

        body += "\nProblem:\n" \
                "===============\n"
        if issue_type == 'service_down':
            body += "The service %(service_name)s on the node " \
                    "%(name)s (IP %(ip)s) is done.\n" % (
                        {'service_name': affect_services.name,
                         'name': affect_node.name,
                         'ip': affect_node.ip})
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "ssh ubuntu@%s\n" \
                    "systemctl status %s\n" \
                    "journalctl -u %s\n" % (
                        affect_node.ip,
                        affect_services.name,
                        affect_services.name)
        elif issue_type == 'service_timeout':
            body += "The unnecessary service %(service_name)s on the node " \
                    "%(name)s (IP %(ip)s) is done for a long time.\n" % (
                        {'service_name': affect_services.name,
                         'name': affect_node.name,
                         'ip': affect_node.ip})
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "ssh ubuntu@%s\n" \
                    "systemctl status %s\n" \
                    "journalctl -u %s\n" % (
                        affect_node.ip,
                        affect_services.name,
                        affect_services.name)
        elif issue_type == 'healthchecker_error':
            body += "The ha_healthchecker service on the node %(name)s (IP " \
                    "%(ip)s) is done.\n" % (
                        {'name': affect_node.name,
                         'ip': affect_node.ip})
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "ssh ubuntu@%s\n" \
                    "systemctl status ha_healthchecker\n" \
                    "journalctl -u ha_healthchecker\n"
        elif issue_type == 'other_node_down':
            body += "The %(role)s node %(name)s (IP %(ip)s) is done.\n" % (
                {'role': affect_node.role,
                 'name': affect_node.name,
                 'ip': affect_node.ip})
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "ssh ubuntu@%s\n" % affect_node.ip
            body += "Or try to login the cloud to check whether the " \
                    "resource exists.\n"
        elif issue_type == 'switch':
            body += "HA deployment already switch to slave deployment.\n"
            body += "Please use labkeeper new-slave command to re-create a new" \
                    "slave cluster.\n"
            body += "\nSuggestion:\n" \
                    "===============\n" \
                    "cd go-to-labkeeper-directory\n" \
                    "modify inventory file\n" \
                    "./deploy.py openlab-ha --action new-slave\n"

        return title, body

    def refresh(self, cluster_config):
        self.cluster_config = cluster_config
        self.app_name = cluster_config.github_app_name
        if (cluster_config.github_user_token != self.token or
                cluster_config.github_repo != self.repo_name):
            self.token = cluster_config.github_user_token
            self.repo_name = cluster_config.github_repo
            self.repo = Github(login_or_token=self.token).get_repo(
                self.repo_name)

    def create_issue(self, issuer_node, issue_type, affect_node=None,
                     affect_services=None):
        title, body = self._format_body_for_issue(
            issuer_node, issue_type, affect_node=affect_node,
            affect_services=affect_services)
        self.repo.create_issue(
            title=title % (
                datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            body=body)

    def _get_login_page_authenticity_token(self, session):
        login_page = session.get('https://github.com/login')
        login_page_content = login_page.content.decode('utf-8')

        login_page_parser = LoginHTMLParser()
        login_page_parser.feed(login_page_content)
        login_page_parser.close()
        quoted_authenticity_token = parse.quote(login_page_parser.token)
        return quoted_authenticity_token

    def _get_github_app_page_authenticity_token(self, app_url, app_name,
                                                session):
        app_page = session.get(app_url)
        if app_page.status_code == 404:
            self.cluster_config.LOG.error(
                "Not Found Github App: %s" % app_name)
            return
        app_page_content = app_page.content.decode('utf-8')

        app_page_parser = AppUpdateHTMLParser()
        app_page_parser.feed(app_page_content)

        quoted_authenticity_token = parse.quote(app_page_parser.token)
        return quoted_authenticity_token

    def update_github_app_webhook(self):
        session = requests.session()
        login_token = self._get_login_page_authenticity_token(session)
        login_info = ('authenticity_token=%(token)s&login=%(username)s&'
                      'password=%(password)s' % {
            'token': login_token,
            'username': self.cluster_config.github_user_name,
            'password': self.cluster_config.github_user_password})
        login_response = session.post('https://github.com/session',
                                      data=login_info)
        if (login_response.status_code == 200 and
                session.cookies._cookies['.github.com']['/'][
                    'logged_in'].value == 'yes'):
            self.cluster_config.LOG.info("Github app change: Success Login")
        else:
            self.cluster_config.LOG.error("Github app change: Fail Login")
            return

        app_url = 'https://github.com/settings/apps/%s' % self.app_name
        github_app_edit_token = self._get_github_app_page_authenticity_token(
            app_url,
            self.cluster_config.github_app_name,
            session)
        if not github_app_edit_token:
            return
        update_response = session.post(
            app_url,
            data="_method=put&authenticity_token=" +
                 github_app_edit_token +
                 "&integration%5Bhook_attributes%5D%5Burl%5D=http%3A%2F%2F" +
                 self.cluster_config.dns_slave_public_ip + "%3A" + '80' +
                 "%2Fapi%2Fconnection%2Fgithub%2Fpayload"
        )
        if update_response.status_code == 200:
            self.cluster_config.LOG.info(
                "Success Update Github APP: %s" % self.app_name)
        else:
            self.cluster_config.LOG.error(
                "Fail Update Github APP: %s" % self.app_name)


class LoginHTMLParser(HTMLParser):
    def __init__(self):
        super(LoginHTMLParser, self).__init__()
        self.token = None

    def handle_startendtag(self, tag, attrs):
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            for key, value in attrs:
                if key == 'value':
                    self.token = value


class AppUpdateHTMLParser(HTMLParser):
    def __init__(self):
        super(AppUpdateHTMLParser, self).__init__()
        self.token = None
        self.token_index = 1

    def handle_startendtag(self, tag, attrs):
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            if self.token_index == 6:
                for key, value in attrs:
                    if key == 'value':
                        self.token = value
                self.token_index += 1
            else:
                self.token_index += 1
