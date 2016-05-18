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

import logging
import traceback

import pika
from pika.exceptions import ChannelClosed, ConnectionClosed
from pika.spec import BasicProperties

from agora.stoa.server import app

BROKER = app.config['BROKER']

__author__ = 'Fernando Serena'

__log = logging.getLogger('agora.stoa.messaging.reply')


def reply(message, exchange=None, routing_key=None, headers=None, host=BROKER['host'], port=BROKER['port'], vhost=None):
    connection_params = pika.ConnectionParameters(host=host, port=port)
    try:
        connection = pika.BlockingConnection(connection_params)
    except ConnectionClosed, e:
        __log.warning('Bad connection parameters: {}'.format(connection_params))
        traceback.print_exc()
        return

    try:
        channel = connection.channel()
        if not any([exchange, routing_key]):
            raise AttributeError('Insufficient delivery channel parameters')

        exchange = '' if exchange is None else exchange
        routing_key = '' if routing_key is None else routing_key
        channel.confirm_delivery()

        sent = channel.basic_publish(exchange=exchange,
                                     routing_key=routing_key,
                                     body=str(message),
                                     properties=BasicProperties(headers=headers or {}),
                                     mandatory=True)

        if not sent:
            raise IOError('The channel {} does not exist'.format(routing_key))
        __log.debug('Sent message to delivery channel: \n -exchange: {}\n -routing_key: {}'.format(
            exchange, routing_key
        ))
    except ChannelClosed:
        raise EnvironmentError('The queue {} does not exist'.format(routing_key))
    finally:
        connection.close()
