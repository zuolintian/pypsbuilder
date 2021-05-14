"""pypsbuilder classes used by builders.

This module contains classes and tools providing API to THERMOCALC, parsing of
outputs and storage of calculated invariant points and univariant lines.

Todo:
    * Implement own class for divariant fields

"""
# author: Ondrej Lexa
# website: petrol.natur.cuni.cz/~ondro



import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, linemerge   # unary_union
from .tcapi import TCResult, TCResultSet

polymorphs = [{'sill', 'and'}, {'ky', 'and'}, {'sill', 'ky'}, {'q', 'coe'}, {'diam', 'gph'}]
"""list: List of two-element sets containing polymorphs."""


class PseudoBase:
    """Base class with common methods for InvPoint and UniLine.

    """
    def label(self, excess={}):
        """str: full label with space delimeted phases - zero mode phase."""
        phases_lbl = ' '.join(sorted(list(self.phases.difference(excess))))
        out_lbl = ' '.join(sorted(list(self.out)))
        return '{} - {}'.format(phases_lbl, out_lbl)

    def annotation(self, show_out=False):
        """str: String representation of ID with possible zermo mode phase."""
        if show_out:
            return '{:d} {}'.format(self.id, ' '.join(self.out))
        else:
            return '{:d}'.format(self.id)

    def ptguess(self, **kwargs):
        """list: Get stored ptguesses.

        InvPoint has just single ptguess, but for UniLine idx need to be
        specified. If omitted, the middle point from calculated ones is used.

        Args:
            idx (int): index which guesses to get.
        """
        idx = kwargs.get('idx', self.midix)
        return self.results[idx].ptguess

    def datakeys(self, phase=None):
        """list: Get list of variables for phase.

        Args:
            phase (str): name of phase
        """
        if phase is None:
            return list(self.results[self.midix].data.keys())
        else:
            return list(self.results[self.midix].data[phase].keys())


class InvPoint(PseudoBase):
    """Class to store invariant point

    Attributes:
        id (int): Invariant point identification
        phases (set): set of present phases
        out (set): set of zero mode phases
        cmd (str): THERMOCALC standard input to calculate this point
        variance (int): variance
        x (numpy.array): Array of x coordinates
            (even if only one, it is stored as array)
        y (numpy.array): Array of x coordinates
            (even if only one, it is stored as array)
        results (list): List of results dicts with data and ptgues keys.
        output (str): Full THERMOCALC output
        manual (bool): True when inavariant point is user-defined and not
            calculated
    """
    def __init__(self, **kwargs):
        assert 'phases' in kwargs, 'Set of phases must be provided'
        assert 'out' in kwargs, 'Set of zero phase must be provided'
        self.id = kwargs.get('id', 0)
        self.phases = kwargs.get('phases')
        self.out = kwargs.get('out')
        self.cmd = kwargs.get('cmd', '')
        self.variance = kwargs.get('variance', 0)
        self.x = kwargs.get('x', [])
        self.y = kwargs.get('y', [])
        self.results = kwargs.get('results', None)
        self.output = kwargs.get('output', 'User-defined')
        self.manual = kwargs.get('manual', False)

    def __repr__(self):
        return 'Inv: {}'.format(self.label())

    @property
    def midix(self):
        return 0

    @property
    def _x(self):
        """X coordinate as float"""
        return self.x[0]

    @property
    def _y(self):
        """Y coordinate as float"""
        return self.y[0]

    def shape(self):
        """Return shapely Point representing invariant point."""
        return Point(self._x, self._y)

    def all_unilines(self):
        """Return four tuples (phases, out) indicating possible four
        univariant lines passing trough this invariant point"""
        a, b = self.out
        aset, bset = set([a]), set([b])
        aphases, bphases = self.phases.difference(aset), self.phases.difference(bset)
        # Check for polymorphs
        fix = False
        for poly in polymorphs:
            if poly.issubset(self.phases):
                fix = True
                break
        if fix and (poly != self.out):   # on boundary
            yespoly = poly.intersection(self.out)
            nopoly = self.out.difference(yespoly)
            aphases = self.phases.difference(yespoly)
            bphases = self.phases.difference(poly.difference(self.out))
            return((aphases, nopoly),
                   (bphases, nopoly),
                   (self.phases, yespoly),
                   (self.phases.difference(nopoly), yespoly))
        else:
            return((self.phases, aset),
                   (self.phases, bset),
                   (bphases, aset),
                   (aphases, bset))


class UniLine(PseudoBase):
    """Class to store univariant line

    Attributes:
        id (int): Invariant point identification
        phases (set): set of present phases
        out (set): set of zero mode phase
        cmd (str): THERMOCALC standard input to calculate this point
        variance (int): variance
        _x (numpy.array): Array of x coordinates (all calculated)
        _y (numpy.array): Array of x coordinates (all calculated)
        results (list): List of results dicts with data and ptgues keys.
        output (str): Full THERMOCALC output
        manual (bool): True when inavariant point is user-defined and not
            calculated
        begin (int): id of invariant point defining begining of the line.
            0 for no begin
        end (int): id of invariant point defining end of the line.
            0 for no end
        used (slice): slice indicating which point on calculated line are
            between begin and end
    """
    def __init__(self, **kwargs):
        assert 'phases' in kwargs, 'Set of phases must be provided'
        assert 'out' in kwargs, 'Set of zero phase must be provided'
        self.id = kwargs.get('id', 0)
        self.phases = kwargs.get('phases')
        self.out = kwargs.get('out')
        self.cmd = kwargs.get('cmd', '')
        self.variance = kwargs.get('variance', 0)
        self._x = kwargs.get('x', np.array([]))
        self._y = kwargs.get('y', np.array([]))
        self.results = kwargs.get('results', None)
        self.output = kwargs.get('output', 'User-defined')
        self.manual = kwargs.get('manual', False)
        self.begin = kwargs.get('begin', 0)
        self.end = kwargs.get('end', 0)
        self.used = slice(0, len(self._x))
        self.x = self._x.copy()
        self.y = self._y.copy()

    def __repr__(self):
        return 'Uni: {}'.format(self.label())

    @property
    def midix(self):
        return int((self.used.start + self.used.stop) // 2)

    @property
    def connected(self):
        return 2 - [self.begin, self.end].count(0)

    def _shape(self, ratio=None, tolerance=None):
        """Return shapely LineString representing univariant line.

        This method is using all calculated points.

        Args:
            ratio: y-coordinate multiplier to scale coordinates. Default None
            tolerance: tolerance x coordinates. Simplified object will be within
            the tolerance distance of the original geometry. Default None
        """
        if ratio is None:
            return LineString(np.array([self._x, self._y]).T)
        else:
            if tolerance is None:
                return LineString(np.array([self._x, self._y]).T)
            else:
                ln = LineString(np.array([self._x, ratio * self._y]).T).simplify(tolerance)
                x, y = np.array(ln.coords).T
                return LineString(np.array([x, y / ratio]).T)

    def shape(self, ratio=None, tolerance=None):
        """Return shapely LineString representing univariant line.

        This method is using trimmed points.

        Args:
            ratio: y-coordinate multiplier to scale coordinates. Default None
            tolerance: tolerance x coordinates. Simplified object will be within
            the tolerance distance of the original geometry. Default None
        """
        if ratio is None:
            return LineString(np.array([self.x, self.y]).T)
        else:
            if tolerance is None:
                return LineString(np.array([self.x, self.y]).T)
            else:
                ln = LineString(np.array([self.x, ratio * self.y]).T).simplify(tolerance)
                x, y = np.array(ln.coords).T
                return LineString(np.array([x, y / ratio]).T)

    def contains_inv(self, ip):
        """Check whether invariant point theoretically belong to univariant line.

        Args:
            ip (InvPoint): Invariant point

        Returns:
            bool: True for yes, False for no. Note that metastability is not checked.
        """
        def checkme(uphases, uout, iphases, iout):
            a, b = iout
            aset, bset = set([a]), set([b])
            aphases, bphases = iphases.difference(aset), iphases.difference(bset)
            candidate = False
            if iphases == uphases and len(iout.difference(uout)) == 1:
                candidate = True
            if bphases == uphases and aset == uout:
                candidate = True
            if aphases == uphases and bset == uout:
                candidate = True
            return candidate
        # Check for polymorphs
        fixi, fixu = False, False
        for poly in polymorphs:
            if poly.issubset(ip.phases) and (poly != ip.out) and (not ip.out.isdisjoint(poly)):
                fixi = True
                if poly.issubset(self.phases) and not self.out.isdisjoint(poly):
                    fixu = True
                break
        # check invs
        candidate = checkme(self.phases, self.out, ip.phases, ip.out)
        if fixi and not candidate:
            candidate = checkme(self.phases, self.out, ip.phases, ip.out.difference(poly).union(poly.difference(ip.out)))
        if fixu and not candidate:
            candidate = checkme(self.phases, poly.difference(self.out), ip.phases, ip.out)
        return candidate

    def get_label_point(self):
        """Returns coordinate tuple of labeling point for univariant line."""
        if len(self.x) > 1:
            dx = np.diff(self.x)
            dy = np.diff(self.y)
            d = np.sqrt(dx**2 + dy**2)
            sd = np.sum(d)
            if sd > 0:
                cl = np.append([0], np.cumsum(d))
                ix = np.interp(sd / 2, cl, range(len(cl)))
                cix = int(ix)
                return self.x[cix] + (ix - cix) * dx[cix], self.y[cix] + (ix - cix) * dy[cix]
            else:
                return self.x[0], self.y[0]
        else:
            return self.x[0], self.y[0]


class SectionBase:
    """Base class for PTsection, TXsection and PX section

    """
    def __init__(self, **kwargs):
        self.excess = kwargs.get('excess', set())
        self.invpoints = {}
        self.unilines = {}
        self.dogmins = {}

    def __repr__(self):
        return '\n'.join(['{}'.format(type(self).__name__),
                          'Univariant lines: {}'.format(len(self.unilines)),
                          'Invariant points: {}'.format(len(self.invpoints)),
                          '{} range: {} {}'.format(self.x_var, *self.xrange),
                          '{} range: {} {}'.format(self.y_var, *self.yrange)])

    @property
    def ratio(self):
        return (self.xrange[1] - self.xrange[0]) / (self.yrange[1] - self.yrange[0])

    @property
    def range_shapes(self):
        # default p-t range boundary
        bnd = [LineString([(self.xrange[0], self.yrange[0]),
                          (self.xrange[1], self.yrange[0])]),
               LineString([(self.xrange[1], self.yrange[0]),
                          (self.xrange[1], self.yrange[1])]),
               LineString([(self.xrange[1], self.yrange[1]),
                          (self.xrange[0], self.yrange[1])]),
               LineString([(self.xrange[0], self.yrange[1]),
                          (self.xrange[0], self.yrange[0])])]
        return bnd, next(polygonize(bnd))

    def add_inv(self, id, inv):
        if inv.manual:
            inv.results = None
        else:  # temporary compatibility with 2.2.0
            if not isinstance(inv.results, TCResultSet):
                inv.results = TCResultSet([TCResult(float(x), float(y), variance=inv.variance,
                                                    data=r['data'], ptguess=r['ptguess'])
                                           for r, x, y in zip(inv.results, inv.x, inv.y)])
        self.invpoints[id] = inv
        self.invpoints[id].id = id

    def add_uni(self, id, uni):
        if uni.manual:
            uni.results = None
        else:  # temporary compatibility with 2.2.0
            if not isinstance(uni.results, TCResultSet):
                uni.results = TCResultSet([TCResult(float(x), float(y), variance=uni.variance,
                                                    data=r['data'], ptguess=r['ptguess'])
                                           for r, x, y in zip(uni.results, uni._x, uni._y)])
        self.unilines[id] = uni
        self.unilines[id].id = id

    def add_dogmin(self, id, dgm):
        self.dogmins[id] = dgm
        self.dogmins[id].id = id

    def cleanup_data(self):
        for id_uni, uni in self.unilines.items():
            if not uni.manual:
                keep = slice(max(uni.used.start - 1, 0), min(uni.used.stop + 1, len(uni._x)))
                uni._x = uni._x[keep]
                uni._y = uni._y[keep]
                uni.results = uni.results[keep]
            else:
                uni.cmd = ''
                uni.variance = 0
                uni._x = np.array([])
                uni._y = np.array([])
                uni.results = [dict(data=None, ptguess=None)]
                uni.output = 'User-defined'
                uni.used = slice(0, 0)
                uni.x = np.array([])
                uni.y = np.array([])
            self.trim_uni(id_uni)

    def getidinv(self, inv=None):
        '''Return id of either new or existing invariant point'''
        ids = 0
        # collect polymorphs identities
        if inv is not None:
            outs = [inv.out]
            for poly in polymorphs:
                if poly.issubset(inv.phases):
                    switched = inv.out.difference(poly).union(poly.difference(inv.out))
                    if switched:
                        outs.append(switched)

        for iid, cinv in self.invpoints.items():
            if inv is not None:
                if cinv.phases == inv.phases:
                    if cinv.out in outs:
                        inv.out = cinv.out  # switch to already used ??? Needed ???
                        return False, iid
            ids = max(ids, iid)
        return True, ids + 1

    def getiduni(self, uni=None):
        '''Return id of either new or existing univariant line'''
        ids = 0
        # collect polymorphs identities
        if uni is not None:
            outs = [uni.out]
            for poly in polymorphs:
                if poly.issubset(uni.phases):
                    outs.append(poly.difference(uni.out))

        for uid, cuni in self.unilines.items():
            if uni is not None:
                if cuni.phases == uni.phases:
                    if cuni.out in outs:
                        uni.out = cuni.out  # switch to already used ??? Needed ???
                        return False, uid
            ids = max(ids, uid)
        return True, ids + 1

    def trim_uni(self, id):
        uni = self.unilines[id]
        if not uni.manual:
            if uni.begin > 0:
                p1 = Point(self.invpoints[uni.begin].x,
                           self.ratio * self.invpoints[uni.begin].y)
            else:
                p1 = Point(uni._x[0], self.ratio * uni._y[0])
            if uni.end > 0:
                p2 = Point(self.invpoints[uni.end].x,
                           self.ratio * self.invpoints[uni.end].y)
            else:
                p2 = Point(uni._x[-1], self.ratio * uni._y[-1])
            #
            xy = np.array([uni._x, self.ratio * uni._y]).T
            line = LineString(xy)
            # vertex distances
            vdst = np.array([line.project(Point(*v)) for v in xy])
            d1 = line.project(p1)
            d2 = line.project(p2)
            # switch if needed
            if d1 > d2:
                d1, d2 = d2, d1
                uni.begin, uni.end = uni.end, uni.begin
            # get slice of points to keep
            uni.used = slice(np.flatnonzero(vdst >= d1)[0].item(),
                             np.flatnonzero(vdst <= d2)[-1].item() + 1)

        # concatenate begin, keep, end
        if uni.begin > 0:
            x1, y1 = self.invpoints[uni.begin].x, self.invpoints[uni.begin].y
        else:
            x1, y1 = [], []
        if uni.end > 0:
            x2, y2 = self.invpoints[uni.end].x, self.invpoints[uni.end].y
        else:
            x2, y2 = [], []
        if not uni.manual:
            xx = uni._x[uni.used]
            yy = uni._y[uni.used]
        else:
            xx, yy = [], []

        # store trimmed
        uni.x = np.hstack((x1, xx, x2))
        uni.y = np.hstack((y1, yy, y2))

    def create_shapes(self, tolerance=None):
        def splitme(seg):
            '''Recursive boundary splitter'''
            s_seg = []
            for _, l in lns:
                if seg.intersects(l):
                    m = linemerge([seg, l])
                    if m.type == 'MultiLineString':
                        p = seg.intersection(l)
                        p_ok = l.interpolate(l.project(p))  # fit intersection to line
                        t_seg = LineString([Point(seg.coords[0]), p_ok])
                        if t_seg.is_valid:
                            s_seg.append(t_seg)
                        t_seg = LineString([p_ok, Point(seg.coords[-1])])
                        if t_seg.is_valid:
                            s_seg.append(t_seg)
                        break
            if len(s_seg) == 2:
                return splitme(s_seg[0]) + splitme(s_seg[1])
            else:
                return [seg]
        # define bounds and area
        bnd, area = self.range_shapes
        lns = []
        log = []
        # trim univariant lines
        for uni in self.unilines.values():
            ln = area.intersection(uni.shape(ratio=self.ratio, tolerance=tolerance))
            if ln.type == 'LineString' and not ln.is_empty:
                lns.append((uni.id, ln))
            if ln.type == 'MultiLineString':
                for ln_part in ln:
                    if ln_part.type == 'LineString' and not ln_part.is_empty:
                        lns.append((uni.id, ln_part))
        # split boundaries
        edges = splitme(bnd[0]) + splitme(bnd[1]) + splitme(bnd[2]) + splitme(bnd[3])
        # polygonize
        polys = list(polygonize(edges + [l for _, l in lns]))
        # create shapes
        shapes = {}
        unilists = {}
        for ix, poly in enumerate(polys):
            unilist = []
            for uni_id, ln in lns:
                if ln.relate_pattern(poly, '*1*F*****'):
                    unilist.append(uni_id)
            phases = set.intersection(*(self.unilines[id].phases for id in unilist))
            vd = [phases.symmetric_difference(self.unilines[id].phases) == self.unilines[id].out or not phases.symmetric_difference(self.unilines[id].phases) or phases.symmetric_difference(self.unilines[id].phases).union(self.unilines[id].out) in polymorphs for id in unilist]
            if all(vd):
                if frozenset(phases) in shapes:
                    # multivariant field crossed just by single univariant line
                    if len(unilist) == 1:
                        if self.unilines[unilist[0]].out.issubset(phases):
                            phases = phases.difference(self.unilines[unilist[0]].out)
                            shapes[frozenset(phases)] = poly
                            unilists[frozenset(phases)] = unilist
                    elif len(unilists[frozenset(phases)]) == 1:
                        if self.unilines[unilists[frozenset(phases)][0]].out.issubset(phases):
                            orig_unilist = unilists[frozenset(phases)]
                            shapes[frozenset(phases)] = poly
                            unilists[frozenset(phases)] = unilist
                            phases = phases.difference(self.unilines[orig_unilist[0]].out)
                            shapes[frozenset(phases)] = poly
                            unilists[frozenset(phases)] = orig_unilist
                    else:
                        shapes[frozenset(phases)] = shapes[frozenset(phases)].union(poly).buffer(0.00001)
                        log.append('Area defined by unilines {} is self-intersecting with {}.'.format(' '.join([str(id) for id in unilist]), ' '.join([str(id) for id in unilists[frozenset(phases)]])))
                        unilists[frozenset(phases)] = list(set(unilists[frozenset(phases)] + unilist))
                else:
                    shapes[frozenset(phases)] = poly
                    unilists[frozenset(phases)] = unilist
            else:
                log.append('Area defined by unilines {} is not valid field.'.format(' '.join([str(id) for id in unilist])))
        return shapes, unilists, log

    def show(self):
        for ln in self.unilines.values():
            plt.plot(ln.x, ln.y, 'k-')

        for ln in self.invpoints.values():
            plt.plot(ln.x, ln.y, 'ro')

        plt.xlim(self.xrange)
        plt.ylim(self.yrange)
        plt.xlabel(self.x_var_label)
        plt.xlabel(self.y_var_label)
        plt.show()

    @staticmethod
    def read_file(projfile):
        with gzip.open(str(projfile), 'rb') as stream:
            data = pickle.load(stream)
        return data

    @staticmethod
    def from_file(projfile):
        with gzip.open(str(projfile), 'rb') as stream:
            data = pickle.load(stream)
        return data['section']


class PTsection(SectionBase):
    """P-T pseudosection class

    """
    def __init__(self, **kwargs):
        self.xrange = kwargs.get('trange', (200., 1000.))
        self.yrange = kwargs.get('prange', (0.1, 20.))
        self.x_var = 'T'
        self.x_var_label = 'Temperature [C]'
        self.x_var_res = 0.01
        self.y_var = 'p'
        self.y_var_label = 'Pressure [kbar]'
        self.y_var_res = 0.001
        super(PTsection, self).__init__(**kwargs)


class TXsection(SectionBase):
    """T-X pseudosection class

    """
    def __init__(self, **kwargs):
        self.xrange = kwargs.get('trange', (200., 1000.))
        self.yrange = (0., 1.)
        self.x_var = 'T'
        self.x_var_label = 'Temperature [C]'
        self.x_var_res = 0.01
        self.y_var = 'C'
        self.y_var_label = 'Composition'
        self.y_var_res = 0.001
        super(TXsection, self).__init__(**kwargs)


class PXsection(SectionBase):
    """P-X pseudosection class

    """
    def __init__(self, **kwargs):
        self.xrange = (0., 1.)
        self.yrange = kwargs.get('prange', (0.1, 20.))
        self.x_var = 'C'
        self.x_var_label = 'Composition'
        self.x_var_res = 0.001
        self.y_var = 'p'
        self.y_var_label = 'Pressure [kbar]'
        self.y_var_res = 0.001
        super(PXsection, self).__init__(**kwargs)
