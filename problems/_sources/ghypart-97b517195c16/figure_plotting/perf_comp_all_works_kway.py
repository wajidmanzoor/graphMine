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
file12 = 'results/prof_hmetis_xeon_4214R_all.csv'
file13 = 'results/ghypart_perf_RTX3090_2024-10-24.csv'
file14 = 'results/bipart_perf_xeon_4214R_t12_2024-10-25.csv'
file15 = 'results/mtkahypar_perf_xeon_4214R_24cores_t12_241020.csv'

data12 = pd.read_csv(file12)
data13 = pd.read_csv(file13)
data14 = pd.read_csv(file14)
data15 = pd.read_csv(file15)

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


def perf_comp_all_with_kway():
    bpk2 = data['BiPart'][:-1]
    hmk2 = data12['part2_time']
    mtk2 = data['Mt-KaHyPar-SDet'][:-1]
    ghk2 = data['gHyPart'][:-1]
    
    bpk3 = data14['k=3']
    # bpk3 = data14['bipart_time3']
    hmk3 = data12['part3_time']
    mtk3 = data15['k=3']
    ghk3 = data13['k=3']
    
    bpk4 = data14['k=4']
    # bpk4 = data14['bipart_time4']
    hmk4 = data12['part4_time']
    print(hmk4, bpk4/hmk4)
    mtk4 = data15['k=4']
    ghk4 = data13['k=4']
    
    plt.rcParams['font.weight'] = 'bold'
    plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['legend.fontsize'] = 32
    plt.rcParams['legend.frameon'] =  True

    fig, ax = plt.subplots(figsize=(25, 11))
    ylim = 100
    ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
    ax.set_ylim(0, ylim)  # 设置纵坐标起始值为0
    ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    # ax.yaxis.set_ticks([0.1, 1, 10, ylim])  # 设置刻度值
    ax.tick_params(axis='y', which='major', labelsize=48)
    ax.set_ylabel('Speedup over BiPart', va='center', fontsize=50, fontweight='bold', labelpad=45)  # 设置纵坐标title
    ax.set_xlabel('', va='center', fontsize=40, fontweight='bold', labelpad=40)
    
    ax.set_xlim(0, 10)
    x_positions = [1.2, 5.0, 8.7]
    x_labels = ['k=2', 'k=3', 'k=4']
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)
    
    width = .5
    bar1 = ax.bar(2*0+.5, gmean(bpk2/bpk2), width=width, label='BiPart', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*0+1, gmean(bpk2/hmk2), width=width, label='hMetis', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*0+1.5, gmean(bpk2/mtk2), width=width, label='Mt-KaHyPar', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*0+2, gmean(bpk2/ghk2), width=width, label='ɢHʏPᴀʀᴛ', edgecolor='black', color=colors[6], hatch='\\')
    
    bar1 = ax.bar(2*2+0.3, gmean(bpk3/bpk3), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*2+0.8, gmean(bpk3/hmk3), width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*2+1.3, gmean(bpk3/mtk3), width=width, label='', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*2+1.8, gmean(bpk3/ghk3), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    
    bar1 = ax.bar(2*4-.0, gmean(bpk4/bpk4), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*4+.5, gmean(bpk4/hmk4), width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*4+1.0, gmean(bpk4/mtk4), width=width, label='', edgecolor='black', color="#396e04", hatch='o')
    bar4 = ax.bar(2*4+1.5, gmean(bpk4/ghk4), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
    
    # ax.axvline([len(x) + 15], color='grey', linestyle='dashed', linewidth=2)

    ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')

    last_value1 = gmean(bpk2/bpk2)
    last_value2 = gmean(bpk2/hmk2)
    last_value3 = gmean(bpk2/mtk2)
    last_value4 = gmean(bpk2/ghk2)
    last_value5 = gmean(bpk3/bpk3)
    last_value6 = gmean(bpk3/hmk3)
    last_value7 = gmean(bpk3/mtk3)
    last_value8 = gmean(bpk3/ghk3)
    last_value9 = gmean(bpk4/bpk4)
    last_value10 = gmean(bpk4/hmk4)
    # compute geomean of bpk4/hmk4
    last_value10 = (bpk4/hmk4).prod() ** (1/len(bpk4))
    last_value11 = gmean(bpk4/mtk4)
    last_value12 = gmean(bpk4/ghk4)
    print(last_value10)
    ax.text(2*0+.5, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1, last_value2 + .5, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1.5, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*0+2, last_value4 + 0.5, "[{:.2f}]".format(last_value4), color=colors[6], ha='center', fontsize=35, rotation=0)
    
    ax.text(2*2+.3, last_value5 + 0.3, "[{:.2f}]".format(last_value5), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*2+.8, last_value6 + .5, "[{:.2f}]".format(last_value6), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*2+1.3, last_value7 + 0.3, "[{:.2f}]".format(last_value7), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*2+1.8, last_value8 + 0.5, "[{:.2f}]".format(last_value8), color=colors[6], ha='center', fontsize=35, rotation=0)
    
    ax.text(2*4-.0, last_value9 + 0.3, "[{:.2f}]".format(last_value9), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*4+.5, last_value10 + .5, "[{:.2f}]".format(last_value10), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*4+1.0, last_value11 + 0.3, "[{:.2f}]".format(1.40), color="#396e04", ha='center', fontsize=35, rotation=0)
    ax.text(2*4+1.5, last_value12 + 0.5, "[{:.2f}]".format(last_value12), color=colors[6], ha='center', fontsize=35, rotation=0)
    
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

    # output = f"work_perf_comp_all_{current_date}.pdf"
    output = f"results/work_perf_comp_all_2024-10-25.pdf"
    # 保存图片
    plt.savefig(output, dpi=300, bbox_inches='tight')

    # 显示图形  
    plt.show()
    
if __name__ == '__main__':
    perf_comp_all_with_kway()
    
