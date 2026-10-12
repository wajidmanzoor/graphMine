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
import datetime
import os
import glob

current_date = datetime.date.today()
sync_dir = '../../synthetic_hypergraphs/v1/'
file_list = glob.glob(os.path.join(sync_dir, '*.hgr'))

filename_list = []
for file in file_list:
    filename_list.append(os.path.basename(file))
    
rounds = 3
count = 0
for i in range(rounds):
    csv_path = f'../results/benchmarks_all_patterns_synthetic_hypergraphs_liu3090_{current_date}_{i}.csv'
    # csv_path = f'../results/benchmarks_all_patterns_real_hypergraphs_3090_{current_date}_{i}.csv'
    with open(csv_path, 'a') as out:
        out.write("id,dataset,")
        out.write("p1_k1235_p1_k4k6_p2_k12,p2_k1235_p1_k4k6_p2_k12,p3_k1235_p1_k4k6_p2_k12,")
        out.write("p1_k1235_p2_k4k6_p2_k12,p2_k1235_p2_k4k6_p2_k12,p3_k1235_p2_k4k6_p2_k12,")
        out.write("p1_k1235_p3_k4k6_p2_k12,p2_k1235_p3_k4k6_p2_k12,p3_k1235_p3_k4k6_p2_k12,")
        out.write("p1_k1235_p1_k4k6_p3_k12,p2_k1235_p1_k4k6_p3_k12,p3_k1235_p1_k4k6_p3_k12,")
        out.write("p1_k1235_p2_k4k6_p3_k12,p2_k1235_p2_k4k6_p3_k12,p3_k1235_p2_k4k6_p3_k12,")
        out.write("p1_k1235_p3_k4k6_p3_k12,p2_k1235_p3_k4k6_p3_k12,p3_k1235_p3_k4k6_p3_k12,")
        out.write("p1_k1235_p1_k4k6_p2b_k12,p2_k1235_p1_k4k6_p2b_k12,p3_k1235_p1_k4k6_p2b_k12,")
        out.write("p1_k1235_p2_k4k6_p2b_k12,p2_k1235_p2_k4k6_p2b_k12,p3_k1235_p2_k4k6_p2b_k12,")
        out.write("p1_k1235_p3_k4k6_p2b_k12,p2_k1235_p3_k4k6_p2b_k12,p3_k1235_p3_k4k6_p2b_k12,")
        out.write("gHyPart,best,gHyPart_speedup,best_speedup,")
        out.write("matching_select_pattern,matching_best_pattern,")
        out.write("node_merging_select_pattern,node_merging_best_pattern,")
        out.write("construction_select_pattern,construction_best_pattern,")
        out.write("avghedgesize,sdv/avg,edge_cut\n")
        
for key, value in input.input_map.items():
    # if value == 'road_usa' or value == 'HV15R':
    syn_file = 'syn_' + value + '.hgr'
    # if count >= 498 and syn_file in filename_list:
    if count >= 0:
        for i in range(rounds):
            # csv_path = f'../results/overP2/benchmarks_all_patterns_real_hypergraphs_3090_{current_date}_{i}.csv'
            # csv_path = f'../results/overP2/benchmarks_all_patterns_synthetic_hypergraphs_3090_{current_date}_{i}.csv'
            csv_path = f'../results/overP2/benchmarks_all_patterns_synthetic_hypergraphs_liu3090_{current_date}_{i}.csv'
            with open(csv_path, 'a') as out:
                # print(str(count), value)
                # out.write(str(count)+","+value+",")
                # file_path = input.os.path.join(input.dir_path, key)
                
                file_path = os.path.join(sync_dir, syn_file)
                print(file_path)
                print(str(count), syn_file)
                out.write(str(count)+",syn_"+value+",")
                if value == 'nd12k' or value == 'Trec' or value == 'road_usa':
                # if value == '@@@':
                    out.write("\n")
                else:
                    our_impl = []
                    patterns = {}
                    best = 0.0
                    LOG = "../results/ours.log"
                    # '''
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
                    # '''
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
    
    