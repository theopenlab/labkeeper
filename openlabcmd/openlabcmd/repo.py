from openlabcmd import exceptions


class Repo(object):

    def __init__(self, server, appid, appkey):
        # NOTE(yikun): There are two reason we only allow this cmd is executed
        # in zuul node:
        # 1. The app installation interface has been completely supported by
        # zuul github driver (but PyGithub is not supported yet), so we use
        # it directly to avoid to build the duplicate wheels.
        # 2. The app key which is usually only existed in Zuul node.
        try:
            from zuul.driver.github.githubconnection import GithubConnection
            from zuul.driver.github import GithubDriver
        except ImportError:
            raise exceptions.ClientError(
                "Error: 'openlab repo list' only can be used in Zuul node.")
        try:
            driver = GithubDriver()
            connection_config = {
                'server': server,
                'app_id': appid,
                'app_key': appkey,
            }
            self.conn = GithubConnection(driver, 'github', connection_config)
            self.conn._authenticateGithubAPI()
            self.conn._prime_installation_map()
        except Exception:
            raise exceptions.ClientError(
                "Failed to load repo list. Please check the specified"
                " args:\n--server: %s\n--app_id: %s\n--app_key: %s\n"
                "See 'openlab repo list -h' to get more info." % (
                    server, appid, appkey))

    def list(self):
        repos = [{"repo": x} for x in self.conn.installation_map]
        # sort from aA to zZ
        repos.sort(key=lambda x: x["repo"].lower())
        return repos
