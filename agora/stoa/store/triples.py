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

import calendar
import logging
import shutil

from datetime import datetime as dt

import os
import shortuuid
from agora.stoa.server import app
from agora.stoa.store import r
from agora.stoa.actions.core import STOA
from concurrent.futures import ThreadPoolExecutor
from rdflib import ConjunctiveGraph, URIRef, Literal, XSD, BNode

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.store.triples')
pool = ThreadPoolExecutor(max_workers=4)


def load_stream_triples(fid, until):
    def __triplify(x):
        def __extract_lang(v):
            if '@' in v:
                (v, lang) = tuple(v.split('@'))
            else:
                lang = None
            return v, lang

        def __term(elm):
            if elm.startswith('<'):
                return URIRef(elm.lstrip('<').rstrip('>'))
            elif '^^' in elm:
                (value, ty) = tuple(elm.split('^^'))
                return Literal(value.replace('"', ''), datatype=URIRef(ty.lstrip('<').rstrip('>')))
            elif elm.startswith('_:'):
                return BNode(elm.replace('_:', ''))
            else:
                (elm, lang) = __extract_lang(elm)
                elm = elm.replace('"', '')
                if lang is not None:
                    return Literal(elm, lang=lang)
                else:
                    return Literal(elm, datatype=XSD.string)

        c, s, p, o = eval(x)
        return c, __term(s), __term(p), __term(o)

    for x in r.zrangebyscore('fragments:{}:stream'.format(fid), '-inf', '{}'.format(float(until))):
        yield __triplify(x)


def add_stream_triple(fid, tp, (s, p, o), timestamp=None):
    try:
        if timestamp is None:
            timestamp = calendar.timegm(dt.utcnow().timetuple())
        quad = (tp, s.n3(), p.n3(), o.n3())
        stream_key = 'fragments:{}:stream'.format(fid)
        not_found = not bool(r.zscore(stream_key, quad))
        if not_found:
            with r.pipeline() as pipe:
                pipe.zadd(stream_key, timestamp, quad)
                pipe.execute()
        return not_found
    except Exception, e:
        log.error(e.message)


class GraphProvider(object):
    def __init__(self):
        self.__graph_dict = {}

    @staticmethod
    def __clean(name):
        shutil.rmtree('store/query/{}'.format(name))

    def create(self, conjunctive=False):
        uuid = shortuuid.uuid()
        if conjunctive:
            if 'persist' in app.config['STORE']:
                g = ConjunctiveGraph('Sleepycat')
                g.open('store/query/{}'.format(uuid), create=True)
                g.store.graph_aware = False
            else:
                g = ConjunctiveGraph()
                g.store.graph_aware = False
        else:
            g = query.get_context(uuid)
        self.__graph_dict[g] = uuid
        return g

    def destroy(self, g):
        if g in self.__graph_dict:
            if isinstance(g, ConjunctiveGraph):
                if 'persist' in app.config['STORE']:
                    g.close()
                    pool.submit(self.__clean, self.__graph_dict[g])
                else:
                    g.remove((None, None, None))
                    g.close()
            else:
                query.remove_context(query.get_context(self.__graph_dict[g]))
            del self.__graph_dict[g]


graph_provider = GraphProvider()
store_mode = app.config['STORE']
if 'persist' in store_mode:
    log.info('Creating store folders...')
    if not os.path.exists('store'):
        os.makedirs('store')
    if os.path.exists('store/query'):
        shutil.rmtree('store/query/')
    if os.path.exists('store/tmp'):
        shutil.rmtree('store/tmp')
    os.makedirs('store/query')
    log.info('Loading known triples...')
    cache = ConjunctiveGraph('Sleepycat')
    log.info('Building cache graph...')
    cache.open('store/cache', create=True)
    query = ConjunctiveGraph('Sleepycat')
    log.info('Building temp graph...')
    query.open('store/tmp', create=True)
else:
    cache = ConjunctiveGraph()
    query = ConjunctiveGraph()

cache.store.graph_aware = False
query.store.graph_aware = False
cache.bind('stoa', STOA)
query.bind('stoa', STOA)
