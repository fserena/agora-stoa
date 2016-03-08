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

import redis
import sys
from redis.exceptions import BusyLoadingError, RedisError

from agora.stoa.server import app

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions.store')
REDIS_CONFIG = app.config['REDIS']

log.info('Connecting to Redis at {}...'.format(REDIS_CONFIG))
pool = redis.ConnectionPool(host=REDIS_CONFIG.get('host'), port=REDIS_CONFIG.get('port'), db=REDIS_CONFIG.get('db'))
r = redis.StrictRedis(connection_pool=pool)

# Ping redis to check if it's ready
requests = 0
while True:
    try:
        r.keys('*')
        break
    except BusyLoadingError as re:
        log.warning(re.message)
    except RedisError, e:
        log.error('Redis is not available: {}'.format(e.message))
        sys.exit(-1)

store_mode = app.config['STORE']
if 'memory' in store_mode:
    r.flushdb()
