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
import inspect
import logging

from agora.stoa.actions.core.base import Action
from types import ModuleType

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions')
action_modules = {}


def register_module(name, module):
    """
    Registers a Stoa module
    :param name: The unique module name
    :param module: Module instance
    """
    if name in action_modules:
        raise NameError('The module {} already exists'.format(name))
    if not isinstance(module, ModuleType):
        raise AttributeError('{} is not a valid module instance'.format(module))
    action_modules[name] = module


def search_module(module, predicate, limit=1):
    """
    Searches in a module for elements that satisfy a given predicate
    :param module: A module name
    :param predicate: A predicate to check module elements
    :param limit: Default 1
    :return:
    """
    py_mod = action_modules.get(module, None)

    if py_mod is not None:
        cand_elms = filter(predicate,
                           inspect.getmembers(py_mod, lambda x: inspect.isclass(x) and not inspect.isabstract(x)))
        if len(cand_elms) > limit:
            raise EnvironmentError('Too many elements in module {}'.format(module))
        return cand_elms

    return None


def get_instance(module, clz, *args):
    """
    Creates an instance of a given class and module
    :param module: Module name
    :param clz: Instance class
    :param args: Creation arguments
    :return: The instance
    """
    module = action_modules[module]
    class_ = getattr(module, clz)
    instance = class_(*args)
    return instance


def execute(*args, **kwargs):
    """
    Prepares and submits a Stoa-action
    :param args: Action context arguments
    :param kwargs: Action data dictionary
    """

    # The action name (that must match one of the registered modules in order to be submitted)
    name = args[0]
    log.debug('Searching for a compliant "{}" action handler...'.format(name))

    try:
        _, clz = search_module(name,
                               lambda (_, cl): issubclass(cl, Action) and cl != Action).pop()

    except EnvironmentError:
        raise SystemError('Cannot handle {} requests'.format(name))
    except IndexError:
        raise ("Couldn't find an Action class inside {} module".format(name))

    try:
        # Extract the request message from kwargs,
        data = kwargs.get('data', None)
        log.debug(
            'Found! Requesting an instance of {} to perform a/n {} action described as:\n{}'.format(clz, name,
                                                                                                    data))

        # Create the proper action instance...
        action = clz(data)
    except IndexError:
        raise NameError('Action module found but class is missing: "{}"'.format(name))
    else:
        # and submit!
        rid = action.submit()
        if rid is not None:
            log.info('A {} request was successfully submitted with id {}'.format(name, rid))
