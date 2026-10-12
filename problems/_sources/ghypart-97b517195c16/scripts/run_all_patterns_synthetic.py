import input_header as input
import time
import csv
from patterns import base_pattern as base
from patterns import p3_for_k1k2k3k5 as k1k2k3k5
from patterns import k4k6_patterns as k4k6
from patterns import k12_pattern_p2 as p2k12
from patterns import k12_pattern_p3 as p3k12
from patterns import k12_pattern_p2b as p2bk12
from patterns import selection as slt
from patterns import all_patterns as ap
import pandas as pd
from scipy.stats import gmean
import os
import glob

csv_path = '../results/benchmarks_all_patterns_synthetic_hypergraphs.csv'

sync_dir = '../../synthetic_hypergraphs/v1/' # appu 
# sync_dir = '../../synthetic_hypergraphs/v2/'

suitesparse_dir = '../../mtx_benchmarkset/'

# pattern = os.path.join(suitesparse_dir, '*.hgr')
# file_list = sorted(glob.glob(os.path.join(suitesparse_dir, '*.hgr')))
# print(file_list)
file_list = glob.glob(os.path.join(sync_dir, '*.hgr'))
# file_list = sorted(file_list, key=lambda x: int(os.path.basename(x.split('.')[0])))
# file_list = sorted(file_list, key=lambda x: int(os.path.basename(x).split('.')[0].zfill(10)))
# print(file_list)

filename_list = []
for file in file_list:
    filename_list.append(os.path.basename(file))
# print(filename_list)
# skip_list = ['hypergraph11.hgr', 'hypergraph13.hgr', 'hypergraph11.hgr', 'hypergraph9.hgr']

with open(csv_path, 'a') as out:
    # out.write("id,dataset,")
    # out.write("p1_k1235_p1_k4k6_p2_k12,p2_k1235_p1_k4k6_p2_k12,p3_k1235_p1_k4k6_p2_k12,")
    # out.write("p1_k1235_p2_k4k6_p2_k12,p2_k1235_p2_k4k6_p2_k12,p3_k1235_p2_k4k6_p2_k12,")
    # out.write("p1_k1235_p3_k4k6_p2_k12,p2_k1235_p3_k4k6_p2_k12,p3_k1235_p3_k4k6_p2_k12,")
    # out.write("p1_k1235_p1_k4k6_p3_k12,p2_k1235_p1_k4k6_p3_k12,p3_k1235_p1_k4k6_p3_k12,")
    # out.write("p1_k1235_p2_k4k6_p3_k12,p2_k1235_p2_k4k6_p3_k12,p3_k1235_p2_k4k6_p3_k12,")
    # out.write("p1_k1235_p3_k4k6_p3_k12,p2_k1235_p3_k4k6_p3_k12,p3_k1235_p3_k4k6_p3_k12,")
    # out.write("p1_k1235_p1_k4k6_p2b_k12,p2_k1235_p1_k4k6_p2b_k12,p3_k1235_p1_k4k6_p2b_k12,")
    # out.write("p1_k1235_p2_k4k6_p2b_k12,p2_k1235_p2_k4k6_p2b_k12,p3_k1235_p2_k4k6_p2b_k12,")
    # out.write("p1_k1235_p3_k4k6_p2b_k12,p2_k1235_p3_k4k6_p2b_k12,p3_k1235_p3_k4k6_p2b_k12,")
    # out.write("gHyPart,best,gHyPart_speedup,best_speedup,")
    # out.write("matching_select_pattern,matching_best_pattern,")
    # out.write("node_merging_select_pattern,node_merging_best_pattern,")
    # out.write("construction_select_pattern,construction_best_pattern,")
    # out.write("avghedgesize,sdv/avg,edge_cut\n")
    count = 0
    # for file in file_list:
        # print(file)
    # for root, dirs, files in os.walk(mtx_dir):
    #     for file in files:
    #         print(file)
    for key, value in input.input_map.items():
        # file_path = file
        # file = os.path.basename(file_path)
        # print(file)
        syn_file = 'syn_' + value + '.hgr'
        if count >= 500 and syn_file in filename_list:
        # if count >= 38:
            file_path = os.path.join(sync_dir, syn_file)
            print(str(count), syn_file)
            print(file_path)
            out.write(str(count)+",syn_"+value+",")
            our_impl = []
            patterns = {}
            best = 0.0
            LOG = "../results/ours.log"
            ap.p1_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p1_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p2_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p3_k4k6_p2_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p1_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p2_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p3_k4k6_p3_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p1_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p2_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            
            ap.p1_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p2_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            ap.p3_k1235_p3_k4k6_p2b_k12(out, file_path, our_impl, patterns, LOG)
            
            best = min(our_impl)
            print("cur_best:" + str(best))
            selection_k12_pattern = ''
            selection_k4_pattern = ''
            selection_k1_pattern = ''
            avghedgesize = ''
            relative_sdv = ''
            select_pattern = {}
            edge_cut = ''
            best_k12_pattern = ''
            best_k4_pattern = ''
            best_k1_pattern = ''
            best_speedup = 0.0
            select_speedup = 0.0
            ap.select_pattern(out, file_path, our_impl, best, 
                            selection_k12_pattern, selection_k4_pattern, selection_k1_pattern,
                            avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                            best_k12_pattern, best_k4_pattern, best_k1_pattern,
                            best_speedup, select_speedup, LOG)
            
        count+=1
