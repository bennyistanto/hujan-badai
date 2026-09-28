"""Storm segmentation on the 3D (time, lat, lon) intensity cube.

Two methods, so the proposed one has a baseline to beat.

`label_ccl`
    ST-CORA as published: threshold to a binary field, 3D connected-component
    labelling with a 26-neighbour system, drop objects below a voxel count.
    Measured on this domain it percolates badly: at the papers' own 1 mm/h a
    single object holds ~90% of all wet voxels and spans the full domain and
    window. Kept as the baseline, not as a recommendation.

`label_watershed`
    Partition rather than level set. Seed on local maxima whose intensity
    prominence exceeds `prominence`, then watershed the intensity field inside
    the wet mask. Every wet voxel is assigned to exactly one storm, so no single
    object can swallow the domain however connected the rain field is. This is
    percolation-immune by construction, which is the whole point.

Both return an int32 label array, 0 for background.

On the merge tree
-----------------
The design in docs/plan.md calls for retaining the saddle structure so substorms
and split/merge history come for free. That is not implemented here yet.
`label_watershed` at several `prominence` values gives a practical hierarchy in
the meantime; a real merge tree is a later refinement. Do not describe this module
as providing one.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

# 26-neighbour system in space and time, as specified in Laverde-Barajas et al.
# 2019. scipy's default for 3D is 6-connectivity, which is NOT what the papers
# describe, so this must be passed explicitly everywhere.
STRUCT_26 = np.ones((3, 3, 3), dtype=bool)


def drop_small(labels: np.ndarray, min_voxels: int) -> np.ndarray:
    """Zero out objects below a voxel count and renumber the survivors 1..N."""
    if min_voxels <= 1:
        return labels
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    keep = np.flatnonzero(counts >= min_voxels)
    remap = np.zeros(counts.size, dtype=np.int32)
    remap[keep] = np.arange(1, keep.size + 1, dtype=np.int32)
    return remap[labels]


def label_ccl(R: np.ndarray, threshold: float = 1.0,
              min_voxels: int = 6) -> np.ndarray:
    """ST-CORA baseline. See the module docstring on why this percolates here.

    `min_voxels` default of 6 is the size filter from the 2019 paper.
    """
    labels, _ = ndi.label(R >= threshold, structure=STRUCT_26)
    return drop_small(labels.astype(np.int32), min_voxels)


def label_watershed(R: np.ndarray, wet_threshold: float = 1.0,
                    prominence: float = 2.0, min_voxels: int = 6,
                    return_markers: bool = False):
    """Prominence-seeded 3D watershed inside the wet mask.

    Parameters
    ----------
    R
        Intensity cube in mm/hr, shape (time, lat, lon). NaN is treated as dry.
    wet_threshold
        Bounds the analysis. Keeps weak storm edges, unlike `label_ccl` where the
        same number also decides what counts as a separate object.
    prominence
        The one parameter that matters, in mm/hr. A local maximum seeds a storm
        only if it rises this far above the highest saddle joining it to a
        stronger maximum. Low values split more; high values merge more.
    min_voxels
        Size filter applied after the watershed.

    Notes
    -----
    `wet_threshold` and `prominence` do different jobs, which is the structural
    difference from the baseline. In `label_ccl` one threshold has to both find
    the rain and separate the storms, and over this domain it cannot do both.
    """
    from skimage.morphology import h_maxima
    from skimage.segmentation import watershed

    Rf = np.nan_to_num(np.asarray(R, dtype=np.float32), nan=0.0)
    wet = Rf >= wet_threshold
    if not wet.any():
        out = np.zeros(Rf.shape, dtype=np.int32)
        return (out, out) if return_markers else out

    # Seeds: maxima with intensity prominence >= `prominence`, inside the wet mask.
    seeds = h_maxima(Rf, prominence) > 0
    seeds &= wet
    markers, n = ndi.label(seeds, structure=STRUCT_26)
    if n == 0:
        # No maximum is prominent enough. Fall back to connected components so the
        # caller gets the wet field rather than an empty result, and can see why.
        return label_ccl(Rf, wet_threshold, min_voxels)

    # Watershed descends, so invert: high intensity becomes a basin bottom.
    labels = watershed(-Rf, markers=markers, mask=wet).astype(np.int32)
    labels = drop_small(labels, min_voxels)
    return (labels, markers.astype(np.int32)) if return_markers else labels


def percolation_share(labels: np.ndarray) -> float:
    """Fraction of labelled voxels inside the single largest object.

    The diagnostic that drove the whole design. Above roughly 0.20 the labelling
    is not producing storm objects. Always report it with the window length: the
    denominator is window-dependent, so a short window inflates it.
    """
    counts = np.bincount(labels.ravel())
    if counts.size < 2:
        return 0.0
    counts[0] = 0
    total = counts.sum()
    return float(counts.max() / total) if total else 0.0
