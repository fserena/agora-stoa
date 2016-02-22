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

import itertools

import networkx as nx
from networkx.algorithms.isomorphism import DiGraphMatcher
from rdflib import Graph

__author__ = 'Fernando Serena'


def parse_bool(s):
    """
    :param s: String to be parsed
    :return: True iff s is equal to 'True', otherwise False
    """
    if type(s) == str:
        if s == 'True':
            return True
    return False


class CGraph(Graph):
    def objects(self, subject=None, predicate=None, card=None):
        objs_gen = super(CGraph, self).objects(subject, predicate)
        if card is None:
            return objs_gen

        objs_gen, gen_bak = itertools.tee(objs_gen)
        objs = list(objs_gen)

        if card == 1:
            if not (0 < len(objs) < 2):
                raise ValueError(len(objs))
            return objs.pop()

        return gen_bak

    def subjects(self, predicate=None, object=None, card=None):
        subs_gen = super(CGraph, self).subjects(predicate, object)
        if card is None:
            return subs_gen

        subs_gen, gen_bak = itertools.tee(subs_gen)
        subs = list(subs_gen)

        if card == 1:
            if not (0 < len(subs) < 2):
                raise ValueError(len(subs))
            return subs.pop()

        return gen_bak


def chunks(l, n):
    """
    Yield successive n-sized chunks from l.
    :param l:
    :param n:
    :return: Generated chunks
    """
    if n:
        if getattr(l, '__iter__') is not None:
            l = l.__iter__()
        finished = False
        while not finished:
            chunk = []
            try:
                for _ in range(n):
                    chunk.append(l.next())
            except StopIteration:
                finished = True
            yield chunk


class GraphPattern(set):
    """
    An extension of the set class that represents a graph pattern, which is a set of triple patterns
    """

    def __init__(self, s=()):
        super(GraphPattern, self).__init__(s)

    # @property
    # def gp(self):
    #     return self

    @property
    def wire(self):
        """
        Creates a graph from the graph pattern
        :return: The graph (networkx)
        """
        g = nx.DiGraph()
        for tp in self:
            (s, p, o) = tuple(tp_parts(tp.strip()))
            edge_data = {'link': p}
            g.add_node(s)
            if o.startswith('?'):
                g.add_node(o)
            else:
                g.add_node(o, literal=o)
                edge_data['to'] = o
            g.add_edge(s, o, **edge_data)

        return g

    def __eq__(self, other):
        """
        Two graph patterns are equal if they are isomorphic**
        """
        if not isinstance(other, GraphPattern):
            return super(GraphPattern, self).__eq__(other)

        mapping = self.mapping(other)
        return mapping is not None

    def __repr__(self):
        return str(list(self))

    def mapping(self, other):
        """
        :return: If there is any, the mapping with another graph pattern
        """
        if not isinstance(other, GraphPattern):
            return None

        my_wire = self.wire
        others_wire = other.wire

        def __node_match(n1, n2):
            return n1 == n2

        def __edge_match(e1, e2):
            return e1 == e2

        matcher = DiGraphMatcher(my_wire, others_wire, node_match=__node_match, edge_match=__edge_match)
        mapping = list(matcher.isomorphisms_iter())
        if len(mapping) == 1:
            return mapping.pop()
        else:
            return None


def tp_parts(tp):
    """
    :param tp: A triple pattern string
    :return: A string-based 3-tuple like (subject, predicate, object)
    """
    if tp.endswith('"'):
        parts = [tp[tp.find('"'):]]
        st = tp.replace(parts[0], '').rstrip()
        parts = st.split(" ") + parts
    else:
        parts = tp.split(' ')
    return tuple(parts)
