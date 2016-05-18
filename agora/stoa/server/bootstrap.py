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

import os
import logging
import agora.stoa as root
import json
from agora.stoa.server import app
from importlib import import_module

__author__ = 'Fernando Serena'

__log_level = int(os.environ.get('LOG_LEVEL', logging.INFO))
if __log_level is None:
    __log_level = int(app.config['LOG'])

__ch = logging.StreamHandler()
__formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
__ch.setFormatter(__formatter)
__ch.setLevel(__log_level)
__logger = logging.getLogger('agora')
__logger.addHandler(__ch)
__logger.setLevel(__log_level)


def bootstrap(config=None, modules=None, metadata_pkg=None, logger_name=None, api_ext=None):
    if metadata_pkg is None:
        metadata_pkg = root
    metadata_path = os.path.join(metadata_pkg.__path__[0], 'metadata.json')
    with open(metadata_path, 'r') as stream:
        metadata = json.load(stream)

    if config is not None:
        current_config = app.config.items()
        app.config.from_object(config)
        app.config.update(current_config)

    logger_name = logger_name or 'agora.stoa.bootstrap'
    logger = logging.getLogger(logger_name)
    logger.info('--- Starting {} v{} ---'.format(metadata.get('name'), metadata.get('version')))

    logger.info('Loading stores...')
    import agora.stoa.store
    import agora.stoa.store.triples
    import agora.stoa.store.tables

    logger.info('Loading API description...')
    if api_ext is not None and isinstance(modules, list):
        for ext in api_ext:
            import_module(ext)
    from agora.stoa import api

    if modules is not None and isinstance(modules, list):
        from agora.stoa.actions import register_module
        for name, module in modules:
            register_module(name, import_module(module))

    logger.info('Loading messaging system...')
    import agora.stoa.messaging
    import agora.stoa.daemons.delivery

    logger.info('Starting REST API...')
    app.run(host='0.0.0.0', port=app.config['PORT'], debug=False, use_reloader=False)
