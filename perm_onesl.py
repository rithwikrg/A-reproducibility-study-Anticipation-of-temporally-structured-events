import glob
import sys
import nibabel as nib
import numpy as np
from tqdm import tqdm
import pickle
from numpy.random import default_rng
from s_light import one_sl, one_sl_SF

data_fpath = '../data/'
output_fpath = '../outputs/perm/'
subjects = glob.glob(data_fpath + '*pred*')
header_fpath = data_fpath + 'header.nii'

analysis_type = int(sys.argv[1])
sl_i = int(sys.argv[2])
perm_start = int(sys.argv[3])
perm_end = int(sys.argv[4])

rng = default_rng(perm_start) # Seed with perm start

if analysis_type == 4:
    sl_AUCdiffs_Intact = []
    sl_AUCdiffs_SFix = []
else:
    sl_AUCs = []
    if analysis_type == 3:
        sl_K = []

for i in tqdm(range(perm_start, perm_end)):
    subj_perms = dict()
    for s in subjects:
        if i == 0:
            # First perm is the real analysis
            subj_perms[s] = np.arange(6)
        else:
            subj_perms[s] = rng.permutation(6)

    if analysis_type == 0:
        # Traditional
        sl_AUCs.append(one_sl('../data/SL/' + str(sl_i) + '.h5', subj_perms, True, False, 0)[0])
    elif analysis_type == 1:
        # SRM10
        sl_AUCs.append(one_sl('../data/SL/' + str(sl_i) + '.h5', subj_perms, True, False, 10)[0])
    elif analysis_type == 2:
        # Joint fit 6
        sl_AUCs.append(one_sl('../data/SL/' + str(sl_i) + '.h5', subj_perms, False, False, 0)[0])
    elif analysis_type == 3:
        # Tune K
        sl_res = one_sl('../data/SL/' + str(sl_i) + '.h5', subj_perms, True, True, 0)
        sl_AUCs.append(sl_res[0])
        sl_K.append(sl_res[1])
    elif analysis_type == 4:
        # SFix
        sl_res = one_sl_SF('../data/SL/' + str(sl_i) + '.h5', subj_perms, True)
        sl_AUCdiffs_Intact.append(sl_res[0])
        sl_AUCdiffs_SFix.append(sl_res[1])

with open(output_fpath + '/pickles/_' + str(analysis_type) + '_' + str(sl_i) + '_' + str(perm_start) + '_' + str(perm_end) +'_.p', 'wb') as fp:
    if analysis_type == 4:
        pickle.dump((sl_AUCdiffs_Intact, sl_AUCdiffs_SFix), fp)
    elif analysis_type == 3:
        pickle.dump((sl_AUCs, sl_K), fp)
    else:
        pickle.dump(sl_AUCs, fp)
