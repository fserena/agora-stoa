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
import traceback
import uuid

from datetime import datetime

from abc import ABCMeta, abstractmethod
from agora.stoa.actions.core import RDF, STOA, FOAF, TYPES, XSD, AGENT_ID
from agora.stoa.actions.core.base import Request, Action, Response, Sink
from agora.stoa.actions.core.utils import CGraph
from agora.stoa.messaging.reply import reply
from agora.stoa.server import app
from agora.stoa.store import r
from rdflib import BNode, Literal, RDFS

__author__ = 'Fernando Serena'

EXCHANGE_CONFIG = app.config['EXCHANGE']
_exchange = EXCHANGE_CONFIG['exchange']
response_rk = EXCHANGE_CONFIG['response_rk']
_log = logging.getLogger('agora.stoa.actions.delivery')
LIT_AGENT_ID = Literal(AGENT_ID, datatype=TYPES.UUID)


def _build_reply_templates():
    """
    :return: Accept and Failure message templates
    """
    accepted = CGraph()
    failure = CGraph()
    response_node = BNode()
    agent_node = BNode()
    accepted.add((response_node, RDF.type, STOA.Root))
    accepted.add((response_node, RDF.type, STOA.Accepted))
    accepted.add((agent_node, RDF.type, FOAF.Agent))
    accepted.add((response_node, STOA.responseNumber, Literal("0", datatype=XSD.unsignedLong)))
    accepted.add((response_node, STOA.submittedBy, agent_node))
    accepted.add(
        (agent_node, STOA.agentId, LIT_AGENT_ID))
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
    """
    :param template: A specific message template graph
    :param reply_to: Recipient Agent UUID
    :param comment: Optional comment
    :return: The reply graph
    """
    reply_graph = CGraph()
    root_node = None
    for (s, p, o) in template:
        if o == STOA.Root:
            root_node = s
        else:
            reply_graph.add((s, p, o))

    reply_graph.add((root_node, STOA.responseTo, Literal(reply_to, datatype=TYPES.UUID)))
    reply_graph.set((root_node, STOA.submittedOn, Literal(datetime.utcnow())))
    reply_graph.set((root_node, STOA.messageId, Literal(str(uuid.uuid4()), datatype=TYPES.UUID)))
    if comment is not None:
        reply_graph.set((root_node, RDFS.comment, Literal(comment, datatype=XSD.string)))
    for (prefix, ns) in template.namespaces():
        reply_graph.bind(prefix, ns)
    return reply_graph


# Create both accept and failure templates
accepted_template, failure_template = _build_reply_templates()
_log.info('Basic delivery templates created')


class DeliveryRequest(Request):
    def __init__(self):
        super(DeliveryRequest, self).__init__()

    def _extract_content(self, request_type=None):
        """
        Extracts delivery related data from message (delivery channel to reply to)
        """
        super(DeliveryRequest, self)._extract_content(request_type)

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
            raise SyntaxError('Missing fields for delivery request')

        if request_fields[0] != self._request_node:
            raise SyntaxError('Request node does not match')

        delivery_data = {}

        (delivery_data['exchange'],
         delivery_data['routing_key'],
         delivery_data['host'],
         delivery_data['port'],
         delivery_data['vhost']) = request_fields[1:]
        _log.debug("""Parsed attributes of a delivery action request:
                      -exchange name: {}
                      -routing key: {}
                      -host: {}
                      -port: {}
                      -virtual host: {}""".format(
            delivery_data['exchange'],
            delivery_data['routing_key'],
            delivery_data['host'], delivery_data['port'], delivery_data['vhost']))

        # Copy delivery data dictionary to the base request fields attribute
        self._fields['delivery'] = delivery_data.copy()

    @property
    def broker(self):
        """
        :return: Broker to which response must be addressed
        """
        broker_dict = {k: self._fields['delivery'][k].toPython() for k in ('host', 'port', 'vhost') if
                       k in self._fields['delivery']}
        broker_dict['port'] = int(broker_dict['port'])
        return broker_dict

    @property
    def channel(self):
        """
        :return: Delivery channel attributes
        """
        return {k: self._fields['delivery'][k].toPython() for k in ('exchange', 'routing_key') if
                k in self._fields['delivery']}

    @property
    def recipient(self):
        """
        :return: Broker and delivery channel data
        """
        recipient = self.broker.copy()
        recipient.update(self.channel)
        return recipient


class DeliveryAction(Action):
    __metaclass__ = ABCMeta

    def __init__(self, message):
        super(DeliveryAction, self).__init__(message)

    def __reply(self, template, reason=None):
        """
        Sends a protocol reply message to the submitter
        """
        graph = build_reply(template, self.request.message_id, reason)
        reply(graph.serialize(format='turtle'), exchange=_exchange,
              routing_key='{}.{}'.format(response_rk, self.request.submitted_by),
              **self.request.broker)

    def __reply_accepted(self):
        """
        Sends an Accept message to the submitter
        """
        try:
            self.__reply(accepted_template)
        except Exception:
            # KeyError: Delivery channel data may be invalid
            # IOError: If the acceptance couldn't be sent, propagate the exception
            raise

    def _reply_failure(self, reason=None):
        """
        Sends a Failure message to the submitter
        """
        try:
            self.__reply(failure_template, reason)
            _log.info('Notified failure of request {} due to: {}'.format(self.request_id, reason))
        except Exception, e:
            # KeyError: Delivery channel data may be invalid
            # IOError: In this case, if even the failure message couldn't be sent, we cannot do anymore :)
            _log.warning('Sending failure message for request {}: {}'.format(self.request_id, e.message))

    def submit(self):
        """
        Submit and try to send an acceptance message to the submitter if everything is ok
        """
        try:
            super(DeliveryAction, self).submit()
        except SyntaxError, e:
            # If the message is of bad format, reply notifying the issue
            self._reply_failure(e.message)
            raise
        else:
            try:
                self.__reply_accepted()
            except Exception, e:
                _log.warning('Acceptance of request {} failed due to: {}'.format(self.request_id, e.message))
                # If the acceptance message couldn't be sent, remove the request and propagate the error
                self.sink.remove()
                raise

            # If everything was ok, update the request delivery state
            if self.sink.delivery is None:
                self.sink.delivery = 'accepted'


def used_channels():
    """
    Selects all channels that were declared by current requests
    """
    req_channel_keys = r.keys('{}:requests:*:'.format(AGENT_ID))
    for rck in req_channel_keys:
        try:
            channel = r.hget(rck, 'channel')
            yield channel
        except Exception as e:
            traceback.print_exc()
            _log.warning(e.message)


def channel_sharing(channel_b64):
    """
    Calculates how many channel identifiers match the given one (channel_b64)
    :param channel_b64:
    """
    return len(list(filter(lambda x: x == channel_b64, used_channels()))) - 1  # Don't count itself


class DeliverySink(Sink):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(DeliverySink, self).__init__()
        self.__deliveries_key = '{}:deliveries'.format(AGENT_ID)
        self.__ready_key = '{}:ready'.format(self.__deliveries_key)
        self.__sent_key = '{}:sent'.format(self.__deliveries_key)

    @abstractmethod
    def _save(self, action):
        """
        Stores delivery channel data
        """
        super(DeliverySink, self)._save(action)
        self._pipe.sadd(self.__deliveries_key, self._request_id)
        broker_b64 = base64.b64encode('|'.join(map(lambda x: str(x), action.request.broker.values())))
        channel_b64 = base64.b64encode('|'.join(action.request.channel.values()))
        self._pipe.hmset('{}:channels:{}'.format(AGENT_ID, channel_b64), action.request.channel)
        self._pipe.hmset('{}:brokers:{}'.format(AGENT_ID, broker_b64), action.request.broker)
        self._pipe.hset('{}'.format(self._request_key), 'channel', channel_b64)
        self._pipe.hset('{}'.format(self._request_key), 'broker', broker_b64)

    @abstractmethod
    def _load(self):
        """
        Loads all delivery data
        """
        super(DeliverySink, self)._load()
        self._dict_fields['channel'] = r.hgetall('{}:channels:{}'.format(AGENT_ID, self._dict_fields['channel']))
        self._dict_fields['broker'] = r.hgetall('{}:brokers:{}'.format(AGENT_ID, self._dict_fields['broker']))
        self._dict_fields['broker']['port'] = int(self._dict_fields['broker']['port'])
        recipient = self._dict_fields['channel'].copy()
        recipient.update(self._dict_fields['broker'])
        self._dict_fields['recipient'] = recipient

        # If present, remove previously stored delivery state so it can be retrieved each time the delivery getter
        # is invoked
        try:
            del self._dict_fields['delivery']
        except KeyError:
            pass

    @abstractmethod
    def _remove(self, pipe):
        """
        Remove all delivery data
        """

        # If this request is the only one that's using such channel, it is removed
        channel_b64 = r.hget(self._request_key, 'channel')
        sharing = channel_sharing(channel_b64)
        if not sharing:
            _log.info('Removing delivery channel ({}) for request {}'.format(channel_b64, self._request_id))
            pipe.delete('{}:channels:{}'.format(AGENT_ID, channel_b64))
        else:
            _log.info('Cannot remove delivery channel of request {}. It is being shared with {} another requests'.format(
                self.request_id, sharing))

        super(DeliverySink, self)._remove(pipe)

        pipe.srem(self.__deliveries_key, self._request_id)
        pipe.srem(self.__ready_key, self._request_id)

    @property
    def delivery(self):
        return r.hget('{}'.format(self._request_key), 'delivery')

    @delivery.setter
    def delivery(self, value):
        """
        Changes the delivery state of the request
        :param value: 'ready', 'sent', 'accepted', ...
        """
        with r.pipeline(transaction=True) as p:
            p.multi()
            if value == 'ready':
                p.sadd(self.__ready_key, self._request_id)
            elif value == 'sent':
                p.sadd(self.__sent_key, self._request_id)
            if value != 'ready':
                p.srem(self.__ready_key, self._request_id)
            p.hset('{}'.format(self._request_key), 'delivery', value)
            p.execute()
        _log.info('Request {} delivery state is now "{}"'.format(self._request_id, value))


class DeliveryResponse(Response):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        super(DeliveryResponse, self).__init__(rid)

    @abstractmethod
    def build(self):
        super(DeliveryResponse, self).build()
