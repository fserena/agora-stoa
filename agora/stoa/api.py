"""
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=#
  This file is part of the Smart Developer Hub Project:
    http://www.smartdeveloperhub.org

  Center for Open Middleware
        http://www.centeropenmiddleware.com/
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=#
  Copyright (C) 2015 Center for Open Middleware.
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=#
  Licensed under the Apache License, Version 2.0 (the "License");
  you may not use this file except in compliance with the License.
  You may obtain a copy of the License at

            http://www.apache.org/licenses/LICENSE-2.0

  Unless required by applicable law or agreed to in writing, software
  distributed under the License is distributed on an "AS IS" BASIS,
  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
  See the License for the specific language governing permissions and
  limitations under the License.
#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=#
"""

from agora.stoa.server import app
from agora.stoa.store import r
from flask import jsonify

__author__ = 'Fernando Serena'


class APIError(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


class NotFound(APIError):
    def __init__(self, message, payload=None):
        super(NotFound, self).__init__(message, 404, payload)


class Conflict(APIError):
    def __init__(self, message, payload=None):
        super(Conflict, self).__init__(message, 409, payload)


def filter_hash_attrs(key, predicate):
    hash_map = r.hgetall(key)
    visible_attrs = filter(predicate, hash_map)
    return {attr: hash_map[attr] for attr in filter(lambda x: x in visible_attrs, hash_map)}


@app.errorhandler(APIError)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code

    return response


@app.route('/requests')
def get_requests():
    request_keys = filter(lambda x: len(x.split(':')) == 2, r.keys('requests:*'))
    requests = [rk.split(':')[1] for rk in request_keys]
    return jsonify({"requests": requests})


@app.route('/requests/<rid>')
def get_request(rid):
    if not r.keys('requests:{}'.format(rid)):
        raise NotFound('The request {} does not exist'.format(rid))
    r_dict = filter_hash_attrs('requests:{}'.format(rid), lambda x: not x.startswith('__'))
    channel = r_dict['channel']
    ch_dict = r.hgetall('channels:{}'.format(channel))
    broker = r_dict['broker']
    br_dict = r.hgetall('brokers:{}'.format(broker))
    r_dict['channel'] = ch_dict
    r_dict['broker'] = br_dict
    if 'mapping' in r_dict:
        r_dict['mapping'] = eval(r_dict['mapping'])

    return jsonify(r_dict)
