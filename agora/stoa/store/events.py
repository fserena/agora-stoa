from threading import Thread
from time import sleep

import pika


def __setup_channel(exchange, routing_key, queue, callback):
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host='localhost'))

            channel = connection.channel()
            channel.exchange_declare(exchange=exchange,
                                     type='topic', durable=True)

            if queue is None:
                queue = channel.queue_declare(auto_delete=True).method.queue
            else:
                channel.queue_declare(queue, durable=False)

            channel.queue_bind(exchange=exchange, queue=queue, routing_key=routing_key)
            channel.basic_consume(callback, queue=queue)
            # channel.basic_qos(prefetch_count=1)
            channel.start_consuming()
        except Exception as e:
            print e.message
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
