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
import uuid

__author__ = 'Fernando Serena'

import pika
import sys
from rdflib import Graph, URIRef, RDF, Literal
from rdflib.namespace import Namespace, FOAF
import os
from datetime import datetime

CURATOR = Namespace('http://www.smartdeveloperhub.org/vocabulary/curator#')
TYPES = Namespace('http://www.smartdeveloperhub.org/vocabulary/types#')
AMQP = Namespace('http://www.smartdeveloperhub.org/vocabulary/amqp#')

accepted = False


def callback(ch, method, properties, body):
    if properties.headers.get('state', None) == 'end':
        print 'End of stream received!'
        channel.stop_consuming()
    else:
        source = properties.headers.get('source', None)
        print source,
        print body


def accept_callback(ch, method, properties, body):
    global accepted
    if not accepted:
        g = Graph()
        g.parse(StringIO.StringIO(body), format='turtle')
        if len(list(g.subjects(RDF.type, CURATOR.Accepted))) == 1:
            print 'Request accepted!'
            accepted = True


connection = pika.BlockingConnection(pika.ConnectionParameters(
    host='localhost'))
channel = connection.channel()

routing_key = ''
exchange = ''

graph = Graph()
script_dir = os.path.dirname(__file__)
with open(os.path.join(script_dir, 'stream.ttl')) as f:
    graph.parse(file=f, format='turtle')


req_node = list(graph.subjects(RDF.type, CURATOR.StreamRequest)).pop()
message_id = Literal(str(uuid.uuid4()), datatype=TYPES.UUID)
agent_id = Literal(str(uuid.uuid4()), datatype=TYPES.UUID)
graph.set((req_node, CURATOR.messageId, message_id))
graph.set((req_node, CURATOR.submittedOn, Literal(datetime.now())))
agent_node = list(graph.subjects(RDF.type, FOAF.Agent)).pop()
graph.set((agent_node, CURATOR.agentId, agent_id))

ch_node = list(graph.subjects(RDF.type, CURATOR.DeliveryChannel)).pop()

result = channel.queue_declare(exclusive=True)
queue_name = result.method.queue
# channel.queue_bind(exchange=exchange, queue=queue_name, routing_key=routing_key)
channel.basic_consume(callback, queue=queue_name, no_ack=True)

result = channel.queue_declare(exclusive=True)
accept_queue = result.method.queue
channel.queue_bind(exchange='sdh', queue=accept_queue, routing_key='curator.response.{}'.format(str(agent_id)))
channel.basic_consume(accept_callback, queue=accept_queue, no_ack=True)

# graph.set((ch_node, AMQP.queueName, Literal(queue_name)))
graph.set((ch_node, AMQP.routingKey, Literal(queue_name)))
graph.set((ch_node, AMQP.exchangeName, Literal(exchange)))
message = graph.serialize(format='turtle')


channel.basic_publish(exchange='sdh',
                      routing_key='curator.request.stream',
                      body=message)

channel.start_consuming()
