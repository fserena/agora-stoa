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

import os

__author__ = 'Fernando Serena'


def _api_port():
    return int(os.environ.get('API_PORT', 5007))


def _redis_conf(def_host, def_db, def_port):
    return {'host': os.environ.get('DB_HOST', def_host),
            'db': int(os.environ.get('DB_DB', def_db)),
            'port': int(os.environ.get('DB_PORT', def_port))}


def _agora_conf(def_host, def_port):
    return {'host': os.environ.get('AGORA_HOST', def_host),
            'port': int(os.environ.get('AGORA_PORT', def_port))}


def _broker_conf(def_host, def_port):
    return {'host': os.environ.get('AMQP_HOST', def_host),
            'port': int(os.environ.get('AMQP_PORT', def_port))}


def _exchange_conf(def_exchange, def_queue):
    return {
        'exchange': def_exchange,
        'queue': def_queue
    }


def _logging_conf(def_level):
    return int(os.environ.get('LOG_LEVEL', def_level))


class Config(object):
    PORT = _api_port()
    REDIS = _redis_conf('localhost', 4, 6379)
    AGORA = _agora_conf('localhost', 9002)
    BROKER = _broker_conf('localhost', 5672)
    EXCHANGE = _exchange_conf('stoa', 'stoa_requests')


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
