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
import uuid

import os
__author__ = 'Fernando Serena'


def _api_port():
    return int(os.environ.get('API_PORT', 5007))


def _agent_id():
    return os.environ.get('AGENT_ID', uuid.uuid4())


def _redis_conf(def_host, def_port, def_db):
    return {'host': os.environ.get('DB_HOST', def_host),
            'db': int(os.environ.get('DB_DB', def_db)),
            'port': int(os.environ.get('DB_PORT', def_port))}


def _mongo_conf(def_host, def_port, def_db):
    return {'host': os.environ.get('MONGO_HOST', def_host),
            'db': os.environ.get('MONGO_DB', def_db),
            'port': int(os.environ.get('MONGO_PORT', def_port))}


def _agora_conf(def_host, def_port):
    return {'host': os.environ.get('AGORA_HOST', def_host),
            'port': int(os.environ.get('AGORA_PORT', def_port))}


def _broker_conf(def_host, def_port):
    return {'host': os.environ.get('AMQP_HOST', def_host),
            'port': int(os.environ.get('AMQP_PORT', def_port))}


def _exchange_conf(def_exchange, def_queue, def_tp, def_response_rk):
    return {
        'exchange': os.environ.get('EXCHANGE_NAME', def_exchange),
        'queue': os.environ.get('QUEUE_NAME', def_queue),
        'topic_pattern': os.environ.get('TOPIC_PATTERN', def_tp),
        'response_rk': os.environ.get('RESPONSE_RK_PREFIX', def_response_rk)
    }


def _behaviour_conf(def_pass_threshold):
    return {
        'pass_threshold': float(os.environ.get('PASS_THRESHOLD', def_pass_threshold))
    }


def _logging_conf(def_level):
    return int(os.environ.get('LOG_LEVEL', def_level))


class Config(object):
    PORT = _api_port()
    REDIS = _redis_conf('localhost', 6379, 4)
    MONGO = _mongo_conf('localhost', 27017, 'scholar')
    AGORA = _agora_conf('localhost', 9002)
    BROKER = _broker_conf('localhost', 5672)
    EXCHANGE = _exchange_conf('stoa', 'stoa_requests', 'stoa.request.*', 'stoa.response')
    BEHAVIOUR = _behaviour_conf(0.1)
    ID = _agent_id()


class DevelopmentConfig(Config):
    DEBUG = True
    LOG = logging.DEBUG


class TestingConfig(Config):
    DEBUG = False
    LOG = logging.DEBUG
    TESTING = True


class ProductionConfig(Config):
    DEBUG = False
    LOG = _logging_conf(logging.INFO)
