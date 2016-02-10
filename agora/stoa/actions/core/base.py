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

import StringIO
import calendar
import logging

from abc import abstractproperty, abstractmethod, ABCMeta
from agora.stoa.actions.core.utils import CGraph
from agora.stoa.store import r
from shortuuid import uuid

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions.base')


def _fullname(f):
    def wrapper():
        clz = f()
        parts = clz.__module__.split('.')
        if parts:
            module_name = parts[-1]
            return '{}.{}'.format(module_name, clz.__name__)
        raise AttributeError('Invalid response class: {}'.format(clz))

    return wrapper


class Action(object):
    __metaclass__ = ABCMeta

    def __init__(self, message):
        self.__message = message
        self.__action_id = None
        self.__request_id = None
        self.__request_key = None

    @abstractproperty
    def request(self):
        pass

    @classmethod
    def response_class(cls):
        pass

    @abstractproperty
    def sink(self):
        pass

    @property
    def request_id(self):
        return self.__request_id

    @property
    def id(self):
        return self.__action_id

    @property
    def request_key(self):
        return self.__request_key

    @abstractmethod
    def submit(self):
        if not issubclass(self.response_class(), Response):
            raise SystemError(
                'The response class for this action is invalid: {}'.format(self.response_class()))
        log.info('Parsing request message...')
        self.request.parse(self.__message)
        self.__action_id = u'{}@{}'.format(self.request.message_id, self.request.submitted_by)
        self.__request_id = self.sink.save(self)


class Sink(object):
    __metaclass__ = ABCMeta

    def __init__(self):
        self._pipe = r.pipeline(transaction=True)
        self._request_id = None
        self._request_key = None
        self._dict_fields = {}

    def load(self, rid):
        if not r.keys('requests:{}'.format(rid)):
            raise ValueError('Cannot load request: Unknown request id {}'.format(rid))
        self._request_id = rid
        self._request_key = 'requests:{}'.format(self._request_id)
        self._load()

    @abstractmethod
    def _load(self):
        self._dict_fields = r.hgetall('requests:{}'.format(self._request_id))

    def __getattr__(self, item):
        if item in self._dict_fields:
            value = self._dict_fields[item]
            if value == 'True' or value == 'False':
                return eval(value)
            return value
        return super(Sink, self).__getattribute__(item)

    def save(self, action):
        self._request_id = str(uuid())
        self._pipe.multi()
        self._save(action)
        self._pipe.execute()
        log.info("""Request {} was saved:
                    -message id: {}
                    -submitted on: {}
                    -submitted by: {}""".format(self._request_id, action.request.message_id,
                                                action.request.submitted_on, action.request.submitted_by))
        return self._request_id

    def remove(self):
        with r.pipeline(transaction=True) as p:
            p.multi()
            action_id = r.hget(self._request_key, 'id')
            p.zrem('requests', action_id)
            r_keys = r.keys('{}*'.format(self._request_key))
            for key in r_keys:
                p.delete(key)
            self._remove(p)
            p.execute()
        log.info('Request {} was removed'.format(self._request_id))

    @abstractmethod
    def _remove(self, pipe):
        pass

    @abstractmethod
    def _save(self, action):
        if r.zscore('requests', action.id):
            raise ValueError('Duplicated request: {}'.format(action.id))
        submitted_by_ts = calendar.timegm(action.request.submitted_on.timetuple())
        self._pipe.zadd('requests', submitted_by_ts, action.id)
        self._request_key = 'requests:{}'.format(self._request_id)
        self._pipe.hmset(self._request_key, {'submitted_by': action.request.submitted_by,
                                             'submitted_on': action.request.submitted_on,
                                             'message_id': action.request.message_id,
                                             'id': self._request_id,
                                             '__response_class': _fullname(action.response_class)(),
                                             'type': action.__class__.__module__,
                                             '__hash': action.id})

    @property
    def request_id(self):
        return self._request_id


class Request(object):
    def __init__(self):
        from agora.stoa.actions.core import STOA, AMQP
        self._graph = CGraph()
        self._graph.bind('stoa', STOA)
        self._graph.bind('amqp', AMQP)
        self._request_node = None
        self._fields = {}

    def parse(self, message):
        log.debug('Parsing message...')
        try:
            self._graph.parse(StringIO.StringIO(message), format='turtle')
        except Exception, e:
            raise SyntaxError(e.message)

        self._extract_content()

    @abstractmethod
    def _extract_content(self):
        q_res = self._graph.query("""SELECT ?node ?m ?d ?a WHERE {
                                        ?node stoa:messageId ?m;
                                              stoa:submittedOn ?d;
                                              stoa:submittedBy [
                                                 stoa:agentId ?a
                                              ]
                                     }""")
        q_res = list(q_res)
        if len(q_res) != 1:
            raise SyntaxError('Invalid request')

        request_fields = q_res.pop()

        if not all(request_fields):
            raise ValueError('Missing fields for generic request')

        (self._request_node, self._fields['message_id'],
         self._fields['submitted_on'],
         self._fields['submitted_by']) = request_fields
        log.debug(
            """Parsed attributes of generic action request:
                -message id: {}
                -submitted on: {}
                -submitted by: {}""".format(
                self._fields['message_id'], self._fields['submitted_on'], self._fields['submitted_by']))

    @property
    def message_id(self):
        return self._fields['message_id'].toPython()

    @property
    def submitted_by(self):
        return self._fields['submitted_by'].toPython()

    @property
    def submitted_on(self):
        return self._fields['submitted_on'].toPython()


class Response(object):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        self._request_id = rid
        self._request_key = 'requests:{}'.format(rid)

    @abstractmethod
    def build(self):
        pass

    @abstractproperty
    def sink(self):
        pass
