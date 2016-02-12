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
import traceback

from redis.lock import Lock

from abc import ABCMeta, abstractmethod
from agora.client.wrapper import Agora
from agora.stoa.actions.core import STOA, RDF
from agora.stoa.actions.core.delivery import DeliveryRequest, DeliveryAction, DeliveryResponse, DeliverySink
from agora.stoa.actions.core.utils import CGraph, GraphPattern
from agora.stoa.server import app
from agora.stoa.store import r
from rdflib import Literal
from shortuuid import uuid

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions.fragment')
agora_conf = app.config['AGORA']
agora_client = Agora(**agora_conf)
fragment_locks = {}

# Ping Agora
try:
    _ = agora_client.prefixes
except Exception:
    log.warning('Agora is not currently available at {}'.format(agora_conf))
else:
    log.info('Connected to Agora: {}'.format(agora_conf))


class FragmentRequest(DeliveryRequest):
    def __init__(self):
        super(FragmentRequest, self).__init__()
        self.__pattern_graph = CGraph()
        self.__pattern_graph.bind('stoa', STOA)
        try:
            prefixes = agora_client.prefixes
            for p in prefixes:
                self.__pattern_graph.bind(p, prefixes[p])
        except Exception, e:
            raise EnvironmentError(e.message)

    def _extract_content(self):
        super(FragmentRequest, self)._extract_content()

        variables = set(self._graph.subjects(RDF.type, STOA.Variable))
        if not variables:
            raise SyntaxError('There are no variables specified for this request')
        log.debug(
            'Found {} variables in the the fragment pattern'.format(len(variables)))

        visited = set([])
        for v in variables:
            self.__pattern_graph.add((v, RDF.type, STOA.Variable))
            self._follow_variable(v, visited=visited)

        log.debug('Extracted (fragment) pattern graph:\n{}'.format(self.__pattern_graph.serialize(format='turtle')))

    def _add_pattern_link(self, node, triple):
        type_triple = (node, RDF.type, STOA.Variable)
        condition = type_triple in self._graph
        if condition:
            self.__pattern_graph.add(type_triple)
            if triple not in self.__pattern_graph:
                self.__pattern_graph.add(triple)
                condition = True
                log.debug('New pattern link: {}'.format(triple))
        return condition

    def _follow_variable(self, variable_node, visited=None):
        if visited is None:
            visited = set([])
        visited.add(variable_node)
        subject_pattern = self._graph.subject_predicates(variable_node)
        for (n, pr) in subject_pattern:
            if self._add_pattern_link(n, (n, pr, variable_node)) and n not in visited:
                self._follow_variable(n, visited)

        object_pattern = self._graph.predicate_objects(variable_node)
        for (pr, n) in object_pattern:
            if self._add_pattern_link(n, (variable_node, pr, n)):
                if n not in visited:
                    self._follow_variable(n, visited)
            elif n != STOA.Variable:
                self.__pattern_graph.add((variable_node, pr, n))

    @property
    def pattern(self):
        return self.__pattern_graph


class FragmentAction(DeliveryAction):
    __metaclass__ = ABCMeta

    def __init__(self, message):
        super(FragmentAction, self).__init__(message)

    def submit(self):
        super(FragmentAction, self).submit()


class FragmentSink(DeliverySink):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(FragmentSink, self).__init__()
        self._graph_pattern = GraphPattern()
        self._variables_dict = {}
        self._preferred_labels = []
        self._fragment_id = None

    @staticmethod
    def _n3(action, elm):
        return elm.n3(action.request.pattern.namespace_manager)

    def _build_graph_pattern(self, action, v_labels=None):
        variables = set(action.request.pattern.subjects(RDF.type, STOA.Variable))
        if v_labels is not None:
            self._variables_dict = v_labels.copy()
        for i, v in enumerate(variables):
            labels = list(action.request.pattern.objects(v, STOA.label))
            preferred_label = labels.pop() if len(labels) == 1 else ''
            label = preferred_label if preferred_label.startswith('?') else '?v{}'.format(i)
            self._variables_dict[v] = label
            if preferred_label:
                self._preferred_labels.append(str(preferred_label))
        for v in self._variables_dict.keys():
            v_in = action.request.pattern.subject_predicates(v)
            for (s, pr) in v_in:
                s_part = self._variables_dict[s] if s in self._variables_dict else self._n3(action, s)
                self._graph_pattern.add(u'{} {} {}'.format(s_part, self._n3(action, pr), self._variables_dict[v]))
            v_out = action.request.pattern.predicate_objects(v)
            for (pr, o) in [_ for _ in v_out if _[1] != STOA.Variable and not _[0].startswith(STOA)]:
                o_part = self._variables_dict[o] if o in self._variables_dict else (
                    '"{}"'.format(o) if isinstance(o, Literal) else self._n3(action, o))
                p_part = self._n3(action, pr) if pr != RDF.type else 'a'
                self._graph_pattern.add(u'{} {} {}'.format(self._variables_dict[v], p_part, o_part))

    def __check_gp(self):
        gp_keys = r.keys('fragments:*:gp')
        for gpk in gp_keys:
            stored_gp = GraphPattern(r.smembers(gpk))

            mapping = stored_gp.mapping(self._graph_pattern)
            if mapping:
                return gpk.split(':')[1], mapping
        return None

    @abstractmethod
    def _save(self, action):
        super(FragmentSink, self)._save(action)
        self._build_graph_pattern(action)
        fragment_mapping = self.__check_gp()
        exists = fragment_mapping is not None
        if not exists:
            self._fragment_id = str(uuid())
            self._pipe.sadd('fragments', self._fragment_id)
            self._pipe.sadd('fragments:{}:gp'.format(self._fragment_id), *self._graph_pattern)
            mapping = {str(k): str(k) for k in self._variables_dict.values()}
        else:
            self._fragment_id, mapping = fragment_mapping
            if r.get('fragments:{}:on_demand'.format(self._fragment_id)) is not None:
                self._pipe.delete('fragments:{}:sync'.format(self._fragment_id))
        self._pipe.hset(self._request_key, 'mapping', mapping)
        self._pipe.hset(self._request_key, 'preferred_labels', self._preferred_labels)
        self._pipe.sadd('fragments:{}:requests'.format(self._fragment_id), self._request_id)
        self._pipe.hset('{}'.format(self._request_key), 'fragment_id', self._fragment_id)
        self._pipe.hset('{}'.format(self._request_key), 'pattern', ' . '.join(self._graph_pattern))
        self._dict_fields['mapping'] = mapping
        if not exists:
            log.info('Request {} has started a new fragment collection: {}'.format(self._request_id, self._fragment_id))
        else:
            log.info('Request {} is going to re-use fragment {}'.format(self._request_id, self._fragment_id))
            n_fragment_reqs = r.scard('fragments:{}:requests'.format(self._fragment_id))
            log.info('Fragment {} is supporting {} more requests'.format(self._fragment_id, n_fragment_reqs))

    @abstractmethod
    def _remove(self, pipe):
        self._fragment_id = r.hget('{}'.format(self._request_key), 'fragment_id')
        pipe.srem('fragments:{}:requests'.format(self._fragment_id), self._request_id)
        super(FragmentSink, self)._remove(pipe)

    @abstractmethod
    def _load(self):
        super(FragmentSink, self)._load()
        self._fragment_id = self._dict_fields['fragment_id']
        self._graph_pattern = GraphPattern(r.smembers('fragments:{}:gp'.format(self._fragment_id)))
        mapping = self._dict_fields.get('mapping', None)
        if mapping is not None:
            mapping = eval(mapping)
        self._dict_fields['mapping'] = mapping
        preferred_labels = self._dict_fields.get('preferred_labels', None)
        if preferred_labels is not None:
            preferred_labels = eval(preferred_labels)
        self._dict_fields['preferred_labels'] = preferred_labels
        try:
            del self._dict_fields['fragment_id']
        except KeyError:
            pass

    @property
    def fragment_id(self):
        return self._fragment_id

    def map(self, v):
        if self.mapping is not None:
            return self.mapping.get(v, v)
        return v

    @property
    def gp(self):
        return self._graph_pattern


class FragmentResponse(DeliveryResponse):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        super(FragmentResponse, self).__init__(rid)

    @abstractmethod
    def build(self):
        super(FragmentResponse, self).build()
