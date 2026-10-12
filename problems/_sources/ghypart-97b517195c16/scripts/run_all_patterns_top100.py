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

current_date = datetime.date.today()

read_file = '../results/overP2/motivation_data_all_baseline_top100_20240106.csv'
csv_path = '../results/overP2/benchmarks_all_patterns_real_hypergraphs_3090_2024-01-06.csv'


ghypart_geom = []
ghypartO_geom = []
power_law_geom = []
power_law_geomO = []
top100_geom = []
top100_geomO = []

data = pd.read_csv(read_file)
column_values = data.iloc[:, 0].tolist()
print(column_values)
write_file = '../results/benchmarks_all_patterns_top100_3090_240106.csv'

with open(write_file, 'a') as out:
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
        
with open(csv_path, 'r') as file:
    reader = input.csv.reader(file)
    count = 0
    rows_to_write = []
    for row in reader:
        # if count >= 494 and count <= 985:
        # if count >= 1 and count <= 492:
        if count >= 1:
            if row[1] in column_values:
                if row[31] != 'gHyPart_speedup':
                    top100_geom.append(float(row[31]))
                if row[32] != 'best_speedup':
                    top100_geomO.append(float(row[32]))
                rows_to_write.append(row)
        count+=1
    with open(write_file, 'a', newline='') as output_file:
        writer = csv.writer(output_file)
        # writer.writerow(header)  # 写入头部行
        writer.writerows(rows_to_write)

geomean3 = '{:.4f}'.format(input.math.pow(input.math.prod(top100_geom), 1 / len(top100_geom)))
geomean4 = '{:.4f}'.format(input.math.pow(input.math.prod(top100_geomO), 1 / len(top100_geomO)))
print(geomean3)
print(geomean4)
# print(gmean(top100_geom))
with open(write_file, 'a') as out:
    out.write("GMean,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,"+geomean3+","+geomean4+"\n")
