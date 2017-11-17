#!/usr/bin/env python
# -*- coding: utf-8 -*-

# netgraph.py --- Plot weighted, directed graphs of medium size (10-100 nodes).

# Copyright (C) 2016 Paul Brodersen <paulbrodersen+netgraph@gmail.com>

# Author: Paul Brodersen <paulbrodersen+netgraph@gmail.com>

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""
Netgraph
========

Summary:
--------
Module to plot weighted, directed graphs of medium size (10-100 nodes).
Unweighted, undirected graphs will look perfectly fine, too, but this module
might be overkill for such a use case.

Raison d'etre:
--------------
Existing draw routines for networks/graphs in python use fundamentally different
length units for different plot elements. This makes it hard to
    - provide a consistent layout for different axis / figure dimensions, and
    - judge the relative sizes of elements a priori.
This module amends these issues (while sacrificing speed).

Example:
--------
import numpy as np
import matplotlib.pyplot as plt
import netgraph

# construct sparse, directed, weighted graph
# with positive and negative edges
total_nodes = 20
total_edges = 40
edges = np.random.randint(0, total_nodes, size=(total_edges, 2))
weights = np.random.randn(total_edges)
adjacency = np.concatenate([edges, weights[:,None]], axis=1)

# plot
netgraph.draw(adjacency)
plt.show()
"""

__version__ = 0.0
__author__ = "Paul Brodersen"
__email__ = "paulbrodersen+netgraph@gmail.com"


import numpy as np
import itertools
import numbers

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.cbook as cb

from matplotlib.colors import colorConverter, Colormap
from matplotlib.collections import LineCollection


BASE_NODE_SIZE = 1e-2 # i.e. node sizes are in percent of axes space (x,y <- [0, 1], [0,1])
BASE_EDGE_WIDTH = 1e-2 # i.e. edge widths are in percent of axis space (x,y <- [0, 1], [0,1])


def draw(adjacency, node_positions=None, node_labels=None, edge_labels=None, ax=None, **kwargs):
    """
    Convenience function that tries to do "the right thing".

    For a full list of available arguments, and
    for finer control of the individual draw elements,
    please refer to the documentation of

        draw_nodes()
        draw_edges()
        draw_node_labels()
        draw_edge_labels()

    Arguments
    ----------
    adjacency: m-long iterable of 2-tuples or 3-tuples or equivalent (such as (m, 2) or (m, 3) ndarray)
        Adjacency of the network in sparse matrix format.
        Each tuple corresponds to an edge defined by (source, target) or (source, target, weight).

    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    node_labels : dict key -> str (default None)
       Dictionary mapping nodes to labels.
       Only nodes in the dictionary are labelled.

    edge_labels : dictionary (default None)
        Dictionary mapping edge specified by (source index, target index) to label.
        Only edges in the dictionary are labelled.

    ax : matplotlib.axis instance or None (default None)
       Axis to plot onto; if none specified, one will be instantiated with plt.gca().

    See Also
    --------
    draw_nodes()
    draw_edges()
    draw_node_labels()
    draw_edge_labels()

    """

    if ax is None:
        ax = plt.gca()

    if _is_directed(adjacency):
        kwargs.setdefault('draw_arrows', True)

    if _is_weighted(adjacency):

        # reorder edges such that edges with large absolute weights are plotted last
        # and hence most prominent in the graph
        weights = np.array([weight for (source, target, weight) in adjacency])
        edge_zorder = np.argsort(weights)
        edge_zorder = {(source, target): index for (source, target, weight), index in zip(adjacency, edge_zorder)}

        # apply edge_vmin, edge_vmax
        edge_vmin = kwargs.get('edge_vmin', np.nanmin(weights))
        edge_vmax = kwargs.get('edge_vmax', np.nanmax(weights))
        weights[weights<edge_vmin] = edge_vmin
        weights[weights>edge_vmax] = edge_vmax

        # rescale weights such that
        #  - the colormap midpoint is at zero-weight, and
        #  - negative and positive weights have comparable intensity values
        weights /= np.nanmax([np.nanmax(np.abs(weights)), np.abs(edge_vmax), np.abs(edge_vmin)]) # [-1, 1]
        weights += 1. # [0, 2]
        weights /= 2. # [0, 1]

        # edge_color = {(edge[0], edge[1]): weight for (edge, weight) in zip(adjacency, weights)}
        # kwargs.setdefault('edge_color', edge_color)

        adjacency = [(source, target, new_weight) for (source, target, old_weight), new_weight in zip(adjacency, weights)]
        adjacency_matrix = _edge_list_to_adjacency_matrix(adjacency)
        kwargs.setdefault('edge_color', adjacency_matrix)

        kwargs.setdefault('edge_vmin', 0.)
        kwargs.setdefault('edge_vmax', 1.)
        kwargs.setdefault('edge_cmap', 'RdGy')
        kwargs.setdefault('edge_zorder', edge_zorder)

    if node_positions is None:
        node_positions = _get_positions(adjacency)

    draw_edges(adjacency, node_positions, **kwargs)
    draw_nodes(node_positions, **kwargs)

    if node_labels is not None:
        draw_node_labels(node_labels, node_positions, **kwargs)

    if edge_labels is not None:
        draw_edge_labels(edge_labels, node_positions, **kwargs)

    _update_view(node_positions, node_size=3, ax=ax)
    _make_pretty(ax)

    return ax

def _is_directed(adjacency):
    # unpack to ensure that adjacency is a list of tuples
    adjacency = set([(edge[0], edge[1]) for edge in adjacency])

    # test for bi-directional edges
    for source, target in adjacency:
        if (target, source) in adjacency:
            return True

    return False

def _is_weighted(adjacency):
    if len(adjacency[0]) > 2:
        return True
    else:
        return False

def _get_positions(adjacency, **kwargs):
    """
    Position nodes using Fruchterman-Reingold force-directed algorithm.
    Weights are ignored as they typically do not result in a visually pleasing
    arrangement of nodes.

    If neither igraph nor networkx are available, positions are chosen randomly.

    Arguments:
    ----------
    adjacency: m-long iterable of 2-tuples or 3-tuples or equivalent (such as (m, 2) or (m, 3) ndarray)
        Adjacency of the network in sparse matrix format.
        Each tuple corresponds to an edge defined by (source, target) or (source, target, weight).

    **kwargs: passed to networkx.layout.spring_layout() or fallback igraph.Graph.layout_fruchterman_reingold()

    Returns:
    --------
    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    """

    edges = [(edge[0], edge[1]) for edge in adjacency]
    nodes = np.unique(edges)

    # networkx / igraph are heavy dependencies -- only import them if the user actually needs them
    try:
        import networkx
        graph = networkx.Graph(edges)
        positions = networkx.layout.spring_layout(graph, **kwargs)

    except ImportError:
        import warnings
        warnings.warn("Dependency networkx not available. Falling back to igraph.")

        try:
            import igraph
            graph = igraph.Graph(edges=edges, loops=False)
            positions = graph.layout_fruchterman_reingold()

            # normalise to 0-1
            positions = np.array(positions)
            positions -= np.min(positions)
            positions /= np.max(positions)

            # convert to dict
            positions = {node: (x, y) for node, (x, y) in zip(nodes, positions)}

        except ImportError:
            warnings.warn("Neither networkx nor igraph available. Assigning random positions to nodes.")
            positions = np.random.rand(len(nodes), 2)

            # convert to dict
            positions = {node: (x, y) for node, (x, y) in zip(nodes, positions)}

    return positions


def draw_nodes(node_positions,
               node_shape='o',
               node_size=3.,
               node_edge_width=0.5,
               node_color='w',
               node_edge_color='k',
               cmap=None,
               vmin=None,
               vmax=None,
               node_alpha=1.0,
               ax=None,
               **kwargs):
    """
    Draw node markers at specified positions.

    Arguments
    ----------
    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    node_shape : string or dict key->string (default 'o')
       The shape of the node. Specification is as for matplotlib.scatter
       marker, one of 'so^>v<dph8'.
       If a single string is provided all nodes will have the same shape.

    node_size : scalar or (n,) or dict key -> float (default 3.)
       Size (radius) of nodes in percent of axes space.

    node_edge_width : scalar or (n,) or dict key -> float (default 0.5)
       Line width of node marker border.

    node_color : color string, or array of floats (default 'w')
       Node color. Can be a single color format string
       or a sequence of colors with the same length as node_positions.
       If numeric values are specified they will be mapped to
       colors using the cmap and vmin/vmax parameters.

    node_edge_color : color string, or array of floats (default 'k')
       Node color. Can be a single color format string,
       or a sequence of colors with the same length as node_positions.
       If numeric values are specified they will be mapped to
       colors using the cmap and vmin,vmax parameters.

    cmap : Matplotlib colormap (default None)
       Colormap for mapping intensities of nodes.

    vmin, vmax : floats (default None)
       Minimum and maximum for node colormap scaling.

    node_alpha : float (default 1.)
       The node transparency (node face and edge).

    ax : Matplotlib Axes object, optional
       Draw the graph in the specified Matplotlib axes.

    Returns
    -------
    artists: dict
        Dictionary mapping node index to the node face artist and node edge artist,
        where both artists are instances of matplotlib.patches.
        To access the node face of a node: artists[node]['face']
        To access the node edge of a node: artists[node]['edge']

    """

    if ax is None:
        ax = plt.gca()

    # convert all inputs to dicts mapping node->property
    nodes = node_positions.keys()
    number_of_nodes = len(nodes)

    node_color = _parse_color_input(number_of_nodes, node_color, cmap, vmin, vmax, node_alpha)
    node_edge_color = _parse_color_input(number_of_nodes, node_edge_color, cmap, vmin, vmax, node_alpha)

    if isinstance(node_size, (int, float)):
        node_size = {node:node_size for node in nodes}
    if isinstance(node_edge_width, (int, float)):
        node_edge_width = {node: node_edge_width for node in nodes}
    if isinstance(node_shape, str):
        node_shape = {node:node_shape for node in nodes}

    # rescale
    node_size       = {node: size  * BASE_NODE_SIZE for (node, size)  in node_size.items()}
    node_edge_width = {node: width * BASE_NODE_SIZE for (node, width) in node_edge_width.items()}

    artists = dict()
    for node in nodes:
        # create node edge artist:
        # simulate node edge by drawing a slightly larger node artist;
        # I wish there was a better way to do this,
        # but this seems to be the only way to guarantee constant proportions,
        # as linewidth argument in matplotlib.patches will not be proportional
        # to a given node radius
        node_edge_artist = _get_node_artist(shape=node_shape[node],
                                            position=node_positions[node],
                                            size=node_size[node],
                                            facecolor=node_edge_color[node],
                                            zorder=2)

        # create node artist
        node_artist = _get_node_artist(shape=node_shape[node],
                                       position=node_positions[node],
                                       size=node_size[node] -node_edge_width[node],
                                       facecolor=node_color[node],
                                       zorder=2)

        # add artists to axis
        ax.add_artist(node_edge_artist)
        ax.add_artist(node_artist)

        # return handles to artists
        artists[node] = dict()
        artists[node]['edge'] = node_edge_artist
        artists[node]['face'] = node_artist

    return artists


def _get_node_artist(shape, position, size, facecolor, zorder=2):
    if shape == 'o': # circle
        artist = matplotlib.patches.Circle(xy=position,
                                           radius=size,
                                           facecolor=facecolor,
                                           linewidth=0.,
                                           zorder=zorder)
    elif shape == '^': # triangle up
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=3,
                                                   facecolor=facecolor,
                                                   orientation=0,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == '<': # triangle left
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=3,
                                                   facecolor=facecolor,
                                                   orientation=np.pi*0.5,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 'v': # triangle down
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=3,
                                                   facecolor=facecolor,
                                                   orientation=np.pi,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == '>': # triangle right
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=3,
                                                   facecolor=facecolor,
                                                   orientation=np.pi*1.5,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 's': # square
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=4,
                                                   facecolor=facecolor,
                                                   orientation=np.pi*0.25,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 'd': # diamond
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=4,
                                                   facecolor=facecolor,
                                                   orientation=np.pi*0.5,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 'p': # pentagon
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=5,
                                                   facecolor=facecolor,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 'h': # hexagon
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=6,
                                                   facecolor=facecolor,
                                                   linewidth=0.,
                                                   zorder=zorder)
    elif shape == 8: # octagon
        artist = matplotlib.patches.RegularPolygon(xy=position,
                                                   radius=size,
                                                   numVertices=8,
                                                   facecolor=facecolor,
                                                   linewidth=0.,
                                                   zorder=zorder)
    else:
        raise ValueError("Node shape one of: ''so^>v<dph8'. Current shape:{}".format(shape))

    return artist


def draw_edges(adjacency,
               node_positions,
               node_size=3.,
               edge_width=1.,
               edge_color='k',
               edge_cmap=None,
               edge_vmin=None,
               edge_vmax=None,
               edge_alpha=1.,
               edge_zorder=None,
               ax=None,
               draw_arrows=True,
               **kwargs):
    """

    Draw the edges of the network.

    Arguments
    ----------
    adjacency: m-long iterable of 2-tuples or 3-tuples or equivalent (such as (m, 2) or (m, 3) ndarray)
        Adjacency of the network in sparse matrix format.
        Each tuple corresponds to an edge defined by (source, target) or (source, target, weight).

    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    node_size : scalar or (n,) or dict key -> float (default 3.)
        Size (radius) of nodes in percent of axes space.
        Used to offset edges when drawing arrow heads,
        such that the arrow heads are not occluded.
        If draw_nodes() and draw_edges() are called independently,
        make sure to set this variable to the same value.

    edge_width : float or dictionary mapping (source, key) -> width (default 1.)
        Line width of edges.

    edge_color : color string, or (n, n) ndarray or (n, n, 4) ndarray (default: 'k')
        Edge color. Can be a single color format string, or
        a numeric array with the first two dimensions matching the adjacency matrix.
        If a single float is specified for each edge, the values will be mapped to
        colors using the edge_cmap and edge_vmin,edge_vmax parameters.
        If a (n, n, 4) ndarray is passed in, the last dimension is
        interpreted as an RGBA tuple, that requires no further parsing.

    edge_cmap : Matplotlib colormap or None (default None)
        Colormap for mapping intensities of edges.
        Ignored if edge_color is a string or a (n, n, 4) ndarray.

    edge_vmin, edge_vmax : float, float (default None, None)
        Minimum and maximum for edge colormap scaling.
        Ignored if edge_color is a string or a (n, n, 4) ndarray.

    edge_alpha : float (default 1.)
        The edge transparency,
        Ignored if edge_color is a (n, n, 4) ndarray.

    edge_zorder: int or dictionary mapping (source, target) -> int (default None)
        Order in which to plot the edges.
        Graphs typically appear more visually pleasing if darker coloured edges
        are plotted on top of lighter coloured edges.

    ax : matplotlib.axis instance or None (default None)
        Draw the graph in the specified Matplotlib axis.

    draw_arrows : bool, optional (default True)
        If True, draws edges with arrow heads.

    Returns
    -------
    artists: dict
        Dictionary mapping edges to matplotlib.patches.FancyArrow artists.
        The dictionary keys are of the format: (source index, target index).

    """

    if ax is None:
        ax = plt.gca()

    nodes = node_positions.keys()
    number_of_nodes = len(nodes)

    if isinstance(edge_width, (int, float)):
        edge_width = {(edge[0], edge[1]): edge_width for edge in adjacency}
    if isinstance(node_size, (int, float)):
        node_size = {node:node_size for node in nodes}

    # rescale
    node_size  = {node: size  * BASE_NODE_SIZE  for (node, size)  in node_size.items()}
    edge_width = {edge: width * BASE_EDGE_WIDTH for (edge, width) in edge_width.items()}

    if isinstance(edge_color, np.ndarray):
        if (edge_color.ndim == 3) and (edge_color.shape[-1] == 4): # i.e. full RGBA specification
            pass
        else: # array of floats that need to parsed
            edge_color = _parse_color_input(len(adjacency),
                                            edge_color.ravel(),
                                            cmap=edge_cmap,
                                            vmin=edge_vmin,
                                            vmax=edge_vmax,
                                            alpha=edge_alpha)
            edge_color = edge_color.reshape([number_of_nodes, number_of_nodes, 4])
    else: # single float or string
        edge_color = _parse_color_input(len(adjacency),
                                        edge_color,
                                        cmap=edge_cmap,
                                        vmin=edge_vmin,
                                        vmax=edge_vmax,
                                        alpha=edge_alpha)
        edge_color = edge_color.reshape([number_of_nodes, number_of_nodes, 4])

    # sources, targets = np.where(~np.isnan(adjacency_matrix))
    # # Force into a list, since zip became a generator in python 3, and thus can't be indexed below
    # edge_list = list(zip(sources.tolist(), targets.tolist()))

    # order edges if necessary
    if not (edge_zorder is None):
        adjacency = sorted(edge_zorder, key=lambda k: edge_zorder[k])

    # TODO:
    # Actually make use of zorder argument.
    # At the moment, only the relative zorder is honoured, not the absolute value.

    artists = dict()
    for edge in adjacency:

        source = edge[0]
        target = edge[1]

        x1, y1 = node_positions[source]
        x2, y2 = node_positions[target]

        dx = x2-x1
        dy = y2-y1

        w = edge_width[(source, target)]
        color = edge_color[source, target]

        bidirectional = (target, source) in adjacency

        if draw_arrows and bidirectional:
            # shift edge to the right (looking along the arrow)
            x1, y1, x2, y2 = _shift_edge(x1, y1, x2, y2, delta=0.5*w)
            # plot half arrow
            patch = _arrow(ax,
                           x1, y1, dx, dy,
                           offset=node_size[target],
                           facecolor=color,
                           width=w,
                           head_length=2*w,
                           head_width=3*w,
                           length_includes_head=True,
                           zorder=1,
                           edgecolor='none',
                           linewidth=0.1,
                           shape='right',
                           )

        elif draw_arrows and not bidirectional:
            # don't shift edge, plot full arrow
            patch = _arrow(ax,
                           x1, y1, dx, dy,
                           offset=node_size[target],
                           facecolor=color,
                           width=w,
                           head_length=2*w,
                           head_width=3*w,
                           length_includes_head=True,
                           edgecolor='none',
                           linewidth=0.1,
                           zorder=1,
                           shape='full',
                           )

        elif not draw_arrows and bidirectional:
            # shift edge to the right (looking along the line)
            x1, y1, x2, y2 = _shift_edge(x1, y1, x2, y2, delta=0.5*w)
            patch = _line(ax,
                          x1, y1, dx, dy,
                          facecolor=color,
                          width=w,
                          head_length=1e-10, # 0 throws error
                          head_width=1e-10, # 0 throws error
                          length_includes_head=False,
                          edgecolor='none',
                          linewidth=0.1,
                          zorder=1,
                          shape='right',
                          )
        else:
            patch = _line(ax,
                          x1, y1, dx, dy,
                          facecolor=color,
                          width=w,
                          head_length=1e-10, # 0 throws error
                          head_width=1e-10, # 0 throws error
                          length_includes_head=False,
                          edgecolor='none',
                          linewidth=0.1,
                          zorder=1,
                          shape='full',
                          )

        ax.add_artist(patch)
        artists[(source, target)] = patch

    return artists


def _shift_edge(x1, y1, x2, y2, delta):
    # get orthogonal unit vector
    v = np.r_[x2-x1, y2-y1] # original
    v = np.r_[-v[1], v[0]] # orthogonal
    v = v / np.linalg.norm(v) # unit

    dx, dy = delta * v
    return x1+dx, y1+dy, x2+dx, y2+dy


def _arrow(ax, x1, y1, dx, dy, offset, **kwargs):
    # offset to prevent occlusion of head from nodes
    r = np.sqrt(dx**2 + dy**2)
    dx *= (r-offset)/r
    dy *= (r-offset)/r

    return _line(ax, x1, y1, dx, dy, **kwargs)


def _line(ax, x1, y1, dx, dy, **kwargs):
    # use FancyArrow instead of e.g. LineCollection to ensure consistent scaling across elements;
    # return matplotlib.patches.FancyArrow(x1, y1, dx, dy, **kwargs)
    return FancyArrow(x1, y1, dx, dy, **kwargs)


# This is a copy of matplotlib.patches.FancyArrow.
# They messed up in matplotlib version 2.0.0.
# For shape="full" coords in 2.0.0 are
# coords = np.concatenate([left_half_arrow[:-1], right_half_arrow[-2::-1]])
# when they should be:
# coords = np.concatenate([left_half_arrow[:-1], right_half_arrow[-1::-1]])
# TODO: Remove copy when they fix it.
from matplotlib.patches import Polygon
class FancyArrow(Polygon):
    """
    Like Arrow, but lets you set head width and head height independently.
    """

    _edge_default = True

    def __str__(self):
        return "FancyArrow()"

    # @docstring.dedent_interpd
    def __init__(self, x, y, dx, dy, width=0.001, length_includes_head=False,
                 head_width=None, head_length=None, shape='full', overhang=0,
                 head_starts_at_zero=False, **kwargs):
        """
        Constructor arguments
          *width*: float (default: 0.001)
            width of full arrow tail

          *length_includes_head*: [True | False] (default: False)
            True if head is to be counted in calculating the length.

          *head_width*: float or None (default: 3*width)
            total width of the full arrow head

          *head_length*: float or None (default: 1.5 * head_width)
            length of arrow head

          *shape*: ['full', 'left', 'right'] (default: 'full')
            draw the left-half, right-half, or full arrow

          *overhang*: float (default: 0)
            fraction that the arrow is swept back (0 overhang means
            triangular shape). Can be negative or greater than one.

          *head_starts_at_zero*: [True | False] (default: False)
            if True, the head starts being drawn at coordinate 0
            instead of ending at coordinate 0.

        Other valid kwargs (inherited from :class:`Patch`) are:
        %(Patch)s

        """
        if head_width is None:
            head_width = 3 * width
        if head_length is None:
            head_length = 1.5 * head_width

        distance = np.hypot(dx, dy)

        if length_includes_head:
            length = distance
        else:
            length = distance + head_length
        if not length:
            verts = []  # display nothing if empty
        else:
            # start by drawing horizontal arrow, point at (0,0)
            hw, hl, hs, lw = head_width, head_length, overhang, width
            left_half_arrow = np.array([
                [0.0, 0.0],                  # tip
                [-hl, -hw / 2.0],             # leftmost
                [-hl * (1 - hs), -lw / 2.0],  # meets stem
                [-length, -lw / 2.0],          # bottom left
                [-length, 0],
            ])
            # if we're not including the head, shift up by head length
            if not length_includes_head:
                left_half_arrow += [head_length, 0]
            # if the head starts at 0, shift up by another head length
            if head_starts_at_zero:
                left_half_arrow += [head_length / 2.0, 0]
            # figure out the shape, and complete accordingly
            if shape == 'left':
                coords = left_half_arrow
            else:
                right_half_arrow = left_half_arrow * [1, -1]
                if shape == 'right':
                    coords = right_half_arrow
                elif shape == 'full':
                    # The half-arrows contain the midpoint of the stem,
                    # which we can omit from the full arrow. Including it
                    # twice caused a problem with xpdf.
                    coords = np.concatenate([left_half_arrow[:-1],
                                             right_half_arrow[-1::-1]])
                else:
                    raise ValueError("Got unknown shape: %s" % shape)
            if distance != 0:
                cx = float(dx) / distance
                sx = float(dy) / distance
            else:
                #Account for division by zero
                cx, sx = 0, 1
            M = np.array([[cx, sx], [-sx, cx]])
            verts = np.dot(coords, M) + (x + dx, y + dy)

        Polygon.__init__(self, list(map(tuple, verts)), closed=True, **kwargs)


def draw_node_labels(node_labels,
                     node_positions,
                     font_size=8,
                     font_color='k',
                     font_family='sans-serif',
                     font_weight='normal',
                     font_alpha=1.,
                     bbox=None,
                     clip_on=False,
                     ax=None,
                     **kwargs):
    """
    Draw node labels.

    Arguments
    ---------
    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    node_labels : dict key -> str
       Dictionary mapping nodes to labels.
       Only nodes in the dictionary are labelled.

    font_size : int (default 12)
       Font size for text labels

    font_color : string (default 'k')
       Font color string

    font_family : string (default='sans-serif')
       Font family

    font_weight : string (default='normal')
       Font weight

    font_alpha : float (default 1.)
       Text transparency

    bbox : Matplotlib bbox
       Specify text box shape and colors.

    clip_on : bool
       Turn on clipping at axis boundaries (default=False)

    ax : matplotlib.axis instance or None (default None)
       Draw the graph in the specified Matplotlib axis.

    Returns
    -------
    artists: dict
        Dictionary mapping node indices to text objects.

    @reference
    Borrowed with minor modifications from networkx/drawing/nx_pylab.py

    """

    if ax is None:
        ax = plt.gca()

    # set optional alignment
    horizontalalignment = kwargs.get('horizontalalignment', 'center')
    verticalalignment = kwargs.get('verticalalignment', 'center')

    artists = dict()  # there is no text collection so we'll fake one
    for ii, label in node_labels.items():
        x, y = node_positions[ii]
        text_object = ax.text(x, y,
                              label,
                              size=font_size,
                              color=font_color,
                              alpha=font_alpha,
                              family=font_family,
                              weight=font_weight,
                              horizontalalignment=horizontalalignment,
                              verticalalignment=verticalalignment,
                              transform=ax.transData,
                              bbox=bbox,
                              clip_on=False)
        artists[ii] = text_object

    return artists


def draw_edge_labels(edge_labels,
                     node_positions,
                     font_size=10,
                     font_color='k',
                     font_family='sans-serif',
                     font_weight='normal',
                     font_alpha=1.,
                     bbox=None,
                     clip_on=False,
                     ax=None,
                     rotate=True,
                     edge_label_zorder=10000,
                     **kwargs):
    """
    Draw edge labels.

    Arguments
    ---------

    node_positions : dict mapping key -> (float, float)
        Mapping of nodes to (x,y) positions

    edge_labels : dictionary
        Dictionary mapping edge specified by (source index, target index) to label.
        Only edges in the dictionary are labelled.

    font_size : int (default 12)
       Font size for text labels

    font_color : string (default 'k')
       Font color string

    font_family : string (default='sans-serif')
       Font family

    font_weight : string (default='normal')
       Font weight

    font_alpha : float (default 1.)
       Text transparency

    bbox : Matplotlib bbox
       Specify text box shape and colors.

    clip_on : bool
       Turn on clipping at axis boundaries (default=True)

    edge_label_zorder : int
        Set the zorder of edge labels.
        Choose a large number to ensure that the labels are plotted on top of the edges.

    ax : matplotlib.axis instance or None (default None)
       Draw the graph in the specified Matplotlib axis.

    Returns
    -------
    artists: dict
        Dictionary mapping (source index, target index) to text objects.

    @reference
    Borrowed with minor modifications from networkx/drawing/nx_pylab.py

    """

    # draw labels centered on the midway point of the edge
    label_pos = 0.5

    if ax is None:
        ax = plt.gca()

    text_items = {}
    for (n1, n2), label in edge_labels.items():
        (x1, y1) = node_positions[n1]
        (x2, y2) = node_positions[n2]
        (x, y) = (x1 * label_pos + x2 * (1.0 - label_pos),
                  y1 * label_pos + y2 * (1.0 - label_pos))

        if rotate:
            angle = np.arctan2(y2-y1, x2-x1)/(2.0*np.pi)*360  # degrees
            # make label orientation "right-side-up"
            if angle > 90:
                angle -= 180
            if angle < - 90:
                angle += 180
            # transform data coordinate angle to screen coordinate angle
            xy = np.array((x, y))
            trans_angle = ax.transData.transform_angles(np.array((angle,)),
                                                        xy.reshape((1, 2)))[0]
        else:
            trans_angle = 0.0

        if bbox is None: # use default box of white with white border
            bbox = dict(boxstyle='round',
                        ec=(1.0, 1.0, 1.0),
                        fc=(1.0, 1.0, 1.0),
                        )

        # set optional alignment
        horizontalalignment = kwargs.get('horizontalalignment', 'center')
        verticalalignment = kwargs.get('verticalalignment', 'center')

        t = ax.text(x, y,
                    label,
                    size=font_size,
                    color=font_color,
                    family=font_family,
                    weight=font_weight,
                    horizontalalignment=horizontalalignment,
                    verticalalignment=verticalalignment,
                    rotation=trans_angle,
                    transform=ax.transData,
                    bbox=bbox,
                    zorder=edge_label_zorder,
                    clip_on=True,
                    )

        text_items[(n1, n2)] = t

    return text_items


def _parse_color_input(number_of_elements, color_spec,
                       cmap=None, vmin=None, vmax=None, alpha=1.):
    """
    Handle the mess that is matplotlib color specifications.
    Return an RGBA array with specified number of elements.

    Arguments
    ---------
    number_of_elements: int
        Number (n) of elements to get a color for.

    color_spec : color string, list of strings, a float, or a ndarray of floats
        Any valid matplotlib color specification.
        If numeric values are specified, they will be mapped to colors using the
        cmap and vmin/vmax arguments.

    cmap : matplotlib colormap (default None)
        Color map to use if color_spec is not a string.

    vmin, vmax : float, float (default None, None)
        Minimum and maximum values for normalizing colors if a color mapping is used.

    alpha : float or n-long iterable of floats (default 1.)
        Alpha values to go with the colors.

    Returns
    -------
    rgba_array : (n, 4) numpy ndarray
        Array of RGBA color specifications.

    """

    # map color_spec to either a list of strings or
    # an iterable of floats of the correct length,
    # unless, of course, they already are either of these
    if isinstance(color_spec, (float, int)):
        color_spec = color_spec * np.ones((number_of_elements), dtype=np.float)
    if isinstance(color_spec, str):
        color_spec = number_of_elements * [color_spec]

    # map numeric types using cmap, vmin, vmax
    if isinstance(color_spec[0], (float, int)):
        mapper = cm.ScalarMappable(cmap=cmap)
        mapper.set_clim(vmin, vmax)
        rgba_array = mapper.to_rgba(color_spec)
    # convert string specification to colors
    else:
        rgba_array = np.array([colorConverter.to_rgba(c) for c in color_spec])

    # Set the final column of the rgba_array to have the relevant alpha values.
    rgba_array[:,-1] = alpha

    return rgba_array


def _update_view(node_positions, node_size, ax):
    """
    Pad x and y limits as patches are not registered properly
    when matplotlib sets axis limits automatically.
    """
    maxs = np.max(node_size) * BASE_NODE_SIZE
    maxx, maxy = np.max(node_positions.values(), axis=0)
    minx, miny = np.min(node_positions.values(), axis=0)

    w = maxx-minx
    h = maxy-miny
    padx, pady = 0.05*w + maxs, 0.05*h + maxs
    corners = (minx-padx, miny-pady), (maxx+padx, maxy+pady)

    ax.update_datalim(corners)
    ax.autoscale_view()
    ax.get_figure().canvas.draw()
    return


def _make_pretty(ax):
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect('equal')
    ax.get_figure().set_facecolor('w')
    ax.set_frame_on(False)
    ax.get_figure().canvas.draw()
    return


def _adjacency_matrix_to_edge_list(adjacency_matrix):
    sources, targets = np.where(~np.isnan(adjacency_matrix))
    edge_list = list(zip(sources.tolist(), targets.tolist()))
    adjacency = [(source, target, adjacency_matrix[source, target]) for (source, target) in edge_list]
    return adjacency


def _edge_list_to_adjacency_matrix(adjacency, total_nodes=None):
    edges = [(edge[0], edge[1]) for edge in adjacency]

    if total_nodes is None:
        nodes = np.unique(edges)
        total_nodes = int(np.max(nodes) +1)

    adjacency_matrix = np.full((total_nodes, total_nodes), np.nan)

    if _is_weighted(adjacency):
        for (source, target, weight) in adjacency:
            adjacency_matrix[int(source), int(target)] = weight
    else:
        for source, target in adjacency:
            adjacency_matrix[int(source), int(target)] = 1.

    return adjacency_matrix


# --------------------------------------------------------------------------------

def test(n=20, p=0.15, ax=None, directed=True, **kwargs):
    w = _get_random_weight_matrix(n, p, directed=directed, **kwargs)
    node_labels = {node: str(node) for node in range(n)}
    adjacency = _adjacency_matrix_to_edge_list(w)
    edge_labels = {(edge[0], edge[1]): str(ii) for ii, edge in enumerate(adjacency)}
    ax = draw(adjacency, node_labels=node_labels, edge_labels=edge_labels, ax=ax)
    plt.show()
    return ax


def _get_random_weight_matrix(n, p,
                              weighted=True,
                              strictly_positive=False,
                              directed=True,
                              fully_bidirectional=False,
                              dales_law=False):

    if weighted:
        w = np.random.randn(n, n)
    else:
        w = np.ones((n, n))

    if strictly_positive:
        w = np.abs(w)

    if not directed:
        w = np.triu(w)
        w[np.tril_indices(n)] = np.nan

    if directed and fully_bidirectional:
        c = np.random.rand(n, n) <= p/2
        c = np.logical_or(c, c.T)
    else:
        c = np.random.rand(n, n) <= p
    w[~c] = np.nan

    if dales_law and weighted and not strictly_positive:
        w = np.abs(w) * np.sign(np.random.randn(n))[:,None]

    return w

if __name__ == "__main__":
    test()
