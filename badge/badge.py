import datetime
import json

from flask import Flask
from flask import request
from flask import Response
import requests


app = Flask(__name__)


@app.route('/badge')
def get_badge():
    project = request.args.get('project', '')
    job_name = request.args.get('job_name', '')
    if not project and not job_name:
        return Response("Invaild Request")
    if '/' in project:
        project = project.replace('/', '%2F')
    success = True
    if project:
        url = "http://status.openlabtesting.org/api/builds?project=%s" % project
        if job_name:
            url = url + "&job_name=%s" % job_name
        status_response = requests.get(url)

        if job_name:
            status = json.loads(status_response.text)[0]['result']
            success = True if status == 'SUCCESS' else False
        else:
            date_time = None
            for each in json.loads(status_response.text):
                if not date_time:
                    date_time = each['start_time'].split('T')[0]
                else:
                    if data_time != each['start_time'].split('T')[0]:
                        break
                if each['result'] != 'SUCCESS':
                    success = False
    if success:
        body = """<?xml version="1.0" encoding="UTF-8"?>
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
        """
    else:
        body = '''<?xml version="1.0" encoding="UTF-8"?>
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
    response = Response(body, mimetype='image/svg+xml')
    response.cache_control.no_cache = True
    response.cache_control.no_store = True
    response.cache_control.private = True
    response.cache_control.max_age = 0
    response.expires = datetime.datetime(1984, 1, 1)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.add_etag()
    return response

if __name__ == '__main__':
    app.run(
      host='0.0.0.0',
      port= 15000,
      debug=True
    )

