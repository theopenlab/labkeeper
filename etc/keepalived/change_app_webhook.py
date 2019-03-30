#!/usr/bin/python3

import argparse
from html.parser import HTMLParser
import requests

# Author: Wang XiYuan

try:
    from urllib import parse
except Exception:
    print("This tool only support python3")
    exit(1)

GLOBAL_SESSION = requests.session()
LOGIN_AUTH_TOKEN = None
APP_UPDATE_AUTH_TOKEN = None


class LoginHTMLParser(HTMLParser):
    def handle_startendtag(self, tag, attrs):
        global LOGIN_AUTH_TOKEN
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            for key, value in attrs:
                if key == 'value':
                    LOGIN_AUTH_TOKEN = value


class AppUpdateHTMLParser(HTMLParser):
    token_index = 1

    def handle_startendtag(self, tag, attrs):
        global APP_UPDATE_AUTH_TOKEN
        if tag == 'input' and ('name', 'authenticity_token') in attrs:
            if self.token_index == 6:
                for key, value in attrs:
                    if key == 'value':
                        APP_UPDATE_AUTH_TOKEN = value
                self.token_index += 1
            else:
                self.token_index += 1


def _get_login_page_authenticity_token():
    login_page = GLOBAL_SESSION.get('https://github.com/login')
    login_page_content = login_page.content.decode('utf-8')

    login_page_parser = LoginHTMLParser()
    login_page_parser.feed(login_page_content)
    login_page_parser.close()
    quoted_authenticity_token = parse.quote(LOGIN_AUTH_TOKEN)
    return quoted_authenticity_token


def _get_github_app_page_authenticity_token(app_url, app_name):
    app_page = GLOBAL_SESSION.get(app_url)
    if app_page.status_code == 404:
        print("Not Found Github App: %s" % app_name)
        exit(1)
    app_page_content = app_page.content.decode('utf-8')

    app_page_parser = AppUpdateHTMLParser()
    app_page_parser.feed(app_page_content)

    quoted_authenticity_token = parse.quote(APP_UPDATE_AUTH_TOKEN)
    return quoted_authenticity_token


def main(args):
    login_token = _get_login_page_authenticity_token()
    login_info = ('authenticity_token=%(token)s&login=%(username)s&'
                  'password=%(password)s' % {'token': login_token,
                                             'username': args.user,
                                             'password': args.password})
    login_response = GLOBAL_SESSION.post(
        'https://github.com/session',
        data=login_info,
    )
    if (login_response.status_code == 200 and
            GLOBAL_SESSION.cookies._cookies['.github.com']['/'][
                'logged_in'].value == 'yes'):
        print("Success Login")
    else:
        print("Fail Login")
        exit(1)

    app_url = 'https://github.com/settings/apps/%s' % args.app
    github_app_edit_token = _get_github_app_page_authenticity_token(app_url,
                                                                    args.app)
    update_response = GLOBAL_SESSION.post(
        app_url,
        data="_method=put&authenticity_token=" +
             github_app_edit_token +
             "&integration%5Bhook_attributes%5D%5Burl%5D=http%3A%2F%2F" +
             args.ip + "%3A" + args.port +
             "%2Fapi%2Fconnection%2Fgithub%2Fpayload"
    )
    if update_response.status_code == 200:
        print("Success Update Github APP: %s" % args.app)
    else:
        print("Fail Update Github APP: %s" % args.app)
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Githup app webhook url update tool',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument('--user',  metavar='<user_name>', required=True,
                        help="Github user name")
    parser.add_argument('--password', metavar='<password>', required=True,
                        help="Github user password")
    parser.add_argument('--app', metavar='<app_name>', required=True,
                        help="The name of github app")
    parser.add_argument('--ip', metavar='<ip>', required=True,
                        help="The webhook server's IP")
    parser.add_argument('--port', metavar='<port>', default='80',
                        help="The listener's port. Default is 80")
    args = parser.parse_args()
    main(args)
