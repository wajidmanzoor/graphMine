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

file = 'results/works_all_comp_3090_2024-01-08.csv'
file1 = 'results/bipart_perf_xeon_4214R_24cores_t12.csv'
file2 = 'results/mtkahypar_perf_xeon_4214R_24cores_t12.csv'
file11 = 'results/benchmarks_all_patterns_real_hypergraphs_liu3090_2024-10-20_new.csv'
file12 = 'results/prof_hmetis_xeon_4214R_all.csv'

data1 = pd.read_csv(file1)
data2 = pd.read_csv(file2)
data11 = pd.read_csv(file11)
data12 = pd.read_csv(file12)

data = pd.read_csv(file)
bipart_column = data.iloc[:-1, 1] # bipart
mtkaypar_column = data.iloc[:-1,3] # mtkahypar
ghypart_column = data.iloc[:-1,5] # gHyPart
gpubase_column = data.iloc[:-1,4] # gHyPart-B
# print(bipart_column, mtkaypar_column, ghypart_column)
print(bipart_column)

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", 
          "#800080", "#ffc0cb", "#ffa500", "#808080", 
          "#007fff", "#8e52dc", "#ff7f50", "#ff4500", 
          "#396e04", "#ff00ff", "#ff69b4", "#489177",
          "#CC99FF", "#FFCC99", "#99CCFF", "#CCFF99",]


def perf_comp_all_with_2way(k):
    last_three_columns = data2.iloc[:, -4:-1]
    last_three_columns.columns = ['mt_k2', 'mt_k3', 'mt_k4']
    # merged_data = pd.concat([data1, last_three_columns], axis=1)
    merged_data = pd.concat([data1, last_three_columns], axis=1)
    
    last_three_columns = data11['p1_k1235_p1_k4k6_p2_k12']
    # last_three_columns.columns = ['bp64_k2', 'bp64_k3', 'bp64_k4']
    merged_data = pd.concat([merged_data, last_three_columns], axis=1)
    
    last_three_columns = data11['gHyPart']
    # last_three_columns.columns = ['mt64_k2', 'mt64_k3', 'mt64_k4']
    merged_data = pd.concat([merged_data, last_three_columns], axis=1)
    
    last_three_columns = data11['best']
    # last_three_columns.columns = ['gp_k2', 'gp_k3', 'gp_k4']
    merged_data = pd.concat([merged_data, last_three_columns], axis=1)
    
    merged_data = pd.concat([merged_data, data12['part2_time']], axis=1)
    print(merged_data)
    
    if k == 2:
        y1 = merged_data['k=2']
        y2 = merged_data['mt_k2']
        # y3 = merged_data['gp_k2']
        y3 = merged_data['p1_k1235_p1_k4k6_p2_k12']
        y4 = merged_data['gHyPart']
        y5 = merged_data['best']
        y6 = merged_data['part2_time']
    # if k == 3:
    #     y1 = merged_data['k=3']
    #     y2 = merged_data['mt_k3']
    #     y3 = merged_data['gp_k3']
    # if k == 4:
    #     y1 = merged_data['k=4']
    #     y2 = merged_data['mt_k4']
    #     y3 = merged_data['gp_k4']
    
    # print(y1)
    # print(gmean(y1/y1), gmean(y1/y2), gmean(y1/y3), gmean(bipart_column/ghypart_column))
    # print(gmean(bipart_column/y1))
    # print(ghypart_column, y3)
    # print(gmean(data6['gHyPart']/y3), gmean(y1/data6['gHyPart']))
    # print(gmean(data6['p1_k1235_p1_k4k6_p2_k12']/gpubase_column))
    # print(gmean(merged_data['k=2']/data7['time_k=2']), 
    #       gmean(merged_data['k=3']/data7['time_k=3']), 
    #       gmean(merged_data['k=4']/data7['time_k=4']))
    # print(gmean(merged_data['k=2']/data8['time_k=2']),
    #       gmean(merged_data['k=3']/data8['time_k=3']),
    #       gmean(merged_data['k=4']/data8['time_k=4']))
    # print(gmean(merged_data['k=2']/data9['time_k=2']),
    #       gmean(merged_data['k=3']/data9['time_k=3']),
    #       gmean(merged_data['k=4']/data9['time_k=4']))
          
    # last_three_columns = data7.iloc[:, -7:-1]
    # merged_data = pd.concat([merged_data, last_three_columns], axis=1)
    # print(merged_data)
    
    if k == 2:
        merged_data['g_ratio'] = merged_data['k=2'] / merged_data['best']
        merged_data = merged_data.sort_values(by='g_ratio')
        y1 = merged_data['k=2']
        y2 = merged_data['mt_k2']
        # y3 = merged_data['bp64_k2']
        # y4 = merged_data['mt64_k2']
        # y6 = merged_data['time_k=2']
        y3 = merged_data['p1_k1235_p1_k4k6_p2_k12']
        y4 = merged_data['gHyPart']
        y5 = merged_data['best']
        y6 = merged_data['part2_time']
    # if k == 3:
    #     merged_data['g_ratio'] = merged_data['k=3'] / merged_data['time_k=3']
    #     merged_data = merged_data.sort_values(by='g_ratio')
    #     y1 = merged_data['k=3']
    #     y2 = merged_data['mt_k3']
    #     y3 = merged_data['bp64_k3']
    #     y4 = merged_data['mt64_k3']
    #     y6 = merged_data['time_k=3']
    # if k == 4:
    #     merged_data['g_ratio'] = merged_data['k=4'] / merged_data['time_k=4']
    #     merged_data = merged_data.sort_values(by='g_ratio')
    #     y1 = merged_data['k=4']
    #     y2 = merged_data['mt_k4']
    #     y3 = merged_data['bp64_k4']
    #     y4 = merged_data['mt64_k4']
    #     y6 = merged_data['time_k=4']
    
    merged_data = pd.concat([data, data12['part2_time']], axis=1)
    merged_data['g_ratio'] = merged_data['BiPart'] / merged_data['best']
    merged_data = merged_data.sort_values(by='g_ratio')
    y1 = merged_data['BiPart'][:-1]
    y6 = merged_data['part2_time'][:-1]
    y2 = merged_data['Mt-KaHyPar-SDet'][:-1]
    y3 = merged_data['gHyPart-B'][:-1]
    y4 = merged_data['gHyPart'][:-1]
    y5 = merged_data['best'][:-1]
    
    x = merged_data.iloc[:-1,0]
    index_list = range(len(x))
    print(merged_data, index_list)
    
    plt.rcParams['font.weight'] = 'bold'
    plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['legend.fontsize'] = 32
    plt.rcParams['legend.frameon'] =  True

    fig, ax = plt.subplots(figsize=(30, 11))
    ylim = 100
    ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
    ax.set_ylim(0, ylim)  # 设置纵坐标起始值为0
    ax.yaxis.set_ticks([0.1, 1, 10, 100, 1000, ylim])  # 设置刻度值
    # ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    ax.tick_params(axis='y', which='major', labelsize=48)
    ax.set_ylabel('Speedup over BiPart', va='center', fontsize=60, fontweight='bold', labelpad=45)  # 设置纵坐标title
    ax.set_xlabel('Hypergraphs', va='center', fontsize=60, fontweight='bold', labelpad=40)
    
    xlim = 580
    # xlim = 2.2
    # ax.set_xlim(0,len(x)+1)
    ax.set_xlim(0, xlim)
    app_ticks = [0, 100, 200, 300, 400, len(x)-1, 505]
    ax.xaxis.set_ticks([0, 100, 200, 300, 400, len(x)-1])
    ax.tick_params(axis='x', which='major', labelsize=50, rotation=0)
    
    dot1 = ax.plot(index_list, y1/y1, marker='+', linestyle='-', label='BiPart', color="#808080", linewidth=5)
    dot6 = ax.plot(index_list, y1/y6, marker='o', markersize=6, linestyle='-', label='hMetis', color=colors[16], linewidth=5)
    dot2 = ax.plot(index_list, y1/y2, marker='*', markersize=12, linestyle='-', label='Mt-KaHyPar', color="#396e04", linewidth=3)
    dot3 = ax.plot(index_list, y1/y3, marker='x', linestyle='-', label='ɢHʏPᴀʀᴛ-B', color=colors[6], linewidth=5)
    dot4 = ax.plot(index_list, y1/y4, marker='^', markersize=6, linestyle='-', label='ɢHʏPᴀʀᴛ', color=colors[8], linewidth=5)
    dot5 = ax.plot(index_list, y1/y5, marker='o', markersize=6, linestyle='-', label='ɢHʏPᴀʀᴛ-O', color=colors[0], linewidth=5)
    
    last_center = 540
    bar1_pos = last_center - 14
    bar2_pos = last_center - 5
    bar3_pos = last_center + 4
    bar4_pos = last_center + 13
    bar5_pos = last_center + 22
    bar6_pos = last_center + 31
    width = 8
    bar1 = ax.bar(bar1_pos, gmean(y1/y1), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar6 = ax.bar(bar2_pos, gmean(y1/y6), width=width, label='', edgecolor='black', color=colors[16], hatch='.')
    bar2 = ax.bar(bar3_pos, gmean(y1/y2), width=width, label='', edgecolor='black', color="#396e04", hatch='.')
    bar3 = ax.bar(bar4_pos, gmean(y1/y3), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    bar4 = ax.bar(bar5_pos, gmean(y1/y4), width=width, label='', edgecolor='black', color=colors[8], hatch='o')
    bar5 = ax.bar(bar6_pos, gmean(y1/y5), width=width, label='', edgecolor='black', color=colors[0], hatch='x')
    
    ax.axvline([len(x) + 15], color='grey', linestyle='dashed', linewidth=2)

    ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')
        
    last_label_pos = 550
    xticks = list(ax.get_xticks()) + [last_label_pos]
    xticklabels = list(ax.get_xticklabels()) + ['GMean']
    ax.set_xticks(xticks)
    ax.set_xticklabels(xticklabels)

    xtick_labels = ax.get_xticklabels()
    # 设置最后一个xtick label的大小、角度和颜色
    last_xtick_label = xtick_labels[-1]
    last_xtick_label.set_fontsize(50)
    last_xtick_label.set_rotation(0)

    last_value1 = gmean(y1/y1)
    last_value2 = gmean(y1/y6)
    last_value3 = gmean(y1/y2)
    last_value4 = gmean(y1/y3)
    last_value5 = gmean(y1/y4)
    last_value6 = gmean(y1/y5)
    ax.text(bar1_pos, last_value1 + 0.5, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=90)
    ax.text(bar2_pos, gmean(y1/y6) + .5, "[{:.2f}]".format(gmean(y1/y6)), color=colors[16], ha='center', fontsize=35, rotation=90)
    ax.text(bar3_pos+0.5, last_value3 + 0.5, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=90)
    ax.text(bar4_pos-.5, last_value4 + 5, "[{:.2f}]".format(last_value4), color=colors[6], ha='center', fontsize=35, rotation=90)
    ax.text(bar5_pos+0.5, last_value5 + 6, "[{:.2f}]".format(last_value5), color=colors[8], ha='center', fontsize=35, rotation=90)
    ax.text(bar6_pos+0.5, last_value6 + 7, "[{:.2f}]".format(last_value6), color=colors[0], ha='center', fontsize=35, rotation=90)
    
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles, labels, bbox_to_anchor=(0.45, 0.88), loc='center', ncol=3, fontsize=35, frameon=True)
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

    # output = f"work_comp_all_{k}way_using_4214R_cpu_and_3090_gpu_{current_date}.pdf"
    # output = f"work_comp_all_{k}way_using_4214R_cpu_and_4090_gpu_{current_date}.pdf"
    output = f'results/work_comp_all_2way_using_4214R_cpu_and_3090_gpu_2024-10-25.pdf'

    # 保存图片
    plt.savefig(output, dpi=300, bbox_inches='tight')

    # 显示图形  
    plt.show()



if __name__ == '__main__':
    perf_comp_all_with_2way(2)
    
