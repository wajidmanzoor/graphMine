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

# file = 'overP2/benchmarks_all_patterns_3090_20240102_allversions.csv'
file = 'results/benchmarks_all_patterns_real_hypergraphs_4060Ti_2024-01-08.csv'
# file = 'results/benchmarks_all_patterns_real_hypergraphs_3090_2024-01-08.csv'

data = pd.read_csv(file)

data['ratio'] = data.iloc[:,30] / data.iloc[:,29]
sorted_data = data.sort_values(by='ratio')
# sorted_data = data.iloc[:-1].sort_values(by='ratio')
# sorted_data = pd.concat([sorted_data, data.iloc[-1:]])
sorted_data.reset_index(drop=True, inplace=True)
data = sorted_data
x = data.iloc[:,0]
index_list = range(len(x))

plt.rcParams['font.weight'] = 'bold'
plt.rcParams['axes.labelweight'] = 'bold'
# plt.rcParams['legend.fontsize'] =  30
plt.rcParams['legend.frameon'] =  True

colors = ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#800080", "#ffc0cb", "#ffa500", "#808080", "#007fff", "#8e52dc"]

# fig, ax = plt.subplots(figsize=(34, 10))
# fig, ax = plt.subplots(figsize=(20, 7.5))
# fig, (ax, ax1) = plt.subplots(1, 2, figsize=(30, 7.5))

# ax.set_position([0.1, 0.1, 1, 0.8])
# ax1.set_position([0.78, 0.1, 0.2, 0.8])
fig = plt.figure(figsize=(25, 9))
# spec = fig.add_gridspec(1, 2, width_ratios=[1.0, 1])
# for 4060Ti
spec = fig.add_gridspec(1, 2, width_ratios=[2.2, 1])
ax = fig.add_subplot(spec[0, 0])
ax1 = fig.add_subplot(spec[0, 1])

def myplot(data, markers, labels, color, markersize = 5):
    n = len(data)
    counts = []
    for k in range(n+1):
        count = np.sum(data >= k/n)
        counts.append(count)
    print(counts)
    print(len(counts))
    cdf = np.asarray(counts) / n
    cdf = cdf[::-1]  # 倒转CDF的顺序
    print(cdf)
    percentiles = np.linspace(0, 100, n+1)
    percentiles = percentiles[::-1]  # 倒转百分位数的顺序
    print(percentiles)
    # print(np.sum(data['ratio'] <= 0.99999999))
    ax.plot(percentiles, cdf, marker=markers, markersize = markersize, linestyle='-', label=labels, color=color, linewidth=2)

cmap = plt.cm.Blues
Colors = cmap(np.linspace(0.5, 1, 6))
'''
data['base_ratio'] = data.iloc[:,30] / data.iloc[:,2]
myplot(data['base_ratio'], '*', 'ɢHʏPᴀʀᴛ-B', colors[8])

# data['p2_ratio'] = data.iloc[:,30] / data.iloc[:,44]
data['p2_ratio'] = data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12']
myplot(data['p2_ratio'], 'x', 'ɢHʏPᴀʀᴛ-P2', colors[6])

# data['p3_ratio'] = data.iloc[:,30] / data.iloc[:,45]
data['p3_ratio'] = data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12']
myplot(data['p3_ratio'], 'v', 'ɢHʏPᴀʀᴛ-P3', colors[9])

# data['random3_ratio'] = data.iloc[:,30] / data.iloc[:,42]
data['random3_ratio'] = data.iloc[:,30] / data['gHyPart-rand']
myplot(data['random3_ratio'], '^', 'ɢHʏPᴀʀᴛ-R', colors[0])

# data['3090'] = data.iloc[:,30] / data['gHyPart-3090']
# norm_3090 = data['3090'].tolist()
# norm_3090 = [1 if x > 1.0 else x for x in norm_3090]
# myplot(data['3090'], '+', 'ɢHʏPᴀʀᴛ-3090', Colors[3])

myplot(data['ratio'], 'o', 'ɢHʏPᴀʀᴛ', 'grey')

ax.set_yscale('linear')
ax.set_ylim(0, 1.01)
ax.tick_params(axis='y', which='major', labelsize=36)
ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax.set_ylabel('Hypergraphs (%)', va='center', fontsize=48, fontweight='bold', labelpad=40)  # 设置纵坐标title

ax.set_xlabel('Performance normalized to ɢHʏPᴀʀᴛ-O', va='center', fontsize=40, fontweight='bold', labelpad=36)
# ax.set_xlim(0, len(x)+55)
ax.set_xlim(0,1)
ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)
# ax.xaxis.set_ticks([0, 100, 200, 300, 400, len(x)-1], fontsize=40)
ax.invert_xaxis()  # 翻转x轴
ax.xaxis.set_ticks([105, 100, 90, 60, 40, 20, 0])  # 设置x轴刻度
ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
tick_labels = ax.get_xticklabels()
mytickss = [101, 100, 88, 60, 40, 20, 0]
mylabels = ['101%', '100%', '90%', '60%', '40%', '20%', '0%']
ax.set_xticks(mytickss)  # 设置X轴刻度位置为0和100
ax.set_xticklabels(mylabels)
# 遍历刻度标签
for label in tick_labels:
    # 获取刻度值
    tick_value = label.get_text()
    # 判断是否为90
    if tick_value == '90%':
        # 设置90刻度标签为红色
        label.set_color('red')
    if tick_value == '101%':
        # 设置100刻度标签为不可见
        label.set_visible(False)
        
ax.axvline([90], color='grey', linestyle='dashed', linewidth=3)

# '''
data['speedupBiPart'] = data['BiPart'] / data['gHyPart']
sorted_data = data.sort_values(by='speedupBiPart')
sorted_data.reset_index(drop=True, inplace=True)
y1 = sorted_data['BiPart'] / sorted_data['BiPart']
y2 = sorted_data['BiPart'] / sorted_data['p1_k1235_p1_k4k6_p2_k12']
y3 = sorted_data['BiPart'] / sorted_data['gHyPart']

ylim = 1e3
ax.set_yscale('log', base=10)  # 设置纵坐标为log2刻度
ax.set_ylim(0, ylim)  # 设置纵坐标起始值为0
ax.yaxis.set_ticks([0.1, 1, 10, 100, 1000], fontsize=40)  # 设置刻度值
ax.tick_params(axis='y', which='major', labelsize=40)
ax.set_ylabel('Speedup over BiPart', va='center', fontsize=45, fontweight='bold', labelpad=45)  # 设置纵坐标title
ax.set_xlabel('Hypergraphs', va='center', fontsize=45, fontweight='bold', labelpad=40)

print(len(x))
xlim = 730
ax.set_xlim(0, xlim)
ax.xaxis.set_ticks([0, 250, len(x)-1], fontsize=40)
ax.set_xticks([0, 250, len(x)-1])
ax.tick_params(axis='x', which='major', labelsize=40, rotation=0)
dot1 = ax.plot(index_list, y1, marker='+', linestyle='-', label='BiPart', color="#808080", linewidth=2)
dot2 = ax.plot(index_list, y2, marker='x', linestyle='-', label='ɢHʏPᴀʀᴛ-B', color=colors[6], linewidth=2)
dot3 = ax.plot(index_list, y3, marker='^', linestyle='-', label='ɢHʏPᴀʀᴛ', color=colors[8], linewidth=2)

ax.axvline([len(x) + 50], color='grey', linestyle='dashed', linewidth=2)

last_center = 590
bar1_pos = last_center + 5
bar2_pos = last_center + 50
bar3_pos = last_center + 95
width = 40
bar1 = ax.bar(bar1_pos, gmean(y1), width=width, label='', edgecolor='black', color="#808080", hatch='//')
bar2 = ax.bar(bar2_pos, gmean(y2), width=width, label='', edgecolor='black', color=colors[6], hatch='\\')
bar3 = ax.bar(bar3_pos, gmean(y3), width=width, label='', edgecolor='black', color=colors[8], hatch='o')

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    
last_label_pos = 640
xticks = list(ax.get_xticks()) + [last_label_pos]
# xticks = []#[0, 250, len(x)-1, last_label_pos]
print(xticks)
# xticklabels = list(ax.get_xticklabels()) + ['GMean']
xticklabels = list(ax.get_xticks()) + ['GMean']
print(xticklabels)
# ax.set_xticks(xticks)
ax.xaxis.set_ticks(xticks, fontsize=40)
ax.set_xticklabels(xticklabels)

xtick_labels = ax.get_xticklabels()
# 设置最后一个xtick label的大小、角度和颜色
last_xtick_label = xtick_labels[-1]
last_xtick_label.set_fontsize(40)
last_xtick_label.set_rotation(0)

ax.text(bar1_pos, gmean(y1) + 0.5, "[{:.2f}]".format(gmean(y1)), color="#808080", ha='center', fontsize=30, rotation=90)
ax.text(bar2_pos+0.5, gmean(y2) + 5, "[{:.2f}]".format(gmean(y2)), color=colors[6], ha='center', fontsize=30, rotation=90)
ax.text(bar3_pos, gmean(y3) + 5, "[{:.2f}]".format(gmean(y3)), color=colors[8], ha='center', fontsize=30, rotation=90)
# '''
width = 1
# labels = ['ɢHʏPᴀʀᴛ-B', 'ɢHʏPᴀʀᴛ-R1', 'ɢHʏPᴀʀᴛ-R2', 'ɢHʏPᴀʀᴛ']
# labels = ['ɢHʏPᴀʀᴛ-B', 'ɢHʏPᴀʀᴛ-P2', 'ɢHʏPᴀʀᴛ-P3', 'ɢHʏPᴀʀᴛ-R', 'ɢHʏPᴀʀᴛ']
# labels = ['ɢHʏPᴀʀᴛ-B', 'ɢHʏPᴀʀᴛ-P2', 'ɢHʏPᴀʀᴛ-P3', 'ɢHʏPᴀʀᴛ-R', 'ɢHʏPᴀʀᴛ-3090', 'ɢHʏPᴀʀᴛ']
# labels = ['Base', 'P2', 'P3', 'Rand', '3090', '4060Ti']
# myticks = [-0.3, 0.9, 2.1, 3.3, 4.5, 5.7]
labels = ['Ported', 'Re-trained']
myticks = [-0.1, 1.5]

# labels = ['Base', 'P2', 'P3', 'Rand', 'ɢHʏPᴀʀᴛ']
# myticks = [-0.2, 1.0, 2.2, 3.4, 4.6]

ax1.set_yscale('linear')
ax1.set_ylim(0, 1.01)
ax1.tick_params(axis='y', which='major', labelsize=32)
ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: '{:.0%}'.format(x)))
ax1.set_ylabel('Performance Normalized \nto ɢHʏPᴀʀᴛ-O', va='center', fontsize=40, fontweight='bold', labelpad=30)  # 设置纵坐标title
ax1.set_xlabel('', va='center', fontsize=30, fontweight='bold', labelpad=100)
ax1.set_xlim(-1.0 * width + .0, len(labels) + 0.4)
ax1.set_xticks(ticks=[i for i in range(len(labels))], rotation=0, fontsize=38, labels=labels, fontweight='bold')
# ax1.set_xticks(ticks=[i for i in range(len(labels))], rotation=30, fontsize=36, labels=labels, fontweight='bold')
# ax1.set_xticklabels(ax.get_xticks(), rotation=0, ha='right', fontsize=36, va='top', distance=0.5)

ticks = []
# for i in range(len(labels)):
#     ticks.append(i-0.1)
# ax1.set_xticks(ticks)  # 设置X轴刻度位置为0和100
ax1.set_xticks(myticks)  # 设置X轴刻度位置为0和100
ax1.set_xticklabels(labels)

# '''
data['3090'] = data.iloc[:,30] / data['gHyPart-3090']
norm_3090 = data['3090'].tolist()
norm_3090 = [1 if x > 1.0 else x for x in norm_3090]


# ax1.bar(0-0.3, gmean(data.iloc[:,30] / data.iloc[:,2]), width=width, label='Base', edgecolor='black', color=colors[8], hatch='*')
# ax1.bar(1-0.1, gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12']), width=width, label='P2', edgecolor='black', color=colors[6], hatch='x')
# ax1.bar(2+0.1, gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12']), width=width, label='P3', edgecolor='black', color=colors[9], hatch='.')
# ax1.bar(3+0.3, gmean(data.iloc[:,30] / data['gHyPart-rand']), width=width, label='RAND', edgecolor='black', color=colors[0], hatch='\\')

ax1.bar(-0.1, gmean(norm_3090), width=width, label='3090', edgecolor='black', color=Colors[2], hatch='')
ax1.bar(1.5, gmean(data.iloc[:,30] / data.iloc[:,29]), width=width, label='4060Ti', edgecolor='black', color=Colors[4], hatch='')

# ax1.text(0-0.3, gmean(data.iloc[:,30] / data.iloc[:,2]) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data.iloc[:,2])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(1-0.1, gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12'])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(2+0.1, gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12'])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(3+0.3, gmean(data.iloc[:,30] / data['gHyPart-rand']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['gHyPart-rand'])), color='black', ha='center', fontsize=26, rotation=0)

ax1.text(-0.1, gmean(norm_3090) + 0.01, "{:.1%}".format(gmean(norm_3090)), color='black', ha='center', fontsize=36, rotation=0)
ax1.text(1.5, gmean(data.iloc[:,30] / data.iloc[:,29]) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data.iloc[:,29])), color='black', ha='center', fontsize=36, rotation=0)
# '''

# ax1.bar(0-0.2, gmean(data.iloc[:,30] / data.iloc[:,2]), width=width, label='Base', edgecolor='black', color=colors[8], hatch='*')
# ax1.bar(1-0.0, gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12']), width=width, label='P2', edgecolor='black', color=colors[6], hatch='x')
# ax1.bar(2+0.2, gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12']), width=width, label='P3', edgecolor='black', color=colors[9], hatch='.')
# ax1.bar(3+0.4, gmean(data.iloc[:,30] / data['gHyPart-rand']), width=width, label='RAND', edgecolor='black', color=colors[0], hatch='\\')
# ax1.bar(len(labels)-1+0.6, gmean(data.iloc[:,30] / data.iloc[:,29]), width=width, label='4060', edgecolor='black', color='grey', hatch='/')

# ax1.text(0-0.2, gmean(data.iloc[:,30] / data.iloc[:,2]) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data.iloc[:,2])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(1-0.0, gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['p2_k1235_p2_k4k6_p2b_k12'])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(2+0.2, gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['p3_k1235_p3_k4k6_p3_k12'])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(3+0.4, gmean(data.iloc[:,30] / data['gHyPart-rand']) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data['gHyPart-rand'])), color='black', ha='center', fontsize=26, rotation=0)
# ax1.text(len(labels)-1+0.6, gmean(data.iloc[:,30] / data.iloc[:,29]) + 0.01, "{:.1%}".format(gmean(data.iloc[:,30] / data.iloc[:,29])), color='black', ha='center', fontsize=26, rotation=0)
# # '''

ax.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    
ax1.yaxis.grid(True, color='gray', linestyle = '--', linewidth = 0.5)  # horizontal grid, another method
# 设置y轴刻度标签加粗
for tick in ax1.yaxis.get_major_ticks():
    tick.label1.set_fontweight('bold')
    

handles, labels = ax.get_legend_handles_labels()
# legend = ax.legend(handles, labels, bbox_to_anchor=(1.0, 0.02), loc='lower right', ncol=1, fontsize=30, frameon=True)
legend = ax.legend(handles, labels, bbox_to_anchor=(0.45, 0.92), loc='center', ncol=3, fontsize=30, frameon=True)
# legend = ax.legend(handles, labels, bbox_to_anchor=(0.0, 1.0), loc='upper left', ncol=1, fontsize=30, frameon=True)
# legend = ax.legend(handles, labels, bbox_to_anchor=(0.0, 1.0), loc='upper left', ncol=3, fontsize=30, frameon=True)
frame = legend.get_frame()
frame.set_edgecolor('#808080')  # 设置边框颜色
frame.set_linewidth(1)  # 设置边框粗细
frame.set_alpha(1)  # 设置边框透明度
# frame.set_linestyle('dashed')
frame = legend.get_frame()
frame.set_edgecolor('#808080')  # 设置边框颜色
frame.set_linewidth(2)  # 设置边框粗细
frame.set_alpha(1)  # 设置边框透明度
# ax.xaxis.label.set_fontweight('bold')
# ax.yaxis.label.set_fontweight('bold')
# ax.legend(fontsize=25, frameon=True)

spines = ax.spines
spines['top'].set_linewidth(5)
spines['bottom'].set_linewidth(5)
spines['left'].set_linewidth(5)
spines['right'].set_linewidth(5)  
'''
handles1, labels1 = ax1.get_legend_handles_labels()
legend1 = ax1.legend(handles1, labels1, bbox_to_anchor=(0.48, 1.15), loc='center', ncol=3, fontsize=30, frameon=True)
frame1 = legend1.get_frame()
frame1.set_edgecolor('#808080')  # 设置边框颜色
frame1.set_linewidth(1)  # 设置边框粗细
frame1.set_alpha(1)  # 设置边框透明度
# frame1.set_linestyle('dashed')
frame1 = legend.get_frame()
frame1.set_edgecolor('#808080')  # 设置边框颜色
frame1.set_linewidth(2)  # 设置边框粗细
frame1.set_alpha(1)  # 设置边框透明度
# ax1.xaxis.label.set_fontweight('bold')
# ax1.yaxis.label.set_fontweight('bold')
# ax1.legend(fontsize=15, frameon=True)
'''
spines1 = ax1.spines
spines1['top'].set_linewidth(5)
spines1['bottom'].set_linewidth(5)
spines1['left'].set_linewidth(5)
spines1['right'].set_linewidth(5)  

# 调整布局以适应标签
plt.tight_layout()
plt.subplots_adjust(wspace=0.35) 

# output = 'overP2/benchmarks_all_patterns_3090_20240102_allversions.pdf'
# output = 'overP2/benchmarks_all_patterns_4060Ti_20240108_allversions.pdf'
# output = 'overP2/benchmarks_all_patterns_3090_20240108_allversions.pdf'
output = f'results/benchmarks_all_patterns_allversions_4060Ti_{current_date}.pdf'
# output = f'results/benchmarks_all_patterns_allversions_3090_{current_date}.pdf'

# 保存图片
plt.savefig(output, dpi=300, bbox_inches='tight')

# 显示图形  
plt.show()
