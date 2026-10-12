import csv
import random
import matplotlib.pyplot as plt
import numpy as np
import sys
import os
import pandas as pd
# sys.path.append(".")
# import myplot
import matplotlib
import os
if os.environ.get('DISPLAY', '') == '':
    matplotlib.use('Agg')
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.pyplot import MultipleLocator
from matplotlib.ticker import ScalarFormatter
from matplotlib.ticker import FuncFormatter
from matplotlib.font_manager import FontProperties
import seaborn as sns
from scipy.stats import gmean
import datetime

current_date = datetime.date.today()

file = 'results/quality_comp_all_240112.csv'
file2 = 'results/mtkahypar_all_quality_xeon_4214R.csv'
file3 = 'results/prof_hmetis_xeon_4214R_all.csv'
file4 = 'results/ghypart_quality_results_2024-10-20.csv'
file5 = 'results/bipart_quality_results_2024-10-20.csv'

data = pd.read_csv(file)
data2 = pd.read_csv(file2)
data3 = pd.read_csv(file3)
data4 = pd.read_csv(file4)
data5 = pd.read_csv(file5)

original_bp2 = data['BiPart']
original_gp2 = data['gHyPart']
original_mt2 = data['Mt']
hedges = data['HEs']
dataset = data['dataset']

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", 
          "#800080", "#ffc0cb", "#ffa500", "#808080", 
          "#007fff", "#8e52dc", "#ff7f50", "#ff4500", 
          "#396e04", "#ff00ff", "#ff69b4", "#489177"]


def quality_comp_all_works():
    
    bipart2 = data5['bipart_cut2']
    bipart3 = data5['bipart_cut3']
    bipart4 = data5['bipart_cut4']
    
    ghypart2 = data4['ghypart_cut2']
    ghypart3 = data4['ghypart_cut3']
    ghypart4 = data4['ghypart_cut4']
    
    hmetis2 = data3['part2_cut']
    hmetis3 = data3['part3_cut']
    hmetis4 = data3['part4_cut']
    
    mtkahypar2 = data2['part2_cut']
    mtkahypar3 = data2['part3_cut']
    mtkahypar4 = data2['part4_cut']
    

    for i in range(len(data5)):
        if hedges[i] != data5['hedges'][i]: 
            print("Error: hedges are not equal")
        # if (original_bp2[i] != merged_data['bipart_cut2'][i]) and (bipart2[i] < ghypart2[i]):
            # print(f"Error: original_bp2 are not equal at index {i}")
            # if bipart2[i] < ghypart2[i]:
                # print(f"{dataset[i]}: {original_bp2[i]}, {original_gp2[i]}, {bipart2[i]}, {ghypart2[i]}")
                # with open(outfile, mode='a') as out_file:
                #     out_file.write(f"{i},{dataset[i]},2,{original_bp2[i]},{original_gp2[i]},\n")
        # if original_bp2[i] < original_gp2[i]:
            # print(f"{dataset[i]}: {original_bp2[i]}, {original_gp2[i]}, {bipart2[i]}, {ghypart2[i]}")
        if mtkahypar2[i] != original_mt2[i]:
            print(f"@{dataset[i]}: {original_mt2[i]}, {mtkahypar2[i]}")
        if original_bp2[i] != bipart2[i]:
            print(f"#{dataset[i]}: {original_bp2[i]}, {bipart2[i]}")
        if original_gp2[i] != ghypart2[i]:
            print(f"${dataset[i]}: {original_gp2[i]}, {ghypart2[i]}")

    diff2 = (bipart2 - ghypart2) / hedges
    # worse_than_bp_num = 0
    # comparable_with_bp = 0
    # better_than_bp_num = 0
    # count = 0
    # for value in diff2:
    #     if float(value) < -0.005:
    #         worse_than_bp_num+=1
    #     if float(value) > 0.005:
    #         better_than_bp_num+=1
    #     if float(value) >= -0.005 and float(value) <= 0.005:
    #         comparable_with_bp+=1
    #     count+=1
    # print(worse_than_bp_num, "{:.0%}".format(float(worse_than_bp_num/(len(hedges)))))
    # print(comparable_with_bp, "{:.0%}".format(float(comparable_with_bp/(len(hedges)))))
    # print(better_than_bp_num, "{:.0%}".format(float(better_than_bp_num/(len(hedges)))))

    print("gHyPart vs BiPart")
    count_within_range2 = (abs(diff2) <= 0.005).sum()
    count_larger_than_range2 = (diff2 > 0.005).sum()
    count_smaller_than_range2 = (diff2 < -0.005).sum()
    print("count_within_range2 = ", count_within_range2, "{:.0%}".format(float(count_within_range2/(len(hedges)))))
    print("count_larger_than_range2 = ", count_larger_than_range2, "{:.0%}".format(float(count_larger_than_range2/(len(hedges)))))
    print("count_smaller_than_range2 = ", count_smaller_than_range2, "{:.0%}".format(float(count_smaller_than_range2/(len(hedges)))))
    
    diff3 = (bipart3 - ghypart3) / hedges
    count_within_range3 = (abs(diff3) <= 0.005).sum()
    count_larger_than_range3 = (diff3 > 0.005).sum()
    count_smaller_than_range3 = (diff3 < -0.005).sum()
    print("count_within_range3 = ", count_within_range3, "{:.0%}".format(float(count_within_range3/(len(hedges)))))
    print("count_larger_than_range3 = ", count_larger_than_range3, "{:.0%}".format(float(count_larger_than_range3/(len(hedges)))))
    print("count_smaller_than_range3 = ", count_smaller_than_range3, "{:.0%}".format(float(count_smaller_than_range3/(len(hedges)))))
    
    diff4 = (bipart4 - ghypart4) / hedges
    count_within_range4 = (abs(diff4) <= 0.005).sum()
    count_larger_than_range4 = (diff4 > 0.005).sum()
    count_smaller_than_range4 = (diff4 < -0.005).sum()
    print("count_within_range4 = ", count_within_range4, "{:.0%}".format(float(count_within_range4/(len(hedges)))))
    print("count_larger_than_range4 = ", count_larger_than_range4, "{:.0%}".format(float(count_larger_than_range4/(len(hedges)))))
    print("count_smaller_than_range4 = ", count_smaller_than_range4, "{:.0%}".format(float(count_smaller_than_range4/(len(hedges)))))

    result2 = []
    result3 = []
    result4 = []
    for i in range(len(bipart2)):
        bp2 = float(bipart2[i])
        gh2 = float(ghypart2[i])
        # print(f"{dataset[i]}: {bp2}, {gh2}")
        if float(bipart2[i]) == 0:
            bp2 = 1
        if float(ghypart2[i]) == 0:
            gh2 = 1
        # print(f"{dataset[i]}: {bp2}, {gh2}")
        result2.append(gh2 / bp2)
        
        bp3 = float(bipart3[i])
        gh3 = float(ghypart3[i])
        if float(bipart3[i]) == 0:
            bp3 = 1
        if float(ghypart3[i]) == 0:
            gh3 = 1
        result3.append(gh3 / bp3)
        
        bp4 = float(bipart4[i])
        gh4 = float(ghypart4[i])
        if float(bipart4[i]) == 0:
            bp4 = 1
        if float(ghypart4[i]) == 0:
            gh4 = 1
        result4.append(gh4 / bp4)
    
    y_bp2 = gmean(result2)
    y_bp3 = gmean(result3)
    y_bp4 = gmean(result4)

    print("gHyPart vs MtKaHyPar")
    diff2 = (mtkahypar2 - ghypart2) / hedges
    count_within_range2 = (abs(diff2) <= 0.005).sum()
    count_larger_than_range2 = (diff2 > 0.005).sum()
    count_smaller_than_range2 = (diff2 < -0.005).sum()
    print("count_within_range2 = ", count_within_range2, "{:.0%}".format(float(count_within_range2/(len(hedges)))))
    print("count_larger_than_range2 = ", count_larger_than_range2, "{:.0%}".format(float(count_larger_than_range2/(len(hedges)))))
    print("count_smaller_than_range2 = ", count_smaller_than_range2, "{:.0%}".format(float(count_smaller_than_range2/(len(hedges)))))
    
    diff3 = (mtkahypar3 - ghypart3) / hedges
    count_within_range3 = (abs(diff3) <= 0.005).sum()
    count_larger_than_range3 = (diff3 > 0.005).sum()
    count_smaller_than_range3 = (diff3 < -0.005).sum()
    print("count_within_range3 = ", count_within_range3, "{:.0%}".format(float(count_within_range3/(len(hedges)))))
    print("count_larger_than_range3 = ", count_larger_than_range3, "{:.0%}".format(float(count_larger_than_range3/(len(hedges)))))
    print("count_smaller_than_range3 = ", count_smaller_than_range3, "{:.0%}".format(float(count_smaller_than_range3/(len(hedges)))))
    
    diff4 = (mtkahypar4 - ghypart4) / hedges
    count_within_range4 = (abs(diff4) <= 0.005).sum()
    count_larger_than_range4 = (diff4 > 0.005).sum()
    count_smaller_than_range4 = (diff4 < -0.005).sum()
    print("count_within_range4 = ", count_within_range4, "{:.0%}".format(float(count_within_range4/(len(hedges)))))
    print("count_larger_than_range4 = ", count_larger_than_range4, "{:.0%}".format(float(count_larger_than_range4/(len(hedges)))))
    print("count_smaller_than_range4 = ", count_smaller_than_range4, "{:.0%}".format(float(count_smaller_than_range4/(len(hedges)))))


    result2 = []
    result3 = []
    result4 = []
    for i in range(len(mtkahypar2)):
        mt2 = float(mtkahypar2[i])
        gh2 = float(ghypart2[i])
        bp2 = float(bipart2[i])
        if float(mtkahypar2[i]) == 0:
            mt2 = 1
        if float(ghypart2[i]) == 0:
            gh2 = 1
        if float(bipart2[i]) == 0:
            bp2 = 1
        result2.append(mt2 / bp2)
        
        mt3 = float(mtkahypar3[i])
        gh3 = float(ghypart3[i])
        bp3 = float(bipart3[i])
        if float(mtkahypar3[i]) == 0:
            mt3 = 1
        if float(ghypart3[i]) == 0:
            gh3 = 1
        if float(bipart3[i]) == 0:
            bp3 = 1
        result3.append(mt3 / bp3)
        
        mt4 = float(mtkahypar4[i])
        gh4 = float(ghypart4[i])
        bp4 = float(bipart4[i])
        if float(mtkahypar4[i]) == 0:
            mt4 = 1
        if float(ghypart4[i]) == 0:
            gh4 = 1
        if float(bipart4[i]) == 0:
            bp4 = 1
        result4.append(mt4 / bp4)

    y_mt2 = gmean(result2)
    y_mt3 = gmean(result3)
    y_mt4 = gmean(result4)

    # print("gHyPart vs MtKaHyPar-RB")
    # # print(mt_rb_2, ghypart2)
    # diff2 = (mt_rb_2 - ghypart2) / hedges
    # count_within_range2 = (abs(diff2) <= 0.005).sum()
    # count_larger_than_range2 = (diff2 > 0.005).sum()
    # count_smaller_than_range2 = (diff2 < -0.005).sum()
    # print("count_within_range2 = ", count_within_range2, "{:.0%}".format(float(count_within_range2/(len(hedges)))))
    # print("count_larger_than_range2 = ", count_larger_than_range2, "{:.0%}".format(float(count_larger_than_range2/(len(hedges)))))
    # print("count_smaller_than_range2 = ", count_smaller_than_range2, "{:.0%}".format(float(count_smaller_than_range2/(len(hedges)))))
    
    # diff3 = (mt_rb_3 - ghypart3) / hedges
    # count_within_range3 = (abs(diff3) <= 0.005).sum()
    # count_larger_than_range3 = (diff3 > 0.005).sum()
    # count_smaller_than_range3 = (diff3 < -0.005).sum()
    # print("count_within_range3 = ", count_within_range3, "{:.0%}".format(float(count_within_range3/(len(hedges)))))
    # print("count_larger_than_range3 = ", count_larger_than_range3, "{:.0%}".format(float(count_larger_than_range3/(len(hedges)))))
    # print("count_smaller_than_range3 = ", count_smaller_than_range3, "{:.0%}".format(float(count_smaller_than_range3/(len(hedges)))))
    
    # diff4 = (mt_rb_4 - ghypart4) / hedges
    # count_within_range4 = (abs(diff4) <= 0.005).sum()
    # count_larger_than_range4 = (diff4 > 0.005).sum()
    # count_smaller_than_range4 = (diff4 < -0.005).sum()
    # print("count_within_range4 = ", count_within_range4, "{:.0%}".format(float(count_within_range4/(len(hedges)))))
    # print("count_larger_than_range4 = ", count_larger_than_range4, "{:.0%}".format(float(count_larger_than_range4/(len(hedges)))))
    # print("count_smaller_than_range4 = ", count_smaller_than_range4, "{:.0%}".format(float(count_smaller_than_range4/(len(hedges)))))

    print(hedges)
    print("gHyPart vs. hMetis")
    float_positions = []
    float_values = []
    for index, value in enumerate(hmetis2):
        try:
            float_value = float(value)
            if float_value > 0:
                float_positions.append(index)
                float_values.append(float_value)
        except ValueError:
            pass

    # 打印出浮点数的位置和值
    # print("浮点数位置：", float_positions, len(float_positions))
    # print("浮点数值：", float_values, len(float_values))
    print(len(float_positions), len(float_values))
    
    worse_than_hm_num = 0
    comparable_with_hm = 0
    better_than_hm_num = 0
    diff2 = []
    for i in range(len(float_positions)):
        pos = float_positions[i]
        diff = (float(hmetis2[pos]) - float(ghypart2[pos])) / hedges[pos]
        if float(hmetis2[pos]) == 0 or float(ghypart2[pos]) == 0:
            print(f"{dataset[pos]}: {hmetis2[pos]}, {ghypart2[pos]}")
        gh2 = float(ghypart2[pos])
        if float(ghypart2[pos]) == 0:
            gh2 = 1
        bp2 = float(bipart2[pos])
        if float(bipart2[pos]) == 0:
            bp2 = 1
        diff2.append(float(hmetis2[pos]) / bp2)
        if float(diff) < -0.005:
            worse_than_hm_num+=1
        if float(diff) > 0.005:
            better_than_hm_num+=1
        if float(diff) >= -0.005 and float(diff) <= 0.005:
            comparable_with_hm+=1
    print(worse_than_hm_num, "{:.0%}".format(float(worse_than_hm_num/(len(float_positions)))))
    print(comparable_with_hm, "{:.0%}".format(float(comparable_with_hm/(len(float_positions)))))
    print(better_than_hm_num, "{:.0%}".format(float(better_than_hm_num/(len(float_positions)))))
    
    
    float_positions = []
    float_values = []
    for index, value in enumerate(hmetis3):
        try:
            float_value = float(value)
            if float_value > 0:
                float_positions.append(index)
                float_values.append(float_value)
        except ValueError:
            pass

    # 打印出浮点数的位置和值
    # print("浮点数位置：", float_positions, len(float_positions))
    # print("浮点数值：", float_values, len(float_values))
    print(len(float_positions), len(float_values))
    
    worse_than_hm_num = 0
    comparable_with_hm = 0
    better_than_hm_num = 0
    diff3 = []
    for i in range(len(float_positions)):
        pos = float_positions[i]
        diff = (float(hmetis3[pos]) - float(ghypart3[pos])) / hedges[pos]
        gh3 = float(ghypart3[pos])
        if float(ghypart3[pos]) == 0:
            gh3 = 1
        bp3 = float(bipart3[pos])
        if float(bipart3[pos]) == 0:
            bp3 = 1
        diff3.append(float(hmetis3[pos]) / bp3)
        if float(diff) < -0.005:
            worse_than_hm_num+=1
        if float(diff) > 0.005:
            better_than_hm_num+=1
        if float(diff) >= -0.005 and float(diff) <= 0.005:
            comparable_with_hm+=1
    print(worse_than_hm_num, "{:.0%}".format(float(worse_than_hm_num/(len(float_positions)))))
    print(comparable_with_hm, "{:.0%}".format(float(comparable_with_hm/(len(float_positions)))))
    print(better_than_hm_num, "{:.0%}".format(float(better_than_hm_num/(len(float_positions)))))
    
    float_positions = []
    float_values = []
    for index, value in enumerate(hmetis4):
        try:
            float_value = float(value)
            if float_value > 0:
                float_positions.append(index)
                float_values.append(float_value)
        except ValueError:
            pass

    # 打印出浮点数的位置和值
    # print("浮点数位置：", float_positions, len(float_positions))
    # print("浮点数值：", float_values, len(float_values))
    print(len(float_positions), len(float_values))
    
    worse_than_hm_num = 0
    comparable_with_hm = 0
    better_than_hm_num = 0
    diff4 = []
    for i in range(len(float_positions)):
        pos = float_positions[i]
        diff = (float(hmetis4[pos]) - float(ghypart4[pos])) / hedges[pos]
        gh4 = float(ghypart4[pos])
        if float(ghypart4[pos]) == 0:
            gh4 = 1
        bp4 = float(bipart4[pos])
        if float(bipart4[pos]) == 0:
            bp4 = 1
        diff4.append(float(hmetis4[pos]) / bp4)
        if float(diff) < -0.005:
            # print(f"{dataset[pos]}: {hmetis4[pos]}, {ghypart4[pos]}, {diff}")
            worse_than_hm_num+=1
        if float(diff) > 0.005:
            better_than_hm_num+=1
        if float(diff) >= -0.005 and float(diff) <= 0.005:
            comparable_with_hm+=1
    print(worse_than_hm_num, "{:.0%}".format(float(worse_than_hm_num/(len(float_positions)))))
    print(comparable_with_hm, "{:.0%}".format(float(comparable_with_hm/(len(float_positions)))))
    print(better_than_hm_num, "{:.0%}".format(float(better_than_hm_num/(len(float_positions)))))

    y_hm2 = gmean(diff2)
    y_hm3 = gmean(diff3)
    y_hm4 = gmean(diff4)
    # print(diff2)
    
    print(y_bp2, y_bp3, y_bp4, y_mt2, y_mt3, y_mt4, y_hm2, y_hm3, y_hm4)
    
'''
    plt.rcParams['font.weight'] = 'bold'
    plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['legend.fontsize'] = 32
    plt.rcParams['legend.frameon'] =  True

    fig, ax = plt.subplots(figsize=(25, 10))
    # ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
    ax.set_ylim(0, 1.5)  # 设置纵坐标起始值为0
    # ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    # ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    ax.tick_params(axis='y', which='major', labelsize=48)
    ax.set_ylabel('Normalized EdgeCut\n over BiPart', va='center', fontsize=50, fontweight='bold', labelpad=60)  # 设置纵坐标title
    ax.set_xlabel('', va='center', fontsize=40, fontweight='bold', labelpad=40)
    
    ax.set_xlim(0, 10)
    x_positions = [1.3, 5.1, 8.8]
    x_labels = ['k=2', 'k=3', 'k=4']
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)

    width = .5
    bar1 = ax.bar(2*0+.5, 1, width=width, label='BiPart', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*0+1, y_hm2, width=width, label='hMetis', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*0+1.5, y_mt2, width=width, label='Mt-KaHyPar', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*0+2, y_bp2, width=width, label='ɢHʏPᴀʀᴛ', edgecolor='black', color=colors[6], hatch='\\')
    
    bar1 = ax.bar(2*2+.3, 1, width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*2+.8, y_hm3, width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*2+1.3, y_mt3, width=width, label='', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*2+1.8, y_bp3, width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    
    bar1 = ax.bar(2*4+.0, 1, width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*4+.5, y_hm4, width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*4+1.0, y_mt4, width=width, label='', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*4+1.5, y_bp4, width=width, label='', edgecolor='black', color=colors[6], hatch='\\')

    ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')

    last_value1 = 1
    last_value2 = y_hm2
    last_value3 = y_mt2
    last_value4 = y_bp2
    last_value5 = 1
    last_value6 = y_hm3
    last_value7 = y_mt3
    last_value8 = y_bp3
    last_value9 = 1
    last_value10 = y_hm4
    last_value11 = y_mt4
    last_value12 = y_bp4
    print(last_value10)
    ax.text(2*0+.5, last_value1 + 0.1, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1, last_value2 + .0, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1.5, last_value3 + 0.1, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*0+2, last_value4 + 0.1, "[{:.2f}]".format(last_value4), color=colors[6], ha='center', fontsize=35, rotation=0)
    ax.text(2*2+.3, last_value5 + 0.1, "[{:.2f}]".format(last_value5), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*2+.8, last_value6 + .1, "[{:.2f}]".format(last_value6), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*2+1.3, last_value7 + 0.1, "[{:.2f}]".format(last_value7), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*2+1.8, last_value8 + 0.1, "[{:.2f}]".format(last_value8), color=colors[6], ha='center', fontsize=35, rotation=0)
    ax.text(2*4-.0, last_value9 + 0.1, "[{:.2f}]".format(last_value9), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*4+.5, last_value10 + .1, "[{:.2f}]".format(last_value10), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*4+1.0, last_value11 + 0.1, "[{:.2f}]".format(last_value11), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*4+1.5, last_value12 + 0.1, "[{:.2f}]".format(last_value12), color=colors[6], ha='center', fontsize=35, rotation=0)
    
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles, labels, bbox_to_anchor=(0.5, 0.93), loc='center', ncol=4, fontsize=35, frameon=True)
    frame = legend.get_frame()
    frame.set_edgecolor('#808080')  # 设置边框颜色
    frame.set_linewidth(2)  # 设置边框粗细
    frame.set_alpha(1)  # 设置边框透明度

    spines = ax.spines
    spines['top'].set_linewidth(5)
    spines['bottom'].set_linewidth(5)
    spines['left'].set_linewidth(5)
    spines['right'].set_linewidth(5)

    # 调整布局以适应标签
    plt.tight_layout()

    # output = f"work_quality_comp_all_{current_date}.pdf"
    output = f"work_quality_comp_all_2024-10-25.pdf"
    # 保存图片
    plt.savefig(output, dpi=300, bbox_inches='tight')

    # 显示图形  
    plt.show()
'''



if __name__ == '__main__':
    quality_comp_all_works()