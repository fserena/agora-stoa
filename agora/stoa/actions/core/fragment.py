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
from random import random

from abc import ABCMeta, abstractmethod
from agora.client.wrapper import Agora
from agora.stoa.actions.core import STOA, RDF, AGENT_ID
from agora.stoa.actions.core.delivery import DeliveryRequest, DeliveryAction, DeliveryResponse, DeliverySink
from agora.stoa.actions.core.utils import CGraph, GraphPattern
from agora.stoa.actions.core.utils import tp_parts
from agora.stoa.server import app
from agora.stoa.store import r
from rdflib import Literal, URIRef
from shortuuid import uuid

__author__ = 'Fernando Serena'

log = logging.getLogger('agora.stoa.actions.fragment')
agora_conf = app.config['AGORA']
PASS_THRESHOLD = app.config['BEHAVIOUR']['pass_threshold']
agora_client = Agora(**agora_conf)
fragment_locks = {}

# Ping Agora
try:
    _ = agora_client.prefixes
except Exception:
    log.warning('Agora is not currently available at {}'.format(agora_conf))
else:
    log.info('Connected to Agora: {}'.format(agora_conf))

log.info("""Behaviour parameters:
                    - Pass threshold: {}""".format(PASS_THRESHOLD))


class FragmentRequest(DeliveryRequest):
    def __init__(self):
        """
        Prepares the pattern graph object which will store the one that is contained in the
        request
        """
        super(FragmentRequest, self).__init__()
        self.__request_graph = CGraph()
        self.__request_graph.bind('stoa', STOA)
        self.__preferred_labels = set([])
        self.__variable_labels = {}
        self._graph_pattern = GraphPattern()

        # Copy Agora prefixes to the pattern graph
        try:
            prefixes = agora_client.prefixes
            for p in prefixes:
                self.__request_graph.bind(p, prefixes[p])
        except Exception, e:
            raise EnvironmentError(e.message)

    def _extract_content(self, request_type=None):
        super(FragmentRequest, self)._extract_content(request_type)

        # Firstly, it looks for all Variables that are inside the request
        variables = set(self._graph.subjects(RDF.type, STOA.Variable))
        if not variables:
            raise SyntaxError('There are no variables specified for this request')
        log.debug(
            'Found {} variables in the the fragment pattern'.format(len(variables)))

        # Secondly, try to identify all links between variables (avoiding cycles)
        visited = set([])
        for v in variables:
            self.__request_graph.add((v, RDF.type, STOA.Variable))
            self.__follow_variable(v, visited=visited)

        # Thirdly, the request graph is filtered and the request pattern only contains
        # the relevant nodes and their relations

        # Finally, an Agora-compliant Graph Pattern is created and offered as a property
        self.__build_graph_pattern()

        log.debug('Extracted (fragment) pattern graph:\n{}'.format(self.__request_graph.serialize(format='turtle')))

    def __n3(self, elm):
        """
        :param elm: The element to be n3-formatted
        :return: The n3 representation of elm
        """
        return elm.n3(self.__request_graph.namespace_manager)

    def __follow_variable(self, variable_node, visited=None):
        """
        Recursively follows one variable node of the request graph
        :param variable_node: Starting node
        :param visited: Track of visited variable nodes
        :return:
        """

        def add_pattern_link(node, triple):
            type_triple = (node, RDF.type, STOA.Variable)
            condition = type_triple in self._graph
            if condition:
                self.__request_graph.add(type_triple)
            elif isinstance(node, URIRef):
                condition = True
            if condition:
                if triple not in self.__request_graph:
                    self.__request_graph.add(triple)
                    log.debug('New pattern link: {}'.format(triple))
            return condition

        if visited is None:
            visited = set([])
        visited.add(variable_node)
        subject_pattern = self._graph.subject_predicates(variable_node)
        for (n, pr) in subject_pattern:
            if add_pattern_link(n, (n, pr, variable_node)) and n not in visited:
                self.__follow_variable(n, visited)

        object_pattern = self._graph.predicate_objects(variable_node)
        for (pr, n) in object_pattern:
            if add_pattern_link(n, (variable_node, pr, n)):
                if n not in visited:
                    self.__follow_variable(n, visited)
            elif n != STOA.Variable:
                self.__request_graph.add((variable_node, pr, n))

    def __build_graph_pattern(self):
        """
        Creates a GraphPattern with all the identified (Agora compliant) triple patterns
        in the request graph
        """

        def preferred_label():
            # Each variable may have a property STOA.label that specifies its desired label
            labels = list(self.__request_graph.objects(v, STOA.label))
            p_label = labels.pop() if len(labels) == 1 else ''
            if p_label:
                self.__preferred_labels.add(str(p_label))
            return p_label if p_label.startswith('?') else '?v{}'.format(i)

        # Populates a dictionary with all variables and their labels
        variables = self.__request_graph.subjects(RDF.type, STOA.Variable)
        for i, v in enumerate(variables):
            self.__variable_labels[v] = preferred_label()

        # For each variable, generates one triple pattern per relation with other nodes as either subject or object
        for v in self.__variable_labels.keys():
            v_in = self.__request_graph.subject_predicates(v)
            for (s, pr) in v_in:
                s_part = self.__variable_labels[s] if s in self.__variable_labels else self.__n3(s)
                self._graph_pattern.add(u'{} {} {}'.format(s_part, self.__n3(pr), self.__variable_labels[v]))
            v_out = self.__request_graph.predicate_objects(v)
            for (pr, o) in [_ for _ in v_out if _[1] != STOA.Variable and not _[0].startswith(STOA)]:
                o_part = self.__variable_labels[o] if o in self.__variable_labels else (
                    '"{}"'.format(o) if isinstance(o, Literal) else self.__n3(o))
                p_part = self.__n3(pr) if pr != RDF.type else 'a'
                self._graph_pattern.add(u'{} {} {}'.format(self.__variable_labels[v], p_part, o_part))

    @property
    def pattern(self):
        """
        :return: The request graph pattern
        """
        return self._graph_pattern

    @property
    def preferred_labels(self):
        """
        :return: The variable preferred labels
        """
        return self.__preferred_labels

    @property
    def variable_labels(self):
        """
        :return: All variable labels
        """
        return self.__variable_labels.values()

    def variable_label(self, n):
        label = self.__variable_labels.get(n, None)
        if isinstance(label, Literal):
            label = label.toPython()
        return label


class FragmentAction(DeliveryAction):
    __metaclass__ = ABCMeta

    def __init__(self, message):
        super(FragmentAction, self).__init__(message)


class FragmentSink(DeliverySink):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(FragmentSink, self).__init__()
        self._graph_pattern = GraphPattern()
        self._fragment_pattern = GraphPattern()
        self._filter_mapping = {}
        self._fragments_key = '{}:fragments'.format(AGENT_ID)
        self.__f_key_pattern = '{}:'.format(self._fragments_key) + '{}'
        self._fragment_key = None
        self._preferred_labels = set([])

    def __check_gp_mappings(self, gp=None):
        """
        Used in _save method. Seeks matches with some fragment already registered
        :param gp: By default, _graph_pattern attribute is used when gp is None
        :return: The matching fragment id and the mapping dictionary or None if there is no matching
        """
        if gp is None:
            gp = self._graph_pattern
        gp_keys = r.keys('{}:*:gp'.format(self._fragments_key))
        for gpk in gp_keys:
            stored_gp = GraphPattern(r.smembers(gpk))
            mapping = stored_gp.mapping(gp)
            if mapping:
                return gpk.split(':')[-2], mapping
        return None

    def _remove_tp_filters(self, tp):
        """
        Transforms a triple pattern that may contain filters to a new one with both subject and object bounded
        to variables
        :param tp: The triple pattern to be filtered
        :return: Filtered triple pattern
        """

        def __create_var(elm, predicate):
            if elm in self._filter_mapping.values():
                elm = list(filter(lambda x: self._filter_mapping[x] == elm, self._filter_mapping)).pop()
            elif predicate(elm):
                v = '?{}'.format(uuid())
                self._filter_mapping[v] = elm
                elm = v
            return elm

        s, p, o = tp_parts(tp)
        s = __create_var(s, lambda x: '<' in x and '>' in x)
        o = __create_var(o, lambda x: '"' in x or ('<' in x and '>' in x))
        return '{} {} {}'.format(s, p, o)

    def _generalize_gp(self):
        # Create a filtered graph pattern from the request one (general_gp)
        general_gp = GraphPattern()
        for new_tp in map(lambda x: self._remove_tp_filters(x), self._graph_pattern):
            general_gp.add(new_tp)
        if self._filter_mapping:
            # Store the filter mapping
            self._pipe.hmset('{}filters'.format(self._request_key), self._filter_mapping)
        return general_gp

    @abstractmethod
    def _save(self, action, general=True):
        """
        Stores data relating to the recovery of a fragment for this request
        """

        super(FragmentSink, self)._save(action)

        # Recover pattern from the request object
        self._graph_pattern = action.request.pattern

        effective_gp = self._generalize_gp() if general else self._graph_pattern

        # fragment_mapping is a tuple like (fragment_id, mapping)
        fragment_mapping = self.__check_gp_mappings(gp=effective_gp)
        exists = fragment_mapping is not None

        # Decide to proceed depending on whether it's the first time this request is received and the fragment
        # is already known
        proceed = action.id in self.passed_requests or (
            random() > 1.0 - PASS_THRESHOLD if not exists else random() > PASS_THRESHOLD)
        if not proceed:
            self.do_pass(action)
        if action.id in self.passed_requests:
            self.passed_requests.remove(action.id)

        if not exists:
            # If there is no mapping, register a new fragment collection for the general graph pattern
            fragment_id = str(uuid())
            self._fragment_key = self.__f_key_pattern.format(fragment_id)
            self._pipe.sadd(self._fragments_key, fragment_id)
            self._pipe.sadd('{}:gp'.format(self._fragment_key), *effective_gp)
            mapping = {str(k): str(k) for k in action.request.variable_labels}
            mapping.update({str(k): str(k) for k in self._filter_mapping})
        else:
            fragment_id, mapping = fragment_mapping
            self._fragment_key = self.__f_key_pattern.format(fragment_id)
            # Remove the sync state if the fragment is on-demand mode
            if r.get('{}:on_demand'.format(self._fragment_key)) is not None:
                self._pipe.delete('{}:sync'.format(self._fragment_key))

        # Here the following is persisted: mapping, pref_labels, fragment-request links and the original graph_pattern
        self._pipe.hmset('{}map'.format(self._request_key), mapping)
        if action.request.preferred_labels:
            self._pipe.sadd('{}pl'.format(self._request_key), *action.request.preferred_labels)
        self._pipe.sadd('{}:requests'.format(self._fragment_key), self._request_id)
        self._pipe.hset('{}'.format(self._request_key), 'fragment_id', fragment_id)
        self._pipe.sadd('{}gp'.format(self._request_key), *self._graph_pattern)
        self._pipe.hset('{}'.format(self._request_key), 'pattern', ' . '.join(self._graph_pattern))

        # Populate attributes that may be required during the rest of the submission process
        self._dict_fields['mapping'] = mapping
        self._dict_fields['preferred_labels'] = action.request.preferred_labels
        self._dict_fields['fragment_id'] = fragment_id

        if not exists:
            log.info('Request {} has started a new fragment collection: {}'.format(self._request_id, fragment_id))
        else:
            log.info('Request {} is going to re-use fragment {}'.format(self._request_id, fragment_id))
            n_fragment_reqs = r.scard('{}:requests'.format(self._fragment_key))
            log.info('Fragment {} is supporting {} more requests'.format(fragment_id, n_fragment_reqs))

    @abstractmethod
    def _remove(self, pipe):
        """
        Removes data relating to the recovery of a fragment for this request
        """
        fragment_id = r.hget('{}'.format(self._request_key), 'fragment_id')
        self._fragment_key = self.__f_key_pattern.format(fragment_id)
        pipe.srem('{}:requests'.format(self._fragment_key), self._request_id)
        pipe.delete('{}gp'.format(self._request_key))
        pipe.delete('{}map'.format(self._request_key))
        pipe.delete('{}pl'.format(self._request_key))
        pipe.delete('{}filters'.format(self._request_key))
        super(FragmentSink, self)._remove(pipe)

    @abstractmethod
    def _load(self):
        """
        Loads data relating to the recovery of a fragment for this request
        """
        super(FragmentSink, self)._load()
        self._fragment_key = self.__f_key_pattern.format(self.fragment_id)
        self._graph_pattern = GraphPattern(r.smembers('{}gp'.format(self._request_key)))
        self._fragment_pattern = GraphPattern(r.smembers('{}:gp'.format(self._fragment_key)))
        self._filter_mapping = r.hgetall('{}filters'.format(self._request_key))
        self._dict_fields['mapping'] = r.hgetall('{}map'.format(self._request_key))
        self._dict_fields['preferred_labels'] = set(r.smembers('{}pl'.format(self._request_key)))

    def map(self, v, fmap=False):
        """
        Maps a fragment variable to the corresponding variable or filter of the request
        :param v: Fragment variable
        :param fmap: Map to filter or not
        :return: The mapped variable (or filter)
        """
        if self.mapping is not None:
            v = self.mapping.get(v, v)
            if fmap:
                v = self._filter_mapping.get(v, v)
        return v

    @property
    def gp(self):
        """
        :return: The request Graph Pattern
        """
        return self._graph_pattern

    @property
    def fragment_gp(self):
        """
        :return: The Graph Pattern of the supporting fragment
        """
        return self._fragment_pattern

    @property
    def filter_mapping(self):
        """
        :return: The mapping dictionary between original filters and on-the-fly created variables
        """
        return self._filter_mapping


class FragmentResponse(DeliveryResponse):
    __metaclass__ = ABCMeta

    def __init__(self, rid):
        super(FragmentResponse, self).__init__(rid)

    @abstractmethod
    def build(self):
        super(FragmentResponse, self).build()
