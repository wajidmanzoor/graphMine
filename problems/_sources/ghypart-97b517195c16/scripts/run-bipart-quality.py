import input_header as input
import time
import pandas as pd
import os
import re
import datetime

current_date = datetime.date.today()

nparts = [3]

# edgecut_output = "../results/ghypart_quality_results_{current_date}.csv"
edgecut_output = f"../results/bipart_quality_results_{current_date}.csv"


ref_results = "../results/quality_comp_all_240112.csv"

data = pd.read_csv(ref_results)
original_bp2 = data['BiPart']
original_gp2 = data['gHyPart']
hedges = data['HEs']
dataset = data['dataset']
bp_policy = data['policy2']
gp_policy = data['policy1']

bipart_policy = ['RAND', 'PP', 'PLD', 'WD', 'MWD', 'DEG', 'MDEG']
our_policy_list = ['-RAND', '-HDH', '-LDH', '-LSNWH', '-HSNWH', '-LRH', '-HRH']


def prof_bipart_quality_results():
    cmd = f"cd ../cpu_works/BiPart/build/ && cmake -DCMAKE_BUILD_TYPE=RELEASE .. && make bipart-cpu "
    os.system(cmd)
    
    cmd = f"cd ../build && cmake -DCMAKE_BUILD_TYPE=RELEASE .. && make -j8 "
    os.system(cmd)
    
    # with open(edgecut_output, 'w') as out:
    #     out.write("id,dataset,bipart_cut2,bipart_time2,ghypart_cut2,ghypart_time2,bipart_cut3,bipart_time3,ghypart_cut3,ghypart_time3,bipart_cut4,bipart_time4,ghypart_cut4,ghypart_time4,hedges\n")

    with open(edgecut_output, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            file_path = input.os.path.join(input.dir_path, key)
            # if value == "G67":
            if count >= 0:
            # if value == "sat_11pipe":
            # if count >= 462 and count <= 480:
            # if ("ibm" in value or "dac" in value) and count >= 319:
                out.write(str(count)+","+value+",")
                print(count, value)
                hedges = 0
                for n in nparts:
                    LOG1 = "run-bipart.log"
                    cut_result = []
                    time = []
                    # for policy in bipart_policy:
                    policy = bp_policy[count]
                    cmd = f"../cpu_works/BiPart/build/lonestar/analytics/cpu/bipart/bipart-cpu -hMetisGraph "
                    cmd += f"{file_path} -t=12 "
                    cmd += f"--{policy} "
                    # cmd += f"--RAND "
                    cmd += f"--numPartitions={n} "
                    cmd += f"--output=1 > {LOG1}"
                    print(cmd)
                    # os.system(cmd)
                    input.subprocess.call(cmd, shell=True)
                    
                    with open(f'{LOG1}', 'r') as file:
                        for line in file:
                            # 使用正则表达式匹配包含特定文本格式的行
                            match = re.search(r'Final Edge Cut,(\d+)', line)
                            if match:
                                bipart = int(match.group(1))
                                print(f"n={n}, policy={policy}, bipart={bipart}")
                                cut_result.append(bipart)
                            match = re.search(r'Total time\(s\):,(\d+\.\d+)', line)
                            if match:
                                bipart = float(match.group(1))
                                time.append(bipart)
                            match = re.search(r'number of hedges (\d+)$', line)
                            if match:
                                hedges = int(match.group(1))
                                print(hedges)
                    min_bipart = min(cut_result)
                    min_index = cut_result.index(min_bipart)
                    print(f"n={n}, min_bipart={min_bipart}, min_index={min_index}, policy={bipart_policy[min_index]}")
                    out.write(f"{min_bipart},{time[min_index]},")
                    
                    if value == 'bloweya':
                        min_index = 3
                    if value == 'Chem97Zt':
                        min_index = 1
                    
                    LOG = "run-ghypart.log"
                    file_path = input.os.path.join(input.dir_path, key)
                    cmd = f"../build/gHyPart "
                    cmd += f"{file_path} "
                    cmd += f"-bp -wc 0 -useuvm 0 -sort_input 1 "
                    cmd += f"-useSelection 1 "
                    cmd += f"-useMemOpt 1 "
                    # cmd += f"{our_policy_list[min_index]} "
                    cmd += f"{gp_policy[count]} "
                    cmd += f"-numPartitions {n} "
                    cmd += f" > {LOG}"
                    print(cmd)
                    # os.system(cmd)
                    # input.subprocess.call(cmd, shell=True)
                    
                    # with open(f'{LOG}', 'r') as file:
                    #     for line in file:
                    #         # 使用正则表达式匹配包含特定文本格式的行
                    #         match = re.search(r'Total k-way partition time \(s\): (\d+\.\d+)', line)
                    #         if match:
                    #             ghypart = float(match.group(1))
                    #         match = re.search(r'# of Hyperedge cut: (\d+)', line)
                    #         if match:
                    #             ghypart_cut = int(match.group(1))
                    # out.write(f"{ghypart_cut},{ghypart},")
                    out.write(",,")
                    # out.flush()
                out.write(f"{hedges}\n")
                out.flush()
            count += 1



if __name__ == '__main__':
    
    start_time = time.time()
    prof_bipart_quality_results()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
