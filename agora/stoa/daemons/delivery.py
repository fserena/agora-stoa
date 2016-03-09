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

from agora.stoa.actions.core import AGENT_ID
from agora.stoa.messaging.reply import reply
from agora.stoa.server import app
from agora.stoa.store import r
from concurrent.futures.thread import ThreadPoolExecutor

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.daemons.delivery')

# Load environment variables
MAX_CONCURRENT_DELIVERIES = int(app.config.get('PARAMS', {}).get('max_concurrent_deliveries', 8))

# Delivery thread pool
thp = ThreadPoolExecutor(max_workers=min(8, MAX_CONCURRENT_DELIVERIES))

log.info("""Delivery daemon setup:
                    - Maximum concurrent deliveries: {}""".format(MAX_CONCURRENT_DELIVERIES))

deliveries_key = '{}:deliveries'.format(AGENT_ID)
ready_key = '{}:ready'.format(deliveries_key)
sent_key = '{}:sent'.format(deliveries_key)


def build_response(rid):
    """
    Creates a response instance for a given request id
    :param rid: Request identifier
    :return: The response object
    """
    from agora.stoa.actions import get_instance
    response_class = r.hget('{}:requests:{}:'.format(AGENT_ID, rid), '__response_class')
    if response_class is None:
        raise AttributeError('Cannot create a response for {}'.format(rid))
    (module_name, class_name) = tuple(response_class.split('.'))
    return get_instance(module_name, class_name, rid)


def __deliver_response(rid):
    """
    The delivery task for a given request id
    :param rid: Request id
    """

    def deliver_message():
        reply(message, headers=headers, **response.sink.recipient)
        return len(str(message))

    response = None
    try:
        response = build_response(rid)
        delivery_state = response.sink.delivery
        if delivery_state == 'ready':
            messages = response.build()
            # The creation of a response object may change the corresponding request delivery state
            # (mixing, streaming, etc). The thing is that it was 'ready' before,
            # so it should has something prepared to deliver.
            n_messages = 0
            deliver_weight = 0

            message, headers = messages.next()  # Actually, this is the trigger
            deliver_weight += deliver_message()
            n_messages += 1

            deliver_delta = 0
            for (message, headers) in messages:
                message_weight = deliver_message()
                deliver_weight += message_weight
                deliver_delta += message_weight
                n_messages += 1
                if deliver_delta > 1000:
                    deliver_delta = 0
                    log.info('Delivering response of request {} [{} kB]'.format(rid, deliver_weight / 1000.0))

            deliver_weight /= 1000.0
            log.info('{} messages delivered for request {} [{} kB]'.format(n_messages, rid, deliver_weight))

        elif delivery_state == 'accepted':
            log.error('Request {} should not be marked as deliver-ready, its state is inconsistent'.format(rid))
        else:
            log.info('Response of request {} is being delivered by other means...'.format(rid))
            r.srem(ready_key, rid)
    except StopIteration:  # There was nothing prepared to deliver (Its state may have changed to
        # 'streaming')
        r.srem(ready_key, rid)
    except (EnvironmentError, AttributeError, Exception), e:
        r.srem(ready_key, rid)
        # traceback.print_exc()
        log.warning(e.message)
        if response is not None:
            log.error('Force remove of request {} due to a delivery error'.format(rid))
            response.sink.remove()
        else:
            log.error("Couldn't remove request {}".format(rid))


def __deliver_responses():
    import time
    log.info('Delivery daemon started')

    # Declare in-progress deliveries dictionary
    futures = {}
    while True:
        # Get all ready deliveries
        ready = r.smembers(ready_key)
        for rid in ready:
            # If the delivery is not in the thread pool, just submit it
            if rid not in futures:
                log.info('Response delivery of request {} is ready. Putting it in queue...'.format(rid))
                futures[rid] = thp.submit(__deliver_response, rid)

        # Clear futures that have already ceased to be ready
        for obsolete_rid in set.difference(set(futures.keys()), ready):
            if obsolete_rid in futures and futures[obsolete_rid].done():
                del futures[obsolete_rid]

        # All those deliveries that are marked as 'sent' are being cleared here along its request data
        sent = r.smembers(sent_key)
        for rid in sent:
            r.srem(ready_key, rid)
            r.srem(deliveries_key, rid)
            try:
                response = build_response(rid)
                response.sink.remove()
                log.info('Request {} was sent and cleared'.format(rid))
            except AttributeError:
                log.warning('Request number {} was deleted by other means'.format(rid))
                pass
            r.srem(sent_key, rid)

        time.sleep(0.1)


# Log delivery counters at startup
registered_deliveries = r.scard(deliveries_key)
deliveries_ready = r.scard(ready_key)
log.info("""Delivery daemon started:
                - Deliveries: {}
                - Ready: {}""".format(registered_deliveries, deliveries_ready))

# Create and start delivery daemon
__thread = Thread(target=__deliver_responses)
__thread.daemon = True
__thread.start()
