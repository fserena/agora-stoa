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
from threading import Thread

import pika
from agora.stoa.actions import execute
from agora.stoa.server import app
from pika.exceptions import ConnectionClosed

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.messaging')
BROKER_CONFIG = app.config['BROKER']
EXCHANGE_CONFIG = app.config['EXCHANGE']

exchange = EXCHANGE_CONFIG['exchange']
queue = EXCHANGE_CONFIG['queue']

log.info("""Broker setup:
                - host: {}
                - port: {}
                - exchange: {}
                - queue: {}""".format(BROKER_CONFIG['host'],
                                      BROKER_CONFIG['port'],
                                      exchange, queue))


def callback(ch, method, properties, body):
    action_args = method.routing_key.split('.')[2:]
    log.info('--> Incoming {} request!'.format(action_args[0]))
    try:
        execute(*action_args, data=body)
    except (EnvironmentError, AttributeError, ValueError) as e:
        # traceback.print_exc()
        log.error(e.message)
        ch.basic_reject(delivery_tag=method.delivery_tag, requeue=True)
        log.debug('Sent REJECT')
    else:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        log.debug('Sent ACK')


def __setup_queues():
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            host=BROKER_CONFIG['host']))
    except ConnectionClosed:
        log.error('AMQP broker is not available')
    else:
        channel = connection.channel()
        log.info('Connected to the AMQP broker: {}'.format(BROKER_CONFIG))

        log.info('Declaring exchange "{}"...'.format(exchange))
        channel.exchange_declare(exchange=exchange,
                                 type='topic', durable=True)

        # Create the requests queue and binding
        channel.queue_declare(queue, durable=True)
        log.info('Declaring queue "{}"...'.format(queue))
        topic_pattern = 'stoa.request.*'
        channel.queue_bind(exchange=exchange, queue=queue, routing_key=topic_pattern)
        log.info('Binding to topic "{}"...'.format(topic_pattern))
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(callback, queue=queue)

        log.info('Ready to accept requests')
        while True:
            try:
                channel.start_consuming()
            except Exception, e:
                log.error('Messaging system failed due to: {}'.format(e.message))


th = Thread(target=__setup_queues)
th.daemon = True
th.start()
