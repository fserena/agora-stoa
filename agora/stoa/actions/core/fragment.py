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
import calendar
import logging
import traceback

from datetime import datetime as dt
from redis.lock import Lock

from abc import ABCMeta, abstractmethod
from agora.client.wrapper import Agora
from agora.scholar.store.triples import cache, load_stream_triples
from agora.stoa.actions.core import STOA, RDF
from agora.stoa.actions.core.delivery import DeliveryRequest, DeliveryAction, DeliveryResponse, DeliverySink
from agora.stoa.actions.core.utils import CGraph, GraphPattern
from agora.stoa.server import app
from agora.stoa.store import r
from rdflib import Literal, XSD
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

    @property
    def ready(self):
        return self.backed

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
    def backed(self):
        return self.fragment_updated_on is not None  # and self.fragment_on_demand is None

    @property
    def fragment_id(self):
        return self._fragment_id

    def map(self, v):
        if self.mapping is not None:
            return self.mapping.get(v, v)
        return v

    @property
    def fragment_updated_on(self):
        return r.get('fragments:{}:updated'.format(self._fragment_id))

    @property
    def fragment_on_demand(self):
        return r.get('fragments:{}:on_demand'.format(self._fragment_id))

    @property
    def is_pulling(self):
        return r.get('fragments:{}:pulling'.format(self._fragment_id)) is not None

    @property
    def fragment_contexts(self):
        return r.smembers('fragments:{}:contexts'.format(self._fragment_id))

    @property
    def gp(self):
        return self._graph_pattern


class FragmentResponse(DeliveryResponse):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        super(FragmentResponse, self).__init__(rid)

    def build(self):
        super(FragmentResponse, self).build()
        lock_consume_key = 'fragments:{}:lock:consume'.format(self.sink.fragment_id)
        c_lock = r.lock(lock_consume_key, lock_class=Lock)
        c_lock.acquire()
        generator = self._build()
        try:
            for response in generator:
                yield response
        except Exception, e:
            traceback.print_exc()
            log.error(e.message)
        finally:
            c_lock.release()

    @abstractmethod
    def _build(self):
        pass

    @staticmethod
    def query(query_object):
        return cache.query(query_object)

    def graph(self, data=False):
        if data:
            return cache.get_context('/' + self.sink.fragment_id)
        else:
            return cache

    def fragment(self, stream=False, timestamp=None, result_set=False):
        def __transform(x):
            if x.startswith('"'):
                return Literal(x.replace('"', ''), datatype=XSD.string).n3(self.graph(stream).namespace_manager)
            return x

        def __build_query_pattern(x):
            if '"' in x:
                return '{ %s }' % x
            return 'OPTIONAL { %s }' % x

        def __read_contexts():
            contexts = self.sink.fragment_contexts
            triple_patterns = {context: eval(context)[1] for context in contexts}
            for context in self.sink.fragment_contexts:
                for (s, p, o) in self.graph().get_context(context):
                    yield triple_patterns[context], s, p, o

        if timestamp is None:
            timestamp = calendar.timegm(dt.now().timetuple())

        from_streaming = stream and not self.sink.backed

        if from_streaming:
            triples = load_stream_triples(self.sink.fragment_id, timestamp)
            return triples, stream
        elif stream:
            return __read_contexts(), from_streaming

        gp = [' '.join([__transform(self.sink.map(part)) for part in tp.split(' ')]) for tp in self.sink.gp]
        if result_set:
            # where_gp = ' '.join(map(__build_query_pattern, gp))
            where_gp = ' . '.join(gp)
            # TODO: Consider using selective OPTIONAL clauses
            query = """SELECT %s WHERE { %s }""" % (' '.join(self.sink.preferred_labels), where_gp)
        else:
            where_gp = ' . '.join(gp)
            query = """CONSTRUCT WHERE { %s }""" % where_gp

        result = []
        try:
            result = self.graph(data=True).query(query)
        except Exception, e:  # ParseException from query
            log.warning(e.message)
        return result, stream
