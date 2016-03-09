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

from agora.stoa.server import app, NotFound
from agora.stoa.store import r
from flask import jsonify
from flask.views import View

__author__ = 'Fernando Serena'

AGENT_ID = app.config['ID']


def filter_hash_attrs(key, predicate):
    hash_map = r.hgetall(key)
    visible_attrs = filter(predicate, hash_map)
    return {attr: hash_map[attr] for attr in filter(lambda x: x in visible_attrs, hash_map)}


@app.route('/requests')
def get_requests():
    requests = [rk.split(':')[1] for rk in r.keys('{}:requests:*:'.format(AGENT_ID))]
    return jsonify(requests=requests)


@app.route('/requests/<rid>')
def get_request(rid):
    if not r.exists('{}:requests:{}:'.format(AGENT_ID, rid)):
        raise NotFound('The request {} does not exist'.format(rid))
    r_dict = filter_hash_attrs('{}:requests:{}:'.format(AGENT_ID, rid), lambda x: not x.startswith('__'))
    channel = r_dict['channel']
    ch_dict = r.hgetall('{}:channels:{}'.format(AGENT_ID, channel))
    broker = r_dict['broker']
    br_dict = r.hgetall('{}:brokers:{}'.format(AGENT_ID, broker))
    r_dict['channel'] = ch_dict
    r_dict['broker'] = br_dict
    if 'mapping' in r_dict:
        r_dict['mapping'] = eval(r_dict['mapping'])

    return jsonify(r_dict)


@app.route('/fragments')
def get_fragments():
    fragment_ids = list(r.smembers('{}:fragments'.format(AGENT_ID)))
    f_list = [{'id': fid, 'gp': list(r.smembers('{}:fragments:{}:gp'.format(AGENT_ID, fid)))} for fid in fragment_ids]
    return jsonify(fragments=f_list)


class FragmentView(View):
    decorators = []

    @staticmethod
    def __get_fragment(fid):
        if not r.sismember('{}:fragments'.format(AGENT_ID), fid):
            raise NotFound('The fragment {} does not exist'.format(fid))

        f_dict = {
            'id': fid,
            'gp': list(r.smembers('{}:fragments:{}:gp'.format(AGENT_ID, fid))),
            'synced': r.exists('{}:fragments:{}:sync'.format(AGENT_ID, fid)),
            'requests': list(r.smembers('{}:fragments:{}:requests'.format(AGENT_ID, fid)))
        }

        return f_dict

    def dispatch_request(self, **kwargs):
        result = self.__get_fragment(kwargs['fid'])
        for decorator in FragmentView.decorators:
            result = decorator(**result)
        return jsonify(result)


app.add_url_rule('/fragments/<fid>', view_func=FragmentView.as_view('fragment'))
