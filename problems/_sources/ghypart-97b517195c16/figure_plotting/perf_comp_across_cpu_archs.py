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
import plot_perf_comparisons as ppc

current_date = datetime.date.today()

file = 'results/works_all_comp_3090_2024-01-08.csv'
file9 = 'results/bipart_perf_xeon_13900K_t24_2024-10-25.csv'
file10 = 'results/mtkahypar_perf_xeon_13900K_t24_direct_2024-10-25.csv'

data = pd.read_csv(file)
data4 = pd.read_csv(file9) # bipart_perf_xeon_13900K_t24_2024-10-25.csv
data5 = pd.read_csv(file10) # mtkahypar_perf_xeon_13900K_t24_direct_2024-10-25.csv

data_othercpu3 = pd.read_csv('results/bipart_perf_xeon_8358P_32cores_t32.csv')
data_othercpu4 = pd.read_csv('results/mtkahypar_perf_xeon_8358P_64cores_t64.csv')
data_othercpu5 = pd.read_csv('results/mtkahypar_perf_xeon_8358P_32cores_t32.csv')

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", 
          "#800080", "#ffc0cb", "#ffa500", "#808080", 
          "#007fff", "#8e52dc", "#ff7f50", "#ff4500", 
          "#396e04", "#ff00ff", "#ff69b4", "#489177"]


def perf_comp_all_with_highend_cpu_new():
    data = pd.read_csv(file)
    data = data.iloc[:-1]
    merged_data = pd.merge(data, data4, on='dataset')
    merged_data = pd.merge(merged_data, data5, on='dataset')
    merged_data = pd.merge(merged_data, data_othercpu3, on='dataset')
    # merged_data = pd.merge(merged_data, data_othercpu4, on='dataset')
    print(merged_data)
    
    
    # merged_data['g_ratio'] = merged_data['BiPart'] / merged_data['gHyPart']
    # merged_data = merged_data.sort_values(by='g_ratio')
    y1 = merged_data['BiPart']
    y2 = merged_data['Mt-KaHyPar-SDet']
    y3 = merged_data['k=2_x'] # bipart-13900k
    y4 = merged_data['k=2_y'] # mt-kahypar-13900k
    y5 = merged_data['gHyPart']
    y6 = data_othercpu3['k=2']
    # y7 = data_othercpu4['k=2']
    y7 = data_othercpu5['k=2']
    
    print(gmean(y1/y1), gmean(y1/y2), gmean(y1/y3), gmean(y1/y4), gmean(y1/y5))
    print(gmean(y1/data_othercpu3['k=2']))
    print(gmean(y1/data_othercpu4['k=2']))
    print(gmean(y1/data_othercpu5['k=2']))

    plt.rcParams['font.weight'] = 'bold'
    plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['legend.fontsize'] = 25
    plt.rcParams['legend.frameon'] =  True

    fig, ax = plt.subplots(figsize=(18, 7))
    ylim = 100
    ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
    ax.set_ylim(0, ylim)  # 设置纵坐标起始值为0
    ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    # ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    ax.tick_params(axis='y', which='major', labelsize=40)
    ax.set_ylabel('Speedup over BiPart\n on 4214R', va='center', fontsize=40, fontweight='bold', labelpad=45)  # 设置纵坐标title
    ax.set_xlabel('', va='center', fontsize=40, fontweight='bold', labelpad=40)
    
    ax.set_xlim(0, 7.8)
    x_positions = [1.0, 3.0, 5.0, 7.0]
    x_labels = ['4214R', 'I9', '8358P', 'RTX3090']
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)
    
    width = .5
    bar1 = ax.bar(2*0+.75, gmean(y1/y1), width=width, label='BiPart', edgecolor='black', color="#396e04", hatch='//')
    bar2 = ax.bar(2*0+1.25, gmean(y1/y2), width=width, label='Mt-KaHyPar', edgecolor='black', color=colors[6], hatch='\\')
    
    bar3 = ax.bar(2*1+.75, gmean(y1/y3), width=width, label='', edgecolor='black', color="#396e04", hatch='//')
    bar4 = ax.bar(2*1+1.25, gmean(y1/y4), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    
    bar3 = ax.bar(2*2+0.75, gmean(y1/y6), width=width, label='', edgecolor='black', color="#396e04", hatch='//')
    bar4 = ax.bar(2*2+1.25, gmean(y1/y7), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    
    bar4 = ax.bar(7, gmean(y1/y5), width=width, label='ɢHʏPᴀʀᴛ', edgecolor='black', color=colors[0], hatch='.')
    
    ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')
    
    last_value1 = gmean(y1/y1)
    last_value2 = gmean(y1/y2)
    last_value3 = gmean(y1/y3)
    last_value4 = gmean(y1/y4)
    last_value5 = gmean(y1/y5)
    last_value6 = gmean(y1/y6)
    last_value7 = gmean(y1/y7)
    
    ax.text(2*0+.75, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#396e04", ha='center', fontsize=25, rotation=0)
    ax.text(2*0+1.25+.05, last_value2 + .1, "[{:.2f}]".format(last_value2), color=colors[6], ha='center', fontsize=25, rotation=0)
    ax.text(2*1+.75-.05, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=25, rotation=0)
    ax.text(2*1+1.25+.05, last_value4 + .2, "[{:.2f}]".format(last_value4), color=colors[6], ha='center', fontsize=25, rotation=0)
    ax.text(2*2+.75-0.05, last_value6 + 0.1, "[{:.2f}]".format(last_value6), color="#396e04", ha='center', fontsize=25, rotation=0)
    ax.text(2*2+1.25, last_value7 + .3, "[{:.2f}]".format(last_value7), color=colors[6], ha='center', fontsize=25, rotation=0)
    ax.text(7, last_value5 + 1.5, "[{:.2f}]".format(last_value5), color=colors[0], ha='center', fontsize=25, rotation=0)
    
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles, labels, bbox_to_anchor=(0.5, 0.93), loc='center', ncol=4, fontsize=25, frameon=True)
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

    output = f'results/work_comp_all_with_highend_cpu_{current_date}.pdf'
    # 保存图片
    plt.savefig(output, dpi=300, bbox_inches='tight')

    # 显示图形  
    plt.show()
    


if __name__ == '__main__':

    perf_comp_all_with_highend_cpu_new()
    