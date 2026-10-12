import input_header as input
import time
import pandas as pd
import os
import re
import datetime

current_date = datetime.date.today()
nparts = [2, 3, 4]


perf_results = '../results/bipart_perf_xeon_4214R_t12_{current_date}.csv'

bipart_policy = ['RAND', 'PP', 'PLD', 'WD', 'MWD', 'DEG', 'MDEG']
our_policy_list = ['-RAND', '-HDH', '-LDH', '-LSNWH', '-HSNWH', '-LRH', '-HRH']

def prof_bipart_results():

    cmd = f"cd ../cpu_works/BiPart/build/lonestar/analytics/cpu/bipart/ && make bipart-cpu "
    # cmd = f"cd ../cpu_works/BiPart/build_docker/lonestar/analytics/cpu/bipart/ && make bipart-cpu "
    os.system(cmd)
    
    # with open(perf_results, 'w') as out:
    #     out.write("id,dataset,k=2,k=3,k=4,\n")
    with open(perf_results, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            file_path = input.os.path.join(input.dir_path, key)
            # if value == "G67":
            if count >= 0:
            # if value == "tran4":
            # if count >= 462 and count <= 480:
                out.write(str(count)+","+value+",")
                print(count, value)
                for n in nparts:
                    LOG1 = "run-bipart.log"
                    cmd = f"../cpu_works/BiPart/build/lonestar/analytics/cpu/bipart/bipart-cpu -hMetisGraph "
                    # cmd = f"../cpu_works/BiPart/build_docker/lonestar/analytics/cpu/bipart/bipart-cpu -hMetisGraph "
                    cmd += f"{file_path} -t=12 "
                    # cmd += f"--PLD "
                    cmd += f"--numPartitions={n} "
                    cmd += f"--output=1 > {LOG1}"
                    print(cmd)
                    # os.system(cmd)
                    input.subprocess.call(cmd, shell=True)
                    # out.write(f"{total_average},{partitioning_time},")
                    
                    with open(f'{LOG1}', 'r') as file:
                        for line in file:
                            # 使用正则表达式匹配包含特定文本格式的行
                            # match = re.search(r'Final Edge Cut,(\d+)', line)
                            match = re.search(r'Total time\(s\):,(\d+\.\d+)', line)
                            if match:
                                # bipart = int(match.group(1))
                                bipart = float(match.group(1))
                                break
                    
                    print(f"n={n}, time={bipart}")
                    out.write(str(bipart)+",")
                    out.flush()
                out.write("\n")
            count += 1



if __name__ == '__main__':
    
    start_time = time.time()
    prof_bipart_results()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
