import glob
from copy import deepcopy
import numpy as np
import nibabel as nib
from scipy.stats import pearsonr, norm, zscore
from brainiak.eventseg.event import EventSegment
from brainiak.funcalign.srm import DetSRM

def nearest_peak(v):
    # v is 2*max_lag + 1
    # returns quadratic peak

    lag = (len(v)-1)//2
    while (lag >= 2 and lag <= len(v) - 3):
        win = v[(lag-1):(lag+2)]
        if (win[1] > win[0]) and (win[1] > win[2]):
            break
        if win[0] > win[2]:
            lag -= 1
        else:
            lag += 1

    x = [lag-1, lag, lag+1]
    y = v[(lag-1):(lag+2)]
    denom = (x[0] - x[1]) * (x[0] - x[2]) * (x[1] - x[2])
    A = (x[2] * (y[1] - y[0]) + x[1] * (y[0] - y[2]) + x[0] * (y[2] - y[1])) / denom
    B = (x[2]*x[2] * (y[0] - y[1]) + x[1]*x[1] * (y[2] - y[0]) + x[0]*x[0] * (y[1] - y[2])) / denom

    max_x = (-B / (2*A))
    return min(max(max_x, 0), len(v)-1)

def hyperalign(subj_list, nFeatures=15):
    # subj_list is list of Reps x TRs x Vox matrices
    # returns list of Reps x TRs x nFeatures
    nReps = subj_list[0].shape[0]
    nTRs = subj_list[0].shape[1]

    # Remove voxels == 0
    subj_list = [d[:,:,np.all(~np.all(d == 0, axis=1), axis=0)] for d in subj_list]
    # Remove any subjects whose # voxels drop below nFeatures
    subj_list = [d for d in subj_list if d.shape[2] >= nFeatures]

    subj_list = [d.T.reshape(d.shape[-1], nTRs*nReps) for d in subj_list]
    srm = DetSRM(features=nFeatures)
    srm.fit(subj_list)
    shared = srm.transform(subj_list)
    shared = [zscore(d.reshape(d.shape[0], nTRs, nReps), axis=1, ddof=1).T for d in shared]
    return shared

def heldout_ll(data, n_events, split):
    # Data is subj x TR x Voxels
    # split is T/F to define split groups
    nSubj = data.shape[0]
    d = deepcopy(data)

    # Remove nan vox
    nan_idxs = np.where(np.isnan(d))
    nan_idxs = list(set(nan_idxs[2]))
    d = np.delete(np.asarray(d), nan_idxs, axis=2)

    group1 = d[split].mean(0)
    group2 = d[~split].mean(0)
    es = EventSegment(n_events).fit(group1)
    _, ll12 = es.find_events(group2)
    es = EventSegment(n_events).fit(group2)
    _, ll21 = es.find_events(group1)

    return (ll12 + ll21)/2

def tj_fit(data, n_events=7, avg_lasts=True):

    """Jointly fits HMM to multiple trials (repetitions).

    Parameters
    ----------
    data : ndarray
        Data dimensions: Repetition x TR x Voxels

    n_events : int
        Number of events to fit

    avg_lasts : bool, optional
        If true, all viewings after the first are averaged

    Returns
    -------
    list of ndarrays
        Resulting segmentations from model fit
    """

    d = deepcopy(data)

    if avg_lasts:
        d = [d[0], np.nanmean(d[1:], axis=0)]
    d = np.asarray(d)

    nan_idxs = np.where(np.isnan(d))
    nan_idxs = list(set(nan_idxs[2]))

    d = np.delete(np.asarray(d), nan_idxs, axis=2)

    ev_obj = EventSegment(n_events).fit(list(d))

    return ev_obj.segments_


def get_AUCs(segs):
    """Computes the Area Under the Curve for HMM segmentations

    Takes a list of HMM segmentations (each a time x event ndarray of the
    probability of being in each event at each timepoint) and computes the
    expected value of the event number at each timepoint, then sums across
    timepoints to yield the area under this curve.

    Parameters
    ----------
    segs : list of ndarrays
        Time x event probabilities from HMM segmentations

    Returns
    -------
    ndarray
        AUCs for each segmentation, rounded to 2 decimal places

    """

    auc = [round(np.dot(segs[rep], np.arange(segs[rep].shape[1])).sum(), 2)
           for rep in range(len(segs))]

    return np.asarray(auc)


def FDR_p(pvals):
    """Port of AFNI mri_fdrize.c

    Computes False Discovery Rate thresholds (q) for a set of p values

    Parameters
    ----------
    pvals : ndarray
        p values

    Returns
    -------
    ndarray
        q values
    """

    assert np.all(pvals >= 0) and np.all(pvals <= 1)
    pvals[pvals < np.finfo(np.float_).eps] = np.finfo(np.float_).eps
    pvals[pvals == 1] = 1-np.finfo(np.float_).eps
    n = pvals.shape[0]

    qvals = np.zeros((n))
    sorted_ind = np.argsort(pvals)
    sorted_pvals = pvals[sorted_ind]
    qmin = 1.0
    for i in range(n-1, -1, -1):
        qval = (n * sorted_pvals[i])/(i+1)
        if qval > qmin:
            qval = qmin
        else:
            qmin = qval
        qvals[sorted_ind[i]] = qval

    # Estimate number of true positives m1 and adjust q
    if n >= 233:
        phist = np.histogram(pvals, bins=20, range=(0, 1))[0]
        sorted_phist = np.sort(phist[3:19])
        if np.sum(sorted_phist) >= 160:
            median4 = n - 20*np.dot(np.array([1, 2, 2, 1]),
                                    sorted_phist[6:10])/6
            median6 = n - 20*np.dot(np.array([1, 2, 2, 2, 2, 1]),
                                    sorted_phist[5:11])/10
            m1 = min(median4, median6)

            qfac = (n - m1)/n
            if qfac < 0.5:
                qfac = 0.25 + qfac**2
            qvals *= qfac

    return qvals


def lag_pearsonr(x, y, max_lags):
    """Compute lag correlation between x and y, up to max_lags

    Parameters
    ----------
    x : ndarray
        First array of values
    y : ndarray
        Second array of values
    max_lags: int
        Largest lag (must be less than half the length of shortest array)

    Returns
    -------
    ndarray
        Array of 1 + 2*max_lags lag correlations, for x left shifted by
        max_lags to x right shifted by max_lags
    """

    assert max_lags < min(len(x), len(y)) / 2, \
        "max_lags exceeds half the length of shortest array"

    assert len(x) == len(y), "array lengths are not equal"

    lag_corrs = np.full(1 + (max_lags * 2), np.nan)

    for i in range(max_lags + 1):

        # add correlations where x is shifted to the right
        lag_corrs[max_lags + i] = pearsonr(x[:len(x) - i], y[i:len(y)])[0]

        # add correlations where x is shifted to the left
        lag_corrs[max_lags - i] = pearsonr(x[i:len(x)], y[:len(y) - i])[0]

    return lag_corrs


def ev_annot_freq(bootstrap_rng=None):
    """Compute binned frequencies of event boundary annotations

    Returns
    -------
    ndarray
        Proportion of raters marking a boundary for each second
    """

    ev_annots = np.asarray(
        [[5, 12, 54, 77, 90],
         [3, 12, 23, 30, 36, 43, 50, 53, 78, 81, 87, 90],
         [11, 23, 30, 50, 74],
         [1, 55, 75, 90],
         [4, 10, 53, 77, 82, 90],
         [11, 54, 77, 81, 90],
         [12, 22, 36, 54, 78],
         [12, 52, 79, 90],
         [10, 23, 30, 36, 43, 50, 77, 90],
         [13, 55, 79, 90],
         [4, 10, 23, 29, 35, 44, 51, 56, 77, 80, 85, 90],
         [11, 55, 78, 90],
         [11, 30, 43, 54, 77, 90],
         [4, 11, 24, 30, 38, 44, 54, 77, 90]],
    dtype=object)

    nAnnots = len(ev_annots)

    if bootstrap_rng is not None:
        ev_annots = ev_annots[bootstrap_rng.integers(0, nAnnots, size=nAnnots)]
    frequencies = np.bincount(np.concatenate(ev_annots))
    return np.array(frequencies[1:], dtype=np.float64)/nAnnots


def hrf_convolution(ev_annots_freq):
    """Convolve boundary frequencies with the HRF from AFNI's 3dDeconvolve

    Parameters
    ----------
    ev_annots_freq : ndarray
        Proportion of raters marking a boundary for each second

    Returns
    -------
    ndarray
        Boundary frequencies convolved with an HRF
    """

    dts = np.arange(0, 15)
    pp = 8.6
    qq = 0.547
    hrf = lambda dt, p, q: np.power(dt / (p * q), p) * np.exp(p - dt / q)

    TR = 1.5
    nTR = 60
    T = len(ev_annots_freq)

    X_conv = np.convolve(ev_annots_freq, hrf(dts, pp, qq))[:T]


    return np.interp(np.linspace(0, (nTR - 1) * TR, nTR),
                     np.arange(0, T), X_conv)


def get_DTs(ev_seg):
    """Compute derivative of expected event number from an HMM segmentation

    Parameters
    ----------
    ev_seg : ndarray
        Time x event probability from an HMM segmentation

    Returns
    -------
    list
        Diff in expected event number between successive pairs of timepoints
    """

    nTR = ev_seg.shape[0]
    n_events = ev_seg.shape[1]

    evs = np.dot(ev_seg, np.arange(n_events))

    return [(evs[tr + 1] - evs[tr]) / ((tr + 1) - tr) for tr in range(nTR - 1)]

def save_nii(new_fpath, header_fpath, data):
    """Save data into a nifti file, using header from an existing file

    Parameters
    ----------
    new_fpath : string
        File to save to
    header_fpath : string
        File to copy header information from
    data : ndarray
        3d voxel data (will be transposed to become x/y/z)
    """
    img = nib.load(header_fpath)
    new_img = nib.Nifti1Image(data.T, img.affine, img.header)
    nib.save(new_img, new_fpath)

def bootstrap_stats(boot_regex, savename, use_z = True):
    """Compute statistics from bootstraps

    If use_z = True, compute a z statistic using a Normal distribution and
    correct for FDR, otherwise compute a p value as the fraction of
    bootstraps less than zero.

    Parameters
    ----------
    boot_regex : string
        File pattern for bootstraps
    savename : string
        File to save p values to
    use_z : boolean, optional
        Determines the type of p value computation
    """
    bfiles = glob.glob(boot_regex)
    d = np.stack([nib.load(f).get_fdata() for f in bfiles], axis=-1)
    valid_vox = ~np.all(np.isnan(d), axis=3)

    if use_z:
        mean_d = d[valid_vox].mean(1)
        std_d = np.std(d[valid_vox], axis=1)
        p = norm.sf(mean_d/std_d)
        p = FDR_p(p)
    else:
        p = np.mean(d[valid_vox] < 0, axis=1)

    vox_p = np.full(d.shape[:3], np.nan)
    vox_p[valid_vox] = p
    save_nii(savename, bfiles[0], vox_p.T)

def mask_nii(fpath, mask_path, savename, threshold=0.05):
    """Mask a nii file using a statistical map

    Parameters
    ----------
    fpath : string
        File path of target nii
    mask_path : string
        File path for mask nii
    savename : string
        File to save masked nii to
    threshold : float
        Statistical threshold for mask
    """
    mask = nib.load(mask_path).get_fdata() < threshold
    d = nib.load(fpath).get_fdata()
    d_masked = np.full(d.shape, np.nan)
    d_masked[mask] = d[mask]
    save_nii(savename, fpath, d_masked.T)
