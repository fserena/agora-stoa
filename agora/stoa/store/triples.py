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
import traceback
from random import random
from threading import Lock

import datetime
from datetime import datetime as dt
from redis.lock import Lock as RedisLock
from time import sleep

import os
import shortuuid
from agora.stoa.actions.core import STOA, AGENT_ID
from agora.stoa.server import app
from agora.stoa.store import r
from concurrent.futures import ThreadPoolExecutor
from rdflib import ConjunctiveGraph, URIRef, Literal, XSD, BNode
import re

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.store.triples')
pool = ThreadPoolExecutor(max_workers=4)

GRAPH_THROTTLING = max(1, int(app.config.get('CACHE', {}).get('graph_throttling', 30)))
MIN_CACHE_TIME = max(0, int(app.config.get('CACHE', {}).get('min_cache_time', 10)))

log.info("""Triple store setup:
                    - Graph throttling: {}
                    - Minimum cache time: {}""".format(GRAPH_THROTTLING, MIN_CACHE_TIME))

log.info('Cleaning cache...')
uuid_locks = r.keys('{}:cache*'.format(AGENT_ID))
for ulk in uuid_locks:
    r.delete(ulk)


def load_stream_triples(fid, until):
    def __triplify(x):
        def __extract_lang(v):
            def __lang_tag_match(strg, search=re.compile(r'[^a-z]').search):
                return not bool(search(strg))

            if '@' in v:
                try:
                    (v_aux, lang) = tuple(v.split('@'))
                    (v, lang) = (v_aux, lang) if __lang_tag_match(lang) else (v, None)
                except ValueError:
                    lang = None
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

    for x in r.zrangebyscore('{}:fragments:{}:stream'.format(AGENT_ID, fid), '-inf', '{}'.format(float(until))):
        yield __triplify(x)


def add_stream_triple(fid, tp, (s, p, o), timestamp=None):
    try:
        if timestamp is None:
            timestamp = calendar.timegm(dt.utcnow().timetuple())
        quad = (tp, s.n3(), p.n3(), o.n3())
        stream_key = '{}:fragments:{}:stream'.format(AGENT_ID, fid)
        not_found = not bool(r.zscore(stream_key, quad))
        if not_found:
            with r.pipeline() as pipe:
                pipe.zadd(stream_key, timestamp, quad)
                pipe.execute()
        return not_found
    except Exception, e:
        traceback.print_exc()
        log.error(e.message)


class GraphProvider(object):
    def __init__(self):
        self.__last_creation_ts = dt.now()
        self.__graph_dict = {}
        self.__uuid_dict = {}
        self.__gid_uuid_dict = {}
        self.__lock = Lock()
        self.__cache_key = '{}:cache'.format(AGENT_ID)
        self.__gids_key = '{}:gids'.format(self.__cache_key)

        pool.submit(self.__purge)

    @staticmethod
    def __clean(name):
        shutil.rmtree('store/resources/{}'.format(name))

    @staticmethod
    def uuid_lock(uuid):
        lock_key = '{}:cache:{}:lock'.format(AGENT_ID, uuid)
        return r.lock(lock_key, lock_class=RedisLock)

    def __purge(self):
        while True:
            self.__lock.acquire()
            try:
                obsolete = filter(lambda x: not r.exists('{}:cache:{}'.format(AGENT_ID, x)),
                                  r.smembers(self.__cache_key))

                if obsolete:
                    with r.pipeline(transaction=True) as p:
                        p.multi()
                        log.info('Removing {} resouces from cache...'.format(len(obsolete)))
                        for uuid in obsolete:
                            uuid_lock = self.uuid_lock(uuid)
                            uuid_lock.acquire()
                            try:
                                gid = r.hget(self.__gids_key, uuid)
                                counter_key = '{}:cache:{}:cnt'.format(AGENT_ID, uuid)
                                usage_counter = r.get(counter_key)
                                if usage_counter is None or int(usage_counter) <= 0:
                                    try:
                                        resources_cache.remove_context(resources_cache.get_context(uuid))
                                        p.srem(self.__cache_key, uuid)
                                        p.hdel(self.__gids_key, uuid)
                                        p.hdel(self.__gids_key, gid)
                                        p.delete(counter_key)
                                        g = self.__uuid_dict[uuid]
                                        del self.__uuid_dict[uuid]
                                        del self.__graph_dict[g]
                                    except Exception, e:
                                        traceback.print_exc()
                                        log.error('Purging resource {} with uuid {}'.format(gid, uuid))
                                p.execute()
                            finally:
                                uuid_lock.release()
            except Exception, e:
                traceback.print_exc()
                log.error(e.message)
            finally:
                self.__lock.release()
            sleep(10)

    def create(self, conjunctive=False, gid=None, loader=None, format=None):
        self.__lock.acquire()
        uuid_lock = None
        cached = False
        p = r.pipeline(transaction=True)
        p.multi()

        try:
            uuid = shortuuid.uuid()

            if conjunctive:
                if 'persist' in app.config['STORE']:
                    g = ConjunctiveGraph('Sleepycat')
                    g.open('store/resources/{}'.format(uuid), create=True)
                else:
                    g = ConjunctiveGraph()
                g.store.graph_aware = False
                self.__graph_dict[g] = uuid
                self.__uuid_dict[uuid] = g
                return g
            else:
                g = resources_cache.get_context(uuid)
                try:
                    if gid is not None:
                        st_uuid = r.hget(self.__gids_key, gid)
                        if st_uuid is not None:
                            cached = True
                            uuid = st_uuid
                            uuid_lock = self.uuid_lock(uuid)
                            uuid_lock.acquire()
                            g = self.__uuid_dict[uuid]
                            uuid_lock.release()
                        else:
                            post_ts = dt.now()
                            elapsed = (post_ts - self.__last_creation_ts).total_seconds()
                            throttling = (1.0 / GRAPH_THROTTLING) - elapsed
                            if throttling > 0:
                                sleep(throttling)

                        temp_key = '{}:cache:{}'.format(AGENT_ID, uuid)
                        counter_key = '{}:cnt'.format(temp_key)
                        ttl = MIN_CACHE_TIME + int(10 * random())
                        ttl_ts = calendar.timegm((dt.now() + datetime.timedelta(ttl)).timetuple())

                        if st_uuid is None:
                            p.delete(counter_key)
                            p.sadd(self.__cache_key, uuid)
                            p.hset(self.__gids_key, uuid, gid)
                            p.hset(self.__gids_key, gid, uuid)
                            self.__last_creation_ts = dt.now()
                        p.incr(counter_key)
                        p.set(temp_key, ttl_ts)
                        p.expire(temp_key, ttl)
                        uuid_lock = self.uuid_lock(uuid)
                        uuid_lock.acquire()
                except Exception, e:
                    log.error(e.message)
                    traceback.print_exc()
            self.__graph_dict[g] = uuid
            self.__uuid_dict[uuid] = g
        finally:
            self.__lock.release()

        try:
            if cached:
                return g

            source = loader(gid, format)
            if not isinstance(source, bool):
                g.parse(source=source, format=format)
                return g
            else:
                p.hdel(self.__gids_key, gid)
                p.hdel(self.__gids_key, uuid)
                p.srem(self.__cache_key, uuid)
                counter_key = '{}:cache:{}:cnt'.format(AGENT_ID, uuid)
                p.delete(counter_key)
                p.execute()
                del self.__graph_dict[g]
                del self.__uuid_dict[uuid]
                return source
        finally:
            p.execute()
            uuid_lock.release()

    def release(self, g):
        self.__lock.acquire()
        try:
            if g in self.__graph_dict:
                removed = True
                if isinstance(g, ConjunctiveGraph):
                    if 'persist' in app.config['STORE']:
                        g.close()
                        pool.submit(self.__clean, self.__graph_dict[g])
                    else:
                        g.remove((None, None, None))
                        g.close()
                else:
                    uuid = self.__graph_dict[g]
                    if not r.sismember(self.__cache_key, uuid):
                        resources_cache.remove_context(resources_cache.get_context(self.__graph_dict[g]))
                    else:
                        r.decr('{}:cache:{}:cnt'.format(AGENT_ID, uuid))
                        removed = False
                        # The graph will be purged

                if removed:
                    uuid = self.__graph_dict[g]
                    del self.__graph_dict[g]
                    del self.__uuid_dict[uuid]
        finally:
            self.__lock.release()


store_mode = app.config['STORE']
if 'persist' in store_mode:
    log.info('Creating store folders...')
    if not os.path.exists('store'):
        os.makedirs('store')
    if os.path.exists('store/resources'):
        shutil.rmtree('store/resources/')
    os.makedirs('store/resources')
    cache_keys = r.keys('{}:cache*'.format(AGENT_ID))
    for ck in cache_keys:
        r.delete(ck)
    log.info('Loading known triples...')
    fragments_cache = ConjunctiveGraph('Sleepycat')
    log.info('Building fragments graph...')
    fragments_cache.open('store/fragments', create=True)
    resources_cache = ConjunctiveGraph('Sleepycat')
    log.info('Building resources graph...')
    resources_cache.open('store/resources', create=True)
else:
    fragments_cache = ConjunctiveGraph()
    resources_cache = ConjunctiveGraph()

fragments_cache.store.graph_aware = False
resources_cache.store.graph_aware = False
fragments_cache.bind('stoa', STOA)
resources_cache.bind('stoa', STOA)

graph_provider = GraphProvider()
