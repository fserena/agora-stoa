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

from redis.lock import Lock

from abc import abstractproperty, abstractmethod, ABCMeta
from agora.stoa.actions.core import PassRequest, AGENT_ID
from agora.stoa.actions.core.utils import CGraph
from agora.stoa.store import r
from rdflib import RDF
from shortuuid import uuid

__author__ = 'Fernando Serena'

_log = logging.getLogger('agora.stoa.actions.base')

_log.info('Cleaning agent lock...')
r.delete('{}:lock'.format(AGENT_ID))


def agent_lock():
    lock_key = '{}:lock'.format(AGENT_ID)
    return r.lock(lock_key, lock_class=Lock)


class Action(object):
    """
    Generic action class that supports requests to Stoas
    """
    __metaclass__ = ABCMeta

    def __init__(self, message):
        """
        Base constructor
        :param message: the incoming request (RDF)
        :return:
        """
        self.__message = message
        self.__action_id = None
        self.__request_id = None

    @abstractproperty
    def request(self):
        pass

    @classmethod
    def response_class(cls):
        """
        This method should be implemented on each final Action class
        :return: The response class
        """
        pass

    @abstractproperty
    def sink(self):
        """
        :return: The sink instance
        """
        pass

    @property
    def request_id(self):
        """
        Every action is assigned a unique request id.
        """
        return self.__request_id

    @property
    def id(self):
        """
        In order to uniquely identify action requests, each incoming one produces an action id based on
        the message id and the submitter id.
        """
        return self.__action_id

    @abstractmethod
    def submit(self):
        """
        Base method that parses and saves the request message
        :return: The new request id
        """
        if not issubclass(self.response_class(), Response):
            raise SystemError(
                'The response class for this action is invalid: {}'.format(self.response_class()))
        _log.info('Parsing request message...')
        self.request.parse(self.__message)
        self.__action_id = u'{}@{}'.format(self.request.message_id, self.request.submitted_by)
        self.__request_id = self.sink.save(self)
        return self.__request_id


class Sink(object):
    """
     Every action should have a sink that deals with Action persistency.
    """
    __metaclass__ = ABCMeta
    passed_requests = set([])

    def __init__(self):
        self._pipe = r.pipeline(transaction=True)
        self._request_id = None
        self._request_key = None
        self._dict_fields = {}
        self._requests_key = '{}:requests'.format(AGENT_ID)

    def load(self, rid):
        """
        Checks the given request id and loads its associated data
        """
        lock = agent_lock()
        lock.acquire()
        try:
            if not r.keys('{}:requests:{}:'.format(AGENT_ID, rid)):
                raise ValueError('Cannot load request: Unknown request id {}'.format(rid))
            self._request_id = rid
            self._request_key = '{}:requests:{}:'.format(AGENT_ID, self._request_id)
            self._load()
        finally:
            lock.release()

    @staticmethod
    def __response_fullname(f):
        """
        The response class name has to to be stored so as to be instanced on load
        :return: A string like <module>.<Response> based on the given response class function provider (f)
        """

        def wrapper():
            clz = f()
            parts = clz.__module__.split('.')
            if parts:
                module_name = parts[-1]
                return '{}.{}'.format(module_name, clz.__name__)
            raise NameError('Invalid response class: {}'.format(clz))

        return wrapper

    @abstractmethod
    def _load(self):
        """
        Sink-specific load statements (to be extended)
        :return:
        """
        self._dict_fields = r.hgetall(self._request_key)

    def __getattr__(self, item):
        if item in self._dict_fields:
            value = self._dict_fields[item]
            if value == 'True' or value == 'False':
                value = eval(value)
            return value
        return super(Sink, self).__getattribute__(item)

    def save(self, action):
        """
        Generates a new request id and stores all action data
        :return: The new request id
        """
        lock = agent_lock()
        lock.acquire()
        try:
            self._request_id = str(uuid())
            self._pipe.multi()
            self._save(action)
            # It is not until this point when the pipe is executed!
            # If it fails, nothing is stored
            self._pipe.execute()
            _log.info("""Request {} was saved:
                        -message id: {}
                        -submitted on: {}
                        -submitted by: {}""".format(self._request_id, action.request.message_id,
                                                    action.request.submitted_on, action.request.submitted_by))
            return self._request_id
        finally:
            lock.release()

    def remove(self):
        """
        Creates a pipe to remove all stored data of the current request
        """
        # All dict_fields are being removed automatically here (hashmap request attributes)
        lock = agent_lock()
        lock.acquire()
        try:
            with r.pipeline(transaction=True) as p:
                p.multi()
                action_id = r.hget(self._request_key, 'id')
                p.zrem(self._requests_key, action_id)
                r_keys = r.keys('{}*'.format(self._request_key))
                for key in r_keys:
                    p.delete(key)
                self._remove(p)
                p.execute()
            _log.info('Request {} was removed'.format(self._request_id))
        finally:
            lock.release()

    @abstractmethod
    def _remove(self, pipe):
        """
        Sink-specific remove statements (to be extended)
        :param pipe: The pipe to be used on remove statements
        """
        pass

    @abstractmethod
    def _save(self, action):
        """
        Sink-specific save statements (to be extended)
        :param action: The action that contains the data to be stored
        """
        # Firstly, we have to check if the action was previously stored...
        if r.zscore('{}:requests'.format(AGENT_ID), action.id):
            raise ValueError('Duplicated request: {}'.format(action.id))
        submitted_by_ts = calendar.timegm(action.request.submitted_on.timetuple())

        # The action id is stored in a sorted set using its timestamp as score
        self._pipe.zadd(self._requests_key, submitted_by_ts, action.id)
        self._request_key = '{}:requests:{}:'.format(AGENT_ID, self._request_id)
        # Basic request data is stored on a dictionary (hashmap)
        self._pipe.hmset(self._request_key, {'submitted_by': action.request.submitted_by,
                                             'submitted_on': action.request.submitted_on,
                                             'message_id': action.request.message_id,
                                             'id': self._request_id,
                                             '__response_class': self.__response_fullname(action.response_class)(),
                                             'type': action.__class__.__module__,
                                             '__hash': action.id})

    @staticmethod
    def do_pass(action):
        Sink.passed_requests.add(action.id)
        raise PassRequest()

    @property
    def request_id(self):
        return self._request_id


class Request(object):
    """
    The generic class that knows how to parse action messages and supports specific action requests
    """

    def __init__(self):
        from agora.stoa.actions.core import STOA, AMQP
        # Since the message is RDF, we create a graph to store and query its triples
        self._graph = CGraph()
        self._graph.bind('stoa', STOA)
        self._graph.bind('amqp', AMQP)
        self._request_node = None

        # Base fields dictionary
        self._fields = {}

    def parse(self, message):
        """
        Parses the message and extracts all useful content
        :param message: The request message (RDF)
        """
        _log.debug('Parsing message...')
        try:
            self._graph.parse(StringIO.StringIO(message), format='turtle')
        except Exception, e:
            raise SyntaxError(e.message)

        self._extract_content()

    @abstractmethod
    def _extract_content(self, request_type=None):
        """
        Request-specific method to query the message graph and extract key content
        """
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
            raise SyntaxError('Missing fields for generic request')

        (self._request_node, self._fields['message_id'],
         self._fields['submitted_on'],
         self._fields['submitted_by']) = request_fields

        if request_type is not None:
            request_types = set(self._graph.objects(self._request_node, RDF.type))
            if len(request_types) != 1 or request_type not in request_types:
                raise SyntaxError('Invalid request type declaration')

        _log.debug(
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
    """
    Every request should have a response.
    """

    __metaclass__ = ABCMeta

    def __init__(self, rid):
        self._request_id = rid

    @abstractmethod
    def build(self):
        """
        :return: A generator that provides the response
        """
        pass

    @abstractproperty
    def sink(self):
        """
        :return: The associated request sink
        """
        pass
