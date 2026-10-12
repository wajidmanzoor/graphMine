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


def perf_comp_all_across_benchmarks():
    data = pd.read_csv(file)
    data = data.iloc[:-1]
    print(data)
    
    sat = data[data['dataset'].str.contains('sat', case=False, na=False)]
    ispd = data[data['dataset'].str.contains('ibm', case=False, na=False)]
    dac = data[data['dataset'].str.contains('dac', case=False, na=False)]
    matrix = data[~data.index.isin(sat.index) & ~data.index.isin(ispd.index) & ~data.index.isin(dac.index)]
    print("Number of rows in 'sat' table:", sat.shape[0])
    print("Number of rows in 'ispd' table:", ispd.shape[0])
    print("Number of rows in 'dac' table:", dac.shape[0])
    print("Number of rows in 'matrix' table:", matrix.shape[0])
    
    sat_bp = sat['BiPart']
    sat_mt = sat['Mt-KaHyPar-SDet']
    sat_gh = sat['gHyPart']
    
    ispd_bp = ispd['BiPart']
    ispd_mt = ispd['Mt-KaHyPar-SDet']
    ispd_gh = ispd['gHyPart']
    
    dac_bp = dac['BiPart']
    dac_mt = dac['Mt-KaHyPar-SDet']
    dac_gh = dac['gHyPart']
    
    matrix_bp = matrix['BiPart']
    matrix_mt = matrix['Mt-KaHyPar-SDet']
    matrix_gh = matrix['gHyPart']
    
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
    x_positions = [1.0, 3.3, 5.5, 8.2]
    x_labels = ['SAT2014 (276)', 'ISPD98 (18)', 'DAC2012 (10)', 'Sparse Matrix Collection (196)']
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    ax.tick_params(axis='x', which='major', labelsize=30, rotation=0)
    
    width = .5
    bar1 = ax.bar(2*0+.5, gmean(sat_bp/sat_bp), width=width, label='BiPart', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*0+1, gmean(sat_bp/sat_mt), width=width, label='Mt-KaHyPar', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*0+1.5, gmean(sat_bp/sat_gh), width=width, label='ɢHʏPᴀʀᴛ', edgecolor='black', color="#396e04", hatch='o')

    bar1 = ax.bar(2*2-1.2, gmean(ispd_bp/ispd_bp), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*2-0.7, gmean(ispd_bp/ispd_mt), width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*2-0.2, gmean(ispd_bp/ispd_gh), width=width, label='', edgecolor='black', color="#396e04", hatch='o')

    bar1 = ax.bar(2*3-1.0, gmean(dac_bp/dac_bp), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*3-.5, gmean(dac_bp/dac_mt), width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*3+0.0, gmean(dac_bp/dac_gh), width=width, label='', edgecolor='black', color="#396e04", hatch='o')

    bar1 = ax.bar(2*4-0.5, gmean(matrix_bp/matrix_bp), width=width, label='', edgecolor='black', color="#808080", hatch='//')
    bar2 = ax.bar(2*4+0.0, gmean(matrix_bp/matrix_mt), width=width, label='', edgecolor='black', color=colors[5], hatch='.')
    bar3 = ax.bar(2*4+0.5, gmean(matrix_bp/matrix_gh), width=width, label='', edgecolor='black', color="#396e04", hatch='o')

    last_value1 = gmean(sat_bp/sat_bp)
    last_value2 = gmean(sat_bp/sat_mt)
    last_value3 = gmean(sat_bp/sat_gh)
    ax.text(2*0+.5, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1, last_value2 + .1, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*0+1.5, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)

    last_value1 = gmean(ispd_bp/ispd_bp)
    last_value2 = gmean(ispd_bp/ispd_mt)
    last_value3 = gmean(ispd_bp/ispd_gh)
    ax.text(2*2-1.2, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*2-0.7, last_value2 + .1, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*2-0.2, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)
    
    last_value1 = gmean(dac_bp/dac_bp)
    last_value2 = gmean(dac_bp/dac_mt)
    last_value3 = gmean(dac_bp/dac_gh)
    ax.text(2*3-1.0, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*3-.5, last_value2 + .1, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*3+0.0, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)
    
    last_value1 = gmean(matrix_bp/matrix_bp)
    last_value2 = gmean(matrix_bp/matrix_mt)
    last_value3 = gmean(matrix_bp/matrix_gh)
    ax.text(2*4-0.5, last_value1 + 0.3, "[{:.2f}]".format(last_value1), color="#808080", ha='center', fontsize=35, rotation=0)
    ax.text(2*4+0.0, last_value2 + .1, "[{:.2f}]".format(last_value2), color=colors[5], ha='center', fontsize=35, rotation=0)
    ax.text(2*4+0.5, last_value3 + 0.3, "[{:.2f}]".format(last_value3), color="#396e04", ha='center', fontsize=35, rotation=0)

    ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')
    
    
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

    output = f"results/work_perf_comp_all_across_benchmarks_{current_date}.pdf"
    # 保存图片
    plt.savefig(output, dpi=300, bbox_inches='tight')

    # 显示图形  
    plt.show()




if __name__ == '__main__':
    
    perf_comp_all_across_benchmarks()
    