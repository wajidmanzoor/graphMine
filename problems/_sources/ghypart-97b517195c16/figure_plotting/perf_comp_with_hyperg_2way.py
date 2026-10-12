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
import matplotlib.patches as patches

current_date = datetime.date.today()

file = 'results/perf_comp_with_hyperg_2way.csv'


data = pd.read_csv(file)
print(data)
x = data['benchmarks']
y0 = data['HyperG_A6000']
y1 = data['perf. over HyperG']


colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", 
          "#800080", "#ffc0cb", "#ffa500", "#808080", 
          "#007fff", "#8e52dc", "#ff7f50", "#ff4500", 
          "#396e04", "#ff00ff", "#ff69b4", "#489177",
          "#CC99FF", "#FFCC99", "#99CCFF", "#CCFF99",
          "#a98ec6", "#f9dd7e"]

mycolors = ['#014F9C', '#3C79B4', '#78A3CC', '#B3CDE4', '#EEF7FC', '#065AAB']

colorsuite = ["#3376b0", "#498dbd", "#68a4cd", 
              "#88bddb", "#aed7e9", "#d1eff7",
              "#8ab9dd", "#b0cfe9", "#d6e5f5"]


blue_gradient = ["#104498", "#104fb9", "#1062ec", "#157cf5", "#2499f8", 
                 "#44bcf9", "#7ad6fd", "#ade5fe", "#d0edff", "#ebfaff"]


width = .8
plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] = 36
plt.rcParams['legend.frameon'] =  True

bench_num = len(x) - 1
gmean0 = gmean(y0[:-1] / y0[:-1])
# gmean1 = gmean(y1[:-1])
gmean1 = float(y1.iloc[-1])


def perf_comp_with_hyperg_2way():
    fig, ax1 = plt.subplots(figsize=(20, 7))

    ax1.set_yscale('log', base=10)
    ax1.set_ylim(0, 1000)
    # ax1.set_ylim(0, 4)
    ax1.yaxis.set_ticks([0.1, 1, 10, 100, 1000])
    # ax1.yaxis.set_ticks([0, 5, 10, 15])
    ax1.tick_params(axis='y', which='major', labelsize=30)
    ax1.set_ylabel('Speedup over HyperG', va='center', fontsize=30, fontweight='bold', labelpad=60)

    ax1.set_xlabel('', va='center', fontsize=40, fontweight='bold', labelpad=30)
    # ax1.xaxis.set_ticks([])
    # ax1.set_xlim(-1.0 * width + .3, (len(x) - 0)*2 - width + .3)
    ax1.set_xlim(0-width*2, len(x) * 2 + width)
    ax1.set_xticks(ticks=[i*2+.1 for i in range(len(x)-1)], rotation=30, fontsize=28, labels=x[:-1], fontweight='bold')
# ᴀᴜᴛᴏᴍᴀᴛᴀBLAS-best
    ax1.bar(x=[i*2-.4 for i in range(len(x)-1)], height = y0[:-1]/y0[:-1], bottom=0, capsize=4, color=blue_gradient[5], 
            edgecolor='black', alpha=1, width=width, hatch='.', label='HyperG-A6000')
    ax1.bar(x=[i*2+.5 for i in range(len(x)-1)], height = y1[:-1], bottom=0, capsize=4, color=colors[6], linewidth=2, 
            edgecolor='black', alpha=1, width=width, hatch='.', label='ɢHʏPᴀʀᴛ-RTX3090')
    # ax1.bar(x=[i*8-2 for i in range(len(x)-1)], height = y2[:-1], bottom=0, capsize=4, color=colorsuite[3], linewidth=2, 
    #         edgecolor='black', alpha=1, width=width, hatch='.', label='NFA-CG')
    # super_1 = str(1).translate(superscript_mapping)
    # super_2 = str(2).translate(superscript_mapping)
    # super_3 = str(3).translate(superscript_mapping)
    # ax1.bar(x=[i*8-1 for i in range(len(x)-1)], height = y3[:-1], bottom=0, capsize=4, color=colorsuite[1], linewidth=2, 
    #         edgecolor='black', alpha=1, width=width, hatch='.', label=f'ngAP')
    # ax1.bar(x=[i*8-0 for i in range(len(x)-1)], height = y4[:-1], bottom=0, capsize=4, color=mycolors[5], linewidth=2, 
    #         edgecolor='black', alpha=1, width=width, hatch='.', label=f'ᴀᴜᴛᴏᴍᴀᴛᴀBLAS-best')
    # ax1.bar(x=[i*8+0 for i in range(len(x)-1)], height = y5[:-1], bottom=0, capsize=4, color=colorsuite[1], linewidth=2, 
    #         edgecolor='black', alpha=1, width=width, hatch='.', label=f'ᴀᴜᴛᴏᴍᴀᴛᴀBLAS-O{super_1}O{super_2}')
    # ax1.bar(x=[i*8+1 for i in range(len(x)-1)], height = y6[:-1], bottom=0, capsize=4, color=mycolors[0], linewidth=2, 
    #         edgecolor='black', alpha=1, width=width, hatch='.', label=f'ᴀᴜᴛᴏᴍᴀᴛᴀBLAS-O{super_1}O{super_2}O{super_3}')
    ax1.axvline([len(x) * 2 - 2.5], color='grey', linestyle='dashed', linewidth=2)
    
    ax1.bar(bench_num*2+.7, gmean0, bottom=0, capsize=4, color=blue_gradient[5], linewidth=2, edgecolor='black', 
                                                                        alpha=1, width=width, hatch='.', label='')
    ax1.bar(bench_num*2+1.6, gmean1, bottom=0, capsize=4, color=colors[6], linewidth=2, edgecolor='black', 
                                                                        alpha=1, width=width, hatch='.', label='')
    # ax1.bar(bench_num*8+2.3, gmean2, bottom=0, capsize=4, color=colorsuite[2], linewidth=2, edgecolor='black', 
    #                                                                     alpha=1, width=width, hatch='.', label='')
    # ax1.bar(bench_num*8+2.3, gmean3, bottom=0, capsize=4, color=colorsuite[1], linewidth=2, edgecolor='black', 
    #                                                                     alpha=1, width=width, hatch='.', label='')
    # ax1.bar(bench_num*8+3.4, gmean4, bottom=0, capsize=4, color=mycolors[5], linewidth=2, edgecolor='black', 
    #                                                                     alpha=1, width=width, hatch='.', label='')
    # ax1.bar(bench_num*8+5.6, gmean6, bottom=0, capsize=4, color=mycolors[0], linewidth=2, edgecolor='black', alpha=1,
    #                                                                             width=width, hatch='//', label='')
    last_value0 = gmean0
    last_value1 = gmean1
    # last_value2 = gmean2
    print("last_value1: ", last_value1)
    last_label_pos1 = bench_num*2 + 0.7
    last_label_pos2 = bench_num*2 + 1.6
    last_label_pos3 = bench_num*8 + 2.3
    last_label_pos4 = bench_num*8 + 2.3
    last_label_pos5 = bench_num*8 + 3.4
    # last_label_pos6 = bench_num*8 + 5.6

    # max_value = y4.iloc[:-1].max()
    # max_index = y4.iloc[:-1].tolist().index(max_value)
    # ax1.text(max_index*8-1, 6.6+.5, "{:.1f}".format(max_value), color='red', ha='center', 
    #                                                             fontsize=20, fontweight='bold', rotation=0)
    current_ylim = plt.gca().get_ylim()
    print("当前的y轴范围 (ylim):", current_ylim)
    # for i, v in enumerate(y1):
    #     if v > current_ylim[1]:
    #         ax1.text(i*8-2.5, current_ylim[1] + 10, "{:.1f}".format(v), ha='center', fontsize=20, fontweight='bold')
    # for i, v in enumerate(y3):
    #     if v > current_ylim[1]:
    #         # ax1.text(i*8+0.0, current_ylim[1] + .1, "{:.1f}".format(v), ha='center', fontsize=20, fontweight='bold')
    #         ax1.text(i*8+2.0, current_ylim[1] + .05, "{:.1f}".format(v), ha='center', va='bottom', color='black', 
    #                  fontsize=20, fontweight='bold', bbox=dict(facecolor='white', edgecolor='black', boxstyle='round,pad=0.3'))

    ax1.text(last_label_pos1-.1, last_value0+.2, "{:.1f}".format(last_value0), color='black', ha='center', 
                                                                fontsize=20, fontweight='bold', rotation=0)
    ax1.text(last_label_pos2-.0, last_value1+50, "{:.1f}".format(last_value1), color='black', ha='center',
                                                                fontsize=20, fontweight='bold', rotation=0)
    # ax1.text(last_label_pos3+.1, gmean2+1, "{:.1f}".format(gmean2), color='black', ha='center',
    #                                                             fontsize=20, fontweight='bold', rotation=90)
    # ax1.text(last_label_pos4, gmean3+.2, "{:.1f}".format(gmean3), color='black', ha='center',
    #                                                             fontsize=20, fontweight='bold', rotation=90)
    # ax1.text(last_label_pos5+.5, gmean4+.2, "{:.1f}".format(gmean4), color='red', ha='center',
    #                                                             fontsize=20, fontweight='bold', rotation=90)
    # ax1.text(last_label_pos6+.2, gmean6+100, "{:.1f}".format(gmean6), color='black', ha='center',
    #                                                             fontsize=20, fontweight='bold', rotation=90)
    
    ax1.axhline([1], color='red', linestyle='dashed', linewidth=3)

    ax1.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
    # 设置y轴刻度标签加粗
    for tick in ax1.yaxis.get_major_ticks():
        tick.label1.set_fontweight('bold')

    last_label_pos = len(x)*2 - 1
    xticks = list(ax1.get_xticks()) + [last_label_pos]
    xticklabels = list(ax1.get_xticklabels()) + ['GMean']
    ax1.set_xticks(xticks)
    ax1.set_xticklabels(xticklabels)
    # set rotation of the last xtick
    for label in ax1.get_xticklabels():
        if label.get_text() == 'GMean':
            label.set_rotation(20)
            label.set_fontsize(28)
            label.set_fontweight('bold')

    handles, labels = ax1.get_legend_handles_labels()
    # legend = ax1.legend(handles, labels, bbox_to_anchor=(0.31, 0.92), loc='center', ncol=3, fontsize=35, frameon=True)
    legend = ax1.legend(handles, labels, bbox_to_anchor=(0.5, 0.92), loc='center', ncol=5, fontsize=25, frameon=True)
    # legend = ax1.legend(handles, labels, bbox_to_anchor=(1.1, 0.5), loc='center', ncol=1, fontsize=25, frameon=True)
    frame = legend.get_frame()
    frame.set_edgecolor('#808080')  # 设置边框颜色
    frame.set_linewidth(2)  # 设置边框粗细
    frame.set_alpha(1)  # 设置边框透明度

    spines1 = ax1.spines
    spines1['top'].set_linewidth(5)
    spines1['bottom'].set_linewidth(5)
    spines1['left'].set_linewidth(5)
    spines1['right'].set_linewidth(5)  

    plt.tight_layout()
    print("prepare to save figure")
    plt.savefig(f'results/perf_comp_with_hyperg_2way_{current_date}.pdf', dpi=300, bbox_inches='tight')


if __name__ == '__main__':
    
    perf_comp_with_hyperg_2way()
