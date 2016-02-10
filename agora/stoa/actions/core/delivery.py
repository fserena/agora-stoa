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
import base64
import logging
import uuid
from abc import ABCMeta, abstractmethod, abstractproperty
from datetime import datetime

from agora.stoa.actions.core import RDF, STOA, FOAF, TYPES, XSD
from agora.stoa.actions.core.base import Request, Action, Response, Sink
from agora.stoa.actions.core.utils import CGraph
from agora.stoa.messaging.reply import reply
from agora.stoa.store import r
from agora.stoa.server import app
from rdflib import BNode, Literal, RDFS

__author__ = 'Fernando Serena'

EXCHANGE_CONFIG = app.config['EXCHANGE']
exchange = EXCHANGE_CONFIG['exchange']
log = logging.getLogger('agora.stoa.actions.delivery')
AGENT_UUID = Literal(str(uuid.uuid4()), datatype=TYPES.UUID)


def _build_reply_templates():
    accepted = CGraph()
    failure = CGraph()
    response_node = BNode()
    agent_node = BNode()
    accepted.add((response_node, RDF.type, STOA.Accepted))
    accepted.add((agent_node, RDF.type, FOAF.Agent))
    accepted.add((response_node, STOA.responseNumber, Literal("0", datatype=XSD.unsignedLong)))
    accepted.add((response_node, STOA.submittedBy, agent_node))
    accepted.add((response_node, STOA.submittedBy, agent_node))
    accepted.add(
        (agent_node, STOA.agentId, AGENT_UUID))
    accepted.bind('types', TYPES)
    accepted.bind('stoa', STOA)
    accepted.bind('foaf', FOAF)

    for triple in accepted:
        failure.add(triple)
    failure.set((response_node, RDF.type, STOA.Failure))
    for (prefix, ns) in accepted.namespaces():
        failure.bind(prefix, ns)

    return accepted, failure


def build_reply(template, reply_to, comment=None):
    reply_graph = CGraph()
    root_node = None
    for (s, p, o) in template:
        reply_graph.add((s, p, o))
        if p == RDF.type:
            root_node = s
    reply_graph.add((root_node, STOA.responseTo, Literal(reply_to, datatype=TYPES.UUID)))
    reply_graph.set((root_node, STOA.submittedOn, Literal(datetime.now())))
    reply_graph.set((root_node, STOA.messageId, Literal(str(uuid.uuid4()), datatype=TYPES.UUID)))
    if comment is not None:
        reply_graph.set((root_node, RDFS.comment, Literal(comment, datatype=XSD.string)))
    for (prefix, ns) in template.namespaces():
        reply_graph.bind(prefix, ns)
    return reply_graph


accepted_template, failure_template = _build_reply_templates()
log.info('Basic delivery templates created')


class DeliveryRequest(Request):
    def __init__(self):
        super(DeliveryRequest, self).__init__()

    def _extract_content(self):
        super(DeliveryRequest, self)._extract_content()

        q_res = self._graph.query("""SELECT ?node ?ex ?rk ?h ?p ?v WHERE {
                                  ?node stoa:replyTo [
                                        a stoa:DeliveryChannel;
                                        amqp:exchangeName ?ex;
                                        amqp:routingKey ?rk;
                                        amqp:broker [
                                           a amqp:Broker;
                                           amqp:host ?h;
                                           amqp:port ?p;
                                           amqp:virtualHost ?v
                                        ]
                                     ]
                                  } """)
        q_res = list(q_res)
        if len(q_res) != 1:
            raise SyntaxError('Invalid delivery request')

        request_fields = q_res.pop()

        if not any(request_fields):
            raise ValueError('Missing fields for delivery request')

        if request_fields[0] != self._request_node:
            raise SyntaxError('Request node does not match')

        delivery_data = {}

        (delivery_data['exchange'],
         delivery_data['routing_key'],
         delivery_data['host'],
         delivery_data['port'],
         delivery_data['vhost']) = request_fields[1:]
        log.debug("""Parsed attributes of a delivery action request:
                      -exchange name: {}
                      -routing key: {}
                      -host: {}
                      -port: {}
                      -virtual host: {}""".format(
            delivery_data['exchange'],
            delivery_data['routing_key'],
            delivery_data['host'], delivery_data['port'], delivery_data['vhost']))

        self._fields['delivery'] = delivery_data.copy()

    @property
    def broker(self):
        broker_dict = {k: self._fields['delivery'][k].toPython() for k in ('host', 'port', 'vhost') if
                       k in self._fields['delivery']}
        broker_dict['port'] = int(broker_dict['port'])
        return broker_dict

    @property
    def channel(self):
        return {k: self._fields['delivery'][k].toPython() for k in ('exchange', 'routing_key') if
                k in self._fields['delivery']}

    @property
    def recipient(self):
        recipient = self.broker.copy()
        recipient.update(self.channel)
        return recipient


class DeliveryAction(Action):
    __metaclass__ = ABCMeta

    def __init__(self, message):
        super(DeliveryAction, self).__init__(message)

    def __reply_accepted(self):
        graph = build_reply(accepted_template, self.request.message_id)
        reply(graph.serialize(format='turtle'), exchange=exchange,
              routing_key='stoa.response.{}'.format(self.request.submitted_by),
              **self.request.broker)
        if self.sink.delivery is None:
            self.sink.delivery = 'accepted'
        log.info('Request {} was accepted'.format(self.request_id))

    def _reply_failure(self, reason=None):
        try:
            graph = build_reply(failure_template, self.request.message_id, reason)
            reply(graph.serialize(format='turtle'), exchange=exchange,
                  routing_key='stoa.response.{}'.format(self.request.submitted_by),
                  **self.request.broker)
            log.info('Notified failure of request {} due to: {}'.format(self.request_id, reason))
        except KeyError:
            # Delivery channel data may be invalid
            pass

    def submit(self):
        super(DeliveryAction, self).submit()
        try:
            self.__reply_accepted()
        except Exception, e:
            log.warning(e.message)
            self.sink.remove()


def used_channels():
    req_channel_keys = r.keys('requests:*')
    for rck in req_channel_keys:
        try:
            channel = r.hget(rck, 'channel')
            yield channel
        except Exception as e:
            log.warning(e.message)


def channel_sharing(channel_b64):
    return len(list(filter(lambda x: x == channel_b64, used_channels()))) - 1  # Don't count itself


class DeliverySink(Sink):
    __metaclass__ = ABCMeta

    @abstractmethod
    def _save(self, action):
        super(DeliverySink, self)._save(action)
        self._pipe.sadd('deliveries', self._request_id)
        broker_b64 = base64.b64encode('|'.join(map(lambda x: str(x), action.request.broker.values())))
        channel_b64 = base64.b64encode('|'.join(action.request.channel.values()))
        self._pipe.hmset('channels:{}'.format(channel_b64), action.request.channel)
        self._pipe.hmset('brokers:{}'.format(broker_b64), action.request.broker)
        self._pipe.hset('{}'.format(self._request_key), 'channel', channel_b64)
        self._pipe.hset('{}'.format(self._request_key), 'broker', broker_b64)

    @abstractmethod
    def _load(self):
        super(DeliverySink, self)._load()
        self._dict_fields['channel'] = r.hgetall('channels:{}'.format(self._dict_fields['channel']))
        self._dict_fields['broker'] = r.hgetall('brokers:{}'.format(self._dict_fields['broker']))
        self._dict_fields['broker']['port'] = int(self._dict_fields['broker']['port'])
        recipient = self._dict_fields['channel'].copy()
        recipient.update(self._dict_fields['broker'])
        self._dict_fields['recipient'] = recipient
        try:
            del self._dict_fields['delivery']
        except KeyError:
            pass

    @abstractmethod
    def _remove(self, pipe):
        super(DeliverySink, self)._remove(pipe)
        pipe.srem('deliveries', self._request_id)
        pipe.srem('deliveries:ready', self._request_id)
        channel_b64 = r.hget(self._request_key, 'channel')
        sharing = channel_sharing(channel_b64)
        if not sharing:
            log.info('Removing delivery channel ({}) for request {}'.format(channel_b64, self._request_id))
            pipe.delete('channels:{}'.format(channel_b64))
        else:
            log.info('Cannot remove delivery channel of request {}. It is being shared with {} another requests'.format(
                self.request_id, sharing))

    @property
    def delivery(self):
        return r.hget('requests:{}'.format(self._request_id), 'delivery')

    @delivery.setter
    def delivery(self, value):
        with r.pipeline(transaction=True) as p:
            p.multi()
            if value == 'ready':
                p.sadd('deliveries:ready', self._request_id)
            elif value == 'sent':
                p.sadd('deliveries:sent', self._request_id)
            if value != 'ready':
                p.srem('deliveries:ready', self._request_id)
            p.hset('requests:{}'.format(self._request_id), 'delivery', value)
            p.execute()
        log.info('Request {} delivery state is now "{}"'.format(self._request_id, value))

    @abstractproperty
    def ready(self):
        return False


class DeliveryResponse(Response):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        super(DeliveryResponse, self).__init__(rid)

    @abstractmethod
    def build(self):
        super(DeliveryResponse, self).build()
