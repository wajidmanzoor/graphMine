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
from matplotlib.ticker import PercentFormatter
import seaborn as sns
from adjustText import adjust_text
from scipy.stats import gmean
from matplotlib.gridspec import GridSpec
import datetime

current_date = datetime.date.today()

file = 'results/benchmarks_all_patterns_real_hypergraphs_3090_2024-01-08.csv'

data = pd.read_csv(file)

# plt.rcParams['font.sans-serif']=['SimHei']
# plt.rcParams['font.family'] = ['serif']
# plt.rcParams['font.serif']=['SimHei']
# plt.rcParams['axes.unicode_minus']=False

plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
plt.rcParams['legend.fontsize'] =  25
plt.rcParams['legend.frameon'] =  True

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]

# fig, ax1 = plt.subplots(figsize=(25, 11))
fig, ax1 = plt.subplots(figsize=(25, 8))

cmap = plt.cm.Blues
Colors = cmap(np.linspace(1, .1, 28))

width = 0.5
labels = ['Ideal', 
          'P1-P1-P2', 'P2-P1-P2', 'P3-P1-P2', 
          'P1-P2-P2', 'P2-P2-P2', 'P3-P2-P2',
          'P1-P3-P2', 'P2-P3-P2', 'P3-P3-P2',
          
          'P1-P1-P3', 'P2-P1-P3', 'P3-P1-P3', 
          'P1-P2-P3', 'P2-P2-P3', 'P3-P2-P3',
          'P1-P3-P3', 'P2-P3-P3', 'P3-P3-P3',
          
          'P1-P1-P2b', 'P2-P1-P2b', 'P3-P1-P2b', 
          'P1-P2-P2b', 'P2-P2-P2b', 'P3-P2-P2b',
          'P1-P3-P2b', 'P2-P3-P2b', 'P3-P3-P2b',
          ]
ax1.set_yscale('linear')
ax1.set_ylim(0, 1.01)
ax1.tick_params(axis='y', which='major', labelsize=40)
ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax1.set_ylabel('Performance Normalized \nto the Ideal Case', va='center', fontsize=40, fontweight='bold', labelpad=36)  # 设置纵坐标title
# ax1.set_ylabel('达到理想组合的吞吐量比例', va='center', fontsize=40, fontweight='bold', labelpad=36)  # 设置纵坐标title

ax1.set_xlabel('Combinations', va='center', fontsize=40, fontweight='bold', labelpad=30)
# ax1.set_xlabel('模式的所有组合', va='center', fontsize=40, fontweight='bold', labelpad=30)
# ax1.xaxis.set_ticks([])
ax1.set_xlim(-1.0 * width + .0, (len(labels) - 0) - width)
# ax1.set_xticks(ticks=[i for i in range(len(labels))], rotation=90, fontsize=30, labels=labels, fontweight='bold')
ax1.set_xticks(ticks=[i for i in range(len(labels))], rotation=90, fontsize=30, labels='', fontweight='bold')

y = [gmean(data.iloc[:,30] / data.iloc[:,30])]
errors = [np.std(np.log(data.iloc[:,30] / data.iloc[:,30]), ddof=1) / np.sqrt(len(data.iloc[:,30]))]
for i in range(27):
    y.append(gmean(data.iloc[:,30] / data.iloc[:,2+i]))
    errors.append(np.std(np.log(data.iloc[:,30] / data.iloc[:,2+i]), ddof=1) / np.sqrt(len(data.iloc[:,30])))
mycolors = ['red'] + [Colors[0]] * (len(y) - 1)
print(errors)
ax1.bar(x=[i-0.0 for i in range(len(y))], height=y, bottom=0, yerr=errors, capsize=4, color=mycolors, 
        edgecolor='black', alpha=1, width=width, hatch='', label='')
# ax1.errorbar(x=[i-0.0 for i in range(len(y))], height=y, bottom=0, yerr=errors, capsize=4, color=mycolors, 
#         edgecolor='black', alpha=1, width=width, hatch='', label='')
# ax1.bar(x=[i-0.0 for i in range(len(y))], height=y, bottom=0, color="#808080", edgecolor='black', alpha=1, width=width, hatch='', label='')

# ax1.axvline([0.5], color='grey', linestyle='dashed', linewidth=2)
# for i in range(int(27/3)):
#     ax1.axvline([0.5 + (i+1) * 3], color='grey', linestyle='dashed', linewidth=2)

ax1.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax1.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    
spines1 = ax1.spines
spines1['top'].set_linewidth(5)
spines1['bottom'].set_linewidth(5)
spines1['left'].set_linewidth(5)
spines1['right'].set_linewidth(5)  

# 调整布局以适应标签
plt.tight_layout()

output = 'results/benchmarks_all_motivation_3090_240110.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图形  
plt.show()

