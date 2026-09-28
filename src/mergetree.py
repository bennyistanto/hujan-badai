"""Merge tree of the superlevel-set filtration of the 3D rain field.

Why this exists
---------------
The sweep (docs/sweep-prominence.md) showed that captured volume is essentially
h-invariant while the partition into storms is entirely h-dependent: an 8x change
in prominence moves captured volume 4% and the storm count 8.3x. So a catalogue at
one chosen h bakes an arbitrary scale into the product.

The merge tree is the honest object. It is computed once and carries every level
at once, so `cut(tree, h)` returns the segmentation at any prominence without
touching the data again, and the parent/child structure is the storm hierarchy:
which substorms belong to which system.

The algorithm
-------------
Sweep voxels in descending intensity, maintaining connected components of the
superlevel set with union-find:

- a voxel with no already-swept neighbour **births** a component: a local maximum
- a voxel adjacent to exactly one component joins it
- a voxel adjacent to two or more is a **saddle**: the components merge there. The
  one with the highest birth survives; each other one dies at this intensity and
  records the survivor as its parent.

A component's **persistence** is `birth - death`, the intensity prominence of its
peak above the saddle that joins it to something stronger. This is exactly the h
of `segment.label_watershed`, but now available at every level simultaneously.

Only voxels at or above `wet_threshold` participate, so the filtration is truncated
there and a root component's death is `wet_threshold`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit

# 26-neighbour system in space and time, matching segment.STRUCT_26.
_OFF = np.array([(dt, dy, dx)
                 for dt in (-1, 0, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                 if not (dt == 0 and dy == 0 and dx == 0)], dtype=np.int64)


@dataclass
class MergeTree:
    """Components of the filtration, indexed 0..n-1.

    birth       intensity of the component's peak (mm/hr)
    death       intensity of the saddle where it merged, or wet_threshold if a root
    parent      component it merged into, -1 for a root
    peak_flat   flat index of its maximum voxel
    persistence birth - death
    comp        per-voxel component id, -1 for dry. Shape of the input cube.
    """
    birth: np.ndarray
    death: np.ndarray
    parent: np.ndarray
    peak_flat: np.ndarray
    comp: np.ndarray
    wet_threshold: float
    shape: tuple

    @property
    def persistence(self) -> np.ndarray:
        return self.birth - self.death

    def __len__(self) -> int:
        return int(self.birth.size)

    def summary(self) -> str:
        p = self.persistence
        return (f"MergeTree: {len(self)} components, "
                f"{int((self.parent < 0).sum())} root(s), "
                f"persistence max {p.max():.1f}, median {np.median(p):.2f} mm/hr")


@njit(cache=True)
def _build(R, order, shape, off, wet_threshold):
    nt, ny, nx = shape
    n_vox = R.size
    comp = np.full(n_vox, -1, np.int32)

    cap = order.size // 4 + 16
    birth = np.empty(cap, np.float32)
    death = np.full(cap, wet_threshold, np.float32)
    parent = np.full(cap, -1, np.int32)
    peak = np.empty(cap, np.int64)
    uf = np.empty(cap, np.int32)          # union-find over components
    n_comp = 0

    nbr = np.empty(26, np.int32)

    for k in range(order.size):
        v = order[k]
        val = R[v]
        t = v // (ny * nx)
        rem = v - t * ny * nx
        y = rem // nx
        x = rem - y * nx

        # Roots of already-swept neighbouring components.
        n_found = 0
        for o in range(off.shape[0]):
            tt = t + off[o, 0]
            yy = y + off[o, 1]
            xx = x + off[o, 2]
            if tt < 0 or tt >= nt or yy < 0 or yy >= ny or xx < 0 or xx >= nx:
                continue
            c = comp[(tt * ny + yy) * nx + xx]
            if c < 0:
                continue
            # find with path compression
            while uf[c] != c:
                uf[c] = uf[uf[c]]
                c = uf[c]
            dup = False
            for j in range(n_found):
                if nbr[j] == c:
                    dup = True
                    break
            if not dup:
                nbr[n_found] = c
                n_found += 1

        if n_found == 0:
            # Local maximum: a new component is born here.
            if n_comp >= cap:
                return comp, birth[:0], death[:0], parent[:0], peak[:0], -1
            birth[n_comp] = val
            peak[n_comp] = v
            uf[n_comp] = n_comp
            comp[v] = n_comp
            n_comp += 1
        else:
            # Survivor is the neighbour whose peak is highest.
            s = nbr[0]
            for j in range(1, n_found):
                if birth[nbr[j]] > birth[s]:
                    s = nbr[j]
            # Every other component dies at this saddle.
            for j in range(n_found):
                c = nbr[j]
                if c != s:
                    death[c] = val
                    parent[c] = s
                    uf[c] = s
            comp[v] = s

    return comp, birth[:n_comp], death[:n_comp], parent[:n_comp], peak[:n_comp], n_comp


def build_merge_tree(R: np.ndarray, wet_threshold: float = 1.0) -> MergeTree:
    """Build the merge tree of the superlevel sets of `R` above `wet_threshold`."""
    Rf = np.nan_to_num(np.asarray(R, dtype=np.float32), nan=0.0)
    flat = Rf.ravel()
    wet = np.flatnonzero(flat >= wet_threshold)
    if wet.size == 0:
        z = np.zeros(0, np.float32)
        return MergeTree(z, z, np.zeros(0, np.int32), np.zeros(0, np.int64),
                         np.full(Rf.shape, -1, np.int32), wet_threshold, Rf.shape)

    # Descending intensity. A stable sort keeps ties in a deterministic order, so
    # two runs on the same input give the same tree.
    order = wet[np.argsort(-flat[wet], kind="stable")].astype(np.int64)

    comp, birth, death, parent, peak, n = _build(
        flat, order, Rf.shape, _OFF, np.float32(wet_threshold))
    if n < 0:
        raise RuntimeError("merge tree component capacity exceeded")

    return MergeTree(birth, death, parent, peak,
                     comp.reshape(Rf.shape), float(wet_threshold), Rf.shape)


def _survivor_map(tree: MergeTree, persistence: float) -> np.ndarray:
    """For each component, the nearest ancestor with persistence >= h.

    A root always survives: it has nothing left to merge into.
    """
    pers = tree.persistence
    parent = tree.parent
    keep = (pers >= persistence) | (parent < 0)

    out = np.arange(len(tree), dtype=np.int32)
    # Components are created in descending-intensity order, so a parent always has a
    # lower index than its child. One backward pass therefore fully resolves chains.
    for c in range(len(tree) - 1, -1, -1):
        if not keep[c]:
            out[c] = out[parent[c]]
    # Resolve any remaining indirection.
    for c in range(len(tree)):
        r = out[c]
        while out[r] != r:
            r = out[r]
        out[c] = r
    return out


def cut_topological(tree: MergeTree, persistence: float,
                    min_voxels: int = 6) -> np.ndarray:
    """Segmentation by the tree's own first-touch rule.

    **Do not use this to build a catalogue.** It is topologically correct but a poor
    spatial partition: when two peaks share a skirt, every voxel below the saddle
    goes wholesale to whichever peak the descending sweep reached first, rather
    than being divided along the drainage divide.

    Measured on two nearly equal peaks (10.0 and 9.5 mm/hr): this rule split them
    684 voxels to 177, where a watershed gave 441 to 420. That would distort every
    volume in a catalogue by a factor of several.

    Kept because it is the right object for counting components and for reasoning
    about the hierarchy, where the spatial division does not matter. For anything
    that measures rain, use `segment_at`.
    """
    from segment import drop_small

    if len(tree) == 0:
        return np.zeros(tree.shape, np.int32)

    surv = _survivor_map(tree, persistence)
    comp = tree.comp
    labels = np.zeros(comp.shape, np.int32)
    m = comp >= 0
    _, inv = np.unique(surv[comp[m]], return_inverse=True)
    labels[m] = (inv + 1).astype(np.int32)
    return drop_small(labels, min_voxels)


def segment_at(tree: MergeTree, R: np.ndarray, persistence: float,
               min_voxels: int = 6) -> np.ndarray:
    """Segmentation at a given prominence. **This is the one to use.**

    The tree supplies which maxima survive at this persistence, which is the cheap
    part and the part that carries the hierarchy. A watershed seeded on those
    maxima supplies the spatial division, which splits a shared skirt along the
    drainage divide instead of handing it to one peak.

    Equivalent in intent to `segment.label_watershed(R, wet, persistence)`, but the
    expensive h-maxima reconstruction is replaced by a lookup in the prebuilt tree,
    so sweeping h over a built tree is far cheaper than re-segmenting each time.
    """
    from skimage.segmentation import watershed

    from segment import drop_small

    if len(tree) == 0:
        return np.zeros(tree.shape, np.int32)

    Rf = np.nan_to_num(np.asarray(R, dtype=np.float32), nan=0.0)
    wet = Rf >= tree.wet_threshold

    surv = _survivor_map(tree, persistence)
    roots = np.flatnonzero(surv == np.arange(len(tree)))
    if roots.size == 0:
        return np.zeros(tree.shape, np.int32)

    markers = np.zeros(Rf.size, np.int32)
    markers[tree.peak_flat[roots]] = np.arange(1, roots.size + 1, dtype=np.int32)
    markers = markers.reshape(Rf.shape)

    labels = watershed(-Rf, markers=markers, mask=wet).astype(np.int32)
    return drop_small(labels, min_voxels)


def hierarchy(tree: MergeTree, persistence: float) -> "list[dict]":
    """Surviving components at `persistence`, with their immediate children.

    This is what a catalogue needs in order to say "this storm split from that
    system": a substorm is a component whose nearest surviving ancestor is another
    storm.
    """
    surv = _survivor_map(tree, persistence)
    pers = tree.persistence
    out = {}
    for c in range(len(tree)):
        s = int(surv[c])
        if s == c:
            out.setdefault(s, {"component": s, "birth": float(tree.birth[c]),
                               "death": float(tree.death[c]),
                               "persistence": float(pers[c]), "children": []})
    for c in range(len(tree)):
        s = int(surv[c])
        if s != c and s in out:
            out[s]["children"].append({"component": c,
                                       "birth": float(tree.birth[c]),
                                       "persistence": float(pers[c])})
    return list(out.values())
