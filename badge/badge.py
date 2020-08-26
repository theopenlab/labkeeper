import datetime
import json

from flask import Flask
from flask import request
from flask import Response
import requests


app = Flask(__name__)
BASE_URL = "http://status.openlabtesting.org/api/builds?"
RESP_TYPE = {
    True: """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="90" height="20">
  <linearGradient id="a" x2="0" y2="100%">
     <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
     <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <rect rx="3" width="90" height="20" fill="#555"/>
  <rect rx="3" x="37" width="53" height="20" fill="#4c1"/>
  <path fill="#4c1" d="M37 0h4v20h-4z"/><rect rx="3" width="90" height="20" fill="url(#a)"/>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="19.5" y="15" fill="#010101" fill-opacity=".3">build</text>
    <text x="19.5" y="14">build</text><text x="62.5" y="15" fill="#010101" fill-opacity=".3">passing</text>
    <text x="62.5" y="14">passing</text>
  </g>
</svg>
        """,
    False: '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="80" height="20">
  <linearGradient id="b" x2="0" y2="100%">
     <stop offset="0" stop-color="#bbb" stop-opacity=".1" />
     <stop offset="1" stop-opacity=".1" />
  </linearGradient>
  <mask id="a">
     <rect width="80" height="20" rx="3" fill="#fff" />
  </mask>
  <g mask="url(#a)">
     <path fill="#555" d="M0 0h37v20H0z" />
     <path fill="#e05d44" d="M37 0h43v20H37z" />
     <path fill="url(#b)" d="M0 0h80v20H0z" />
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
     <text x="18.5" y="15" fill="#010101" fill-opacity=".3">build</text>
     <text x="18.5" y="14">build</text>
     <text x="57.5" y="15" fill="#010101" fill-opacity=".3">failing</text>
     <text x="57.5" y="14">failing</text>
  </g>
</svg>
'''
}


def get_args(request_args):
    projects = request_args.getlist('project')
    job_names = request_args.getlist('job_name')
    return projects, job_names


def genarate_zuul_url(projects, job_names):
    projects_str_list = []
    for project in projects:
        if '/' in project:
            project = project.replace('/', '%2F')
        projects_str_list.append("project=%s" % project)

    jobs_str_list = []
    for job in job_names:
        jobs_str_list.append("job_name=%s" % job)

    if projects_str_list and not jobs_str_list:
        url = BASE_URL + "&".join(projects_str_list)
    elif not projects_str_list and jobs_str_list:
        url = BASE_URL + "&".join(jobs_str_list)
    else:
        url = BASE_URL + "&".join(projects_str_list) + "&" + "&".join(jobs_str_list)
    return url


def check_the_result(url, projects, job_names):
    status_response = requests.get(url)
    res = json.loads(status_response.text)
    if projects and not job_names:
        projects_set = set(projects)
        for r in res:
            if not projects_set:
                return True
            if r['project'] in projects_set:
                if r['result'] != 'SUCCESS':
                    return False
                else:
                    projects_set.remove(r['project'])
        return True

    elif not projects and job_names:
        jobs_set = set(job_names)
        for r in res:
            if not jobs_set:
                return True
            if r['job_name'] in jobs_set:
                if r['result'] != 'SUCCESS':
                    return False
                else:
                    jobs_set.remove(r['project'])
        return True

    else:
        job_names_set = set(job_names)
        mappings = {}
        for project in projects:
            mappings[project] = {}
        for r in res:
            if not job_names_set:
                return True
            if r['project'] in projects and r['job_name'] in job_names_set:
                if mappings[r['project']].get(r['job_name'], None):
                    continue
                if r['result'] != 'SUCCESS':
                    return False
                else:
                    mappings[r['project']][r['job_name']] = True
                    job_names_set.remove(r['job_name'])
        return True


@app.route('/badge')
def get_badge():
    projects, job_names = get_args(request.args)
    if (not projects and not job_names) or not projects:
        return Response("Invaild Request")
    url = genarate_zuul_url(projects, job_names)
    success = check_the_result(url, projects, job_names)
    response = Response(RESP_TYPE[success], mimetype='image/svg+xml')
    response.cache_control.no_cache = True
    response.cache_control.no_store = True
    response.cache_control.private = True
    response.cache_control.max_age = 0
    response.expires = datetime.datetime(1984, 1, 1)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.add_etag()
    return response

@app.route('/badge-health')
def health_report_to_external():
    projects, job_names = get_args(request.args)
    return Response("Alive")


if __name__ == '__main__':
    app.run(
      host='0.0.0.0',
      port=15000,
      debug=True
    )
