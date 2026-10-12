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
import os
from scipy.stats import gmean
import datetime

current_date = datetime.date.today()

csv_path = f'../results/benchmarks_all_patterns_real_hypergraphs_3090_{current_date}.csv'
read_file = '../results/motivation_data_all_baseline_top100_20240106.csv'
# csv_path = f'../results/overP2/benchmarks_select_patterns_real_hypergraphs_3090_{current_date}.csv'

def brute_force_each_pattern():
    
    # data = pd.read_csv(read_file)
    # column_values = data.iloc[:, 0].tolist()
    # print(column_values)
    # norm_val = gmean(data.iloc[:,30] / data.iloc[:,29])
    
    # write_file = f'../results/overP2/benchmarks_all_patterns_top100_3090_{current_date}.csv'
    # write_file = '../results/overP2/benchmarks_all_patterns_filter_avgsizecv_3090_240104.csv'
    cmd = f"cd ../build && cmake .. && make -j8 "
    # input.subprocess.call(cmd, shell=True)
    
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
        # out.write("id,dataset,gHyPart,select_matching_pattern,select_merging_pattern,select_construction_pattern\n")
        # out.write("id,dataset,gHyPart-rand\n")
        # out.write("id,dataset,gHyPart-P2P2P2b\n")
        # out.write("id,dataset,gHyPart-P3P3P3\n")
        count = 0
        for key, value in input.input_map.items():
        # for key, value in input.synthetics.items():
            # if value == 'as-Skitter':
            if count >= 0:
            # if count >= 488 and count <= 495:
                print(str(count), value)
                out.write(str(count)+","+value+",")
                file_path = input.os.path.join(input.dir_path, key)
                our_impl = []
                patterns = {}
                best = 0.0
                '''
                # base
                LOG = "../results/base.log"
                base.run_pattern_combination(out, file_path, our_impl, patterns, LOG)
                
                # p3_k123_k5
                LOG = "../results/ours.log"
                k1k2k3k5.run_pattern_combination(out, file_path, our_impl, patterns, LOG)
                
                # # p2_k4_k6
                k4k6.run_pattern_p2(out, file_path, our_impl, patterns, LOG)
                
                # # p3_k4_k6
                k4k6.run_pattern_p3(out, file_path, our_impl, patterns, LOG)
                
                # p2_k12
                p2k12.run_pattern(out, file_path, our_impl, patterns, LOG)
                
                # p2_k12_p2_k4_k6
                p2k12.run_pattern_p2(out, file_path, our_impl, patterns, LOG)
                
                # p2_k12_p3_k4_split_k6
                p2k12.run_pattern_p3(out, file_path, our_impl, patterns, LOG)
                
                # p3_k12
                p3k12.run_pattern(out, file_path, our_impl, patterns, LOG)
                
                # p3_k12_p2_k4_k6
                p3k12.run_pattern_p2(out, file_path, our_impl, patterns, LOG)
                
                # p3_k12_p3_k4_split_k6
                p3k12.run_pattern_p3(out, file_path, our_impl, patterns, LOG)
                
                # p2b_k12
                p2bk12.run_pattern(out, file_path, our_impl, patterns, LOG)
                
                # p2b_k12_p2_k4_k6
                p2bk12.run_pattern_p2(out, file_path, our_impl, patterns, LOG)
                
                # p2b_k12_p3_k4_split_k6
                p2bk12.run_pattern_p3(out, file_path, our_impl, patterns, LOG)
                
                best = min(our_impl)
                print("cur_best:" + str(best))
                '''
                # selection
                # LOG = "../results/ours.log" 
                # selection_k12_pattern = ''
                # selection_k4_pattern = ''
                # avghedgesize = ''
                # relative_sdv = ''
                # select_pattern = {}
                # edge_cut = ''
                # best_k12_pattern = ''
                # best_k4_pattern = ''
                # best_speedup = 0.0
                # select_speedup = 0.0
                # slt.select_pattern(out, file_path, our_impl, best, selection_k12_pattern, selection_k4_pattern,
                #                    avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                #                    best_k12_pattern, best_k4_pattern, best_speedup, select_speedup, LOG)
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
                # ap.random_select_pattern(out, file_path, our_impl, best, 
                #                 selection_k12_pattern, selection_k4_pattern, selection_k1_pattern,
                #                 avghedgesize, relative_sdv, select_pattern, patterns, edge_cut, 
                #                 best_k12_pattern, best_k4_pattern, best_k1_pattern,
                #                 best_speedup, select_speedup, LOG)
            count+=1    
                 
    ghypart_geom = []
    ghypartO_geom = []
    power_law_geom = []
    power_law_geomO = []
    top100_geom = []
    top100_geomO = []
'''
    with open(csv_path, 'r') as file:
        reader = input.csv.reader(file)
        count = 0
        rows_to_write = []
        for row in reader:
            # if count >= 494 and count <= 985:
            # if count >= 1 and count <= 492:
            if count >= 1:
                # print(row[1])
                # over P1
                # if row[17] != 'gHyPart_speedup':
                #     ghypart_geom.append(float(row[17]))
                # if row[18] != 'best_speedup':
                #     ghypartO_geom.append(float(row[18]))
                # over P2
                # if row[15] != 'gHyPart_speedup':
                #     ghypart_geom.append(float(row[15]))
                # if row[16] != 'best_speedup':
                #     ghypartO_geom.append(float(row[16]))
                # over P2 all
                if row[31] != 'gHyPart_speedup':
                    ghypart_geom.append(float(row[31]))
                if row[32] != 'best_speedup':
                    ghypartO_geom.append(float(row[32]))
                
                # if float(row[42]) > 20.0 and float(row[43]) > 1000:
                #     if row[31] != 'gHyPart_speedup':
                #         power_law_geom.append(float(row[31]))
                #     if row[32] != 'best_speedup':
                #         power_law_geomO.append(float(row[32]))
                #     rows_to_write.append(row)
                # if float(row[39]) >= 25.0 or float(row[40]) >= 3.0:
                #     if row[31] != 'gHyPart_speedup':
                #         power_law_geom.append(float(row[31]))
                #     if row[32] != 'best_speedup':
                #         power_law_geomO.append(float(row[32]))
                #     rows_to_write.append(row)
                if row[1] in column_values:
                    if row[31] != 'gHyPart_speedup':
                        top100_geom.append(float(row[31]))
                    if row[32] != 'best_speedup':
                        top100_geomO.append(float(row[32]))
                    rows_to_write.append(row)
            count+=1
        with open(write_file, 'w', newline='') as output_file:
            writer = csv.writer(output_file)
            # writer.writerow(header)  # 写入头部行
            writer.writerows(rows_to_write)
    
    print(len(ghypart_geom),len(power_law_geom))        
    geomean1 = '{:.4f}'.format(input.math.pow(input.math.prod(ghypart_geom), 1 / len(ghypart_geom)))
    geomean2 = '{:.4f}'.format(input.math.pow(input.math.prod(ghypartO_geom), 1 / len(ghypartO_geom)))
    print(geomean1)
    print(geomean2)
    
    # geomean3 = '{:.4f}'.format(input.math.pow(input.math.prod(power_law_geom), 1 / len(power_law_geom)))
    # geomean4 = '{:.4f}'.format(input.math.pow(input.math.prod(power_law_geomO), 1 / len(power_law_geomO)))

    geomean3 = '{:.4f}'.format(input.math.pow(input.math.prod(top100_geom), 1 / len(top100_geom)))
    geomean4 = '{:.4f}'.format(input.math.pow(input.math.prod(top100_geomO), 1 / len(top100_geomO)))
    print(geomean3)
    print(geomean4)
    # print(gmean(top100_geom))
    with open(write_file, 'a') as out:
        # out.write("GMean,,,,,,,,,,,,,,,,,"+geomean1+","+geomean2+"\n")
        # out.write("GMean,,,,,,,,,,,,,,,"+geomean1+","+geomean2+"\n")
        # out.write("PowerLawGMean,,,,,,,,,,,,,,,"+geomean3+","+geomean4+"\n")
        # out.write("GMean,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"+geomean1+","+geomean2+"\n")
        out.write("GMean,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"+geomean3+","+geomean4+"\n")
'''           

if __name__ == '__main__':
    start_time = time.time()
    brute_force_each_pattern()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
