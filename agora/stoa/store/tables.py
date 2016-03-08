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

import sys
from pymongo import MongoClient

from agora.stoa.server import app

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions.store.tables')
MONGO_CONFIG = app.config['MONGO']

client = MongoClient(host=MONGO_CONFIG['host'], port=MONGO_CONFIG['port'])
log.info('Connecting to MongoDB at {}...'.format(MONGO_CONFIG))
try:
    server_info = client.server_info()
    store_mode = app.config['STORE']
    if 'memory' in store_mode:
        client.drop_database(MONGO_CONFIG['db'])

    db = client[MONGO_CONFIG['db']]
    log.info('Connected to MongoDB v{}, database: {}'.format(server_info.get('version'), MONGO_CONFIG['db']))
except Exception, e:
    log.error('MongoDB is not available: {}'.format(e.message))
    sys.exit(-1)
