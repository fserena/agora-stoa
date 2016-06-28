from threading import Thread
from time import sleep
from agora.stoa.server import app

import pika


BROKER_CONFIG = app.config['BROKER']


def __setup_channel(exchange, routing_key, queue, callback):
    while True:
        connection = None
        channel = None
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=BROKER_CONFIG['host'], port=BROKER_CONFIG['port']))

            channel = connection.channel()
            channel.exchange_declare(exchange=exchange,
                                     type='topic', durable=True)

            if queue is None:
                queue = channel.queue_declare(auto_delete=True).method.queue
            else:
                channel.queue_declare(queue, durable=False)

            channel.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)
            channel.basic_consume(callback, queue=queue)
            channel.start_consuming()
        except Exception as e:
            print e.message
            if channel is not None:
                channel.close()
            if connection is not None:
                connection.close()
            sleep(1)


def start_channel(exchange, routing_key, queue, callback):
    def wrap_callback(channel, method, properties, body):
        try:
            callback(method, properties, body)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except (SyntaxError, TypeError) as e:
            print e.message
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        except Exception, e:
            print e.message
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=True)

    th = Thread(target=__setup_channel, args=[exchange, routing_key, queue, wrap_callback])
    th.daemon = True
    th.start()
