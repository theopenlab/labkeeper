#!/usr/bin/python
import argparse
import datetime
from github import Github

REPO_NAME = 'moo-ai/moo-ai.github.io'


def notify_issue(args):
    g = Github(args.username, args.password)
    repo = g.get_repo(REPO_NAME)
    repo.create_issue(
        title="[FATAL][%s] The online openlab deployment <%s> has Down, "
              "Please recovery asap!" % (
                  datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  args.env_role),
        body="")


def main(args):
    notify_issue(args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Github tools',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--username',  metavar='<username>', required=True,
                        help="Github User Name")
    parser.add_argument('--password', metavar='<password>', required=True,
                        help="The PassWord of Github User")
    parser.add_argument('--env-role', metavar='<env_role>', required=True,
                        help="The role of target deployment")
    args = parser.parse_args()
    main(args)
