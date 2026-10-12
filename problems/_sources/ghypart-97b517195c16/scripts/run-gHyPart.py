import input_header as input
import time
import pandas as pd
import os
import re
import datetime

current_date = datetime.date.today()

nparts = [2, 3, 4]

edgecut_output = "../results/prof_ghypart_3090.csv"
our_policy_list = ['-RAND', '-HDH', '-LDH', '-LSNWH', '-HSNWH', '-LRH', '-HRH']

# perf_results = "../results/ghypart_perf_RTX3090.csv"
perf_results = f"../results/ghypart_perf_RTX3090_{current_date}.csv"


ref_results = "../results/quality_comp_all_240112.csv"

data = pd.read_csv(ref_results)
original_bp2 = data['BiPart']
original_gp2 = data['gHyPart']
hedges = data['HEs']
dataset = data['dataset']
bp_policy = data['policy2']
gp_policy = data['policy1']


def prof_ghypart_results():
    # with open(edgecut_output, 'w') as out:
    #     out.write("dataset,part2_cut,part2_time,part3_cut,part3_time,part4_cut,part4_time\n")
    
    # cmd = f"cd ../build_1024 && rm -rf * && cmake .. && make -j8 "
    cmd = f"cd ../build_1024 && cmake -DCMAKE_BUILD_TYPE=RELEASE .. && make -j "
    os.system(cmd)
    
    with open(perf_results, 'w') as out:
        out.write("id,dataset,k=2,k=3,k=4,\n")
    with open(perf_results, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            if count >= 0:
            # if value == "tran4":
            # if count >= 462 and count <= 480:
                out.write(str(count)+","+value+",")
                print(count, value)
                for n in nparts:
                    LOG = "run-ghypart.log"
                    file_path = input.os.path.join(input.dir_path, key)
                    cmd = f"../build_1024/gHyPart "
                    cmd += f"{file_path} "
                    cmd += f"-bp -wc 0 -useuvm 0 -sort_input 0 "
                    cmd += f"-useSelection 1 "
                    cmd += f"-useMemOpt 1 "
                    # cmd += f"-LDH "
                    # cmd += f"{gp_policy[count]} "
                    cmd += f"-numPartitions {n} "
                    cmd += f" > {LOG}"
                    print(cmd)
                    # os.system(cmd)
                    input.subprocess.call(cmd, shell=True)
                    
                    with open(f'{LOG}', 'r') as file:
                        for line in file:
                            # 使用正则表达式匹配包含特定文本格式的行
                            match = re.search(r'Total k-way partition time \(s\): (\d+\.\d+)', line)
                            if match:
                                ghypart = float(match.group(1))
                                # break
                    print(f"n={n}, time={ghypart}")
                    out.write(str(ghypart)+",")
                    out.flush()
                out.write("\n")
            count += 1
            

# perf_breakdown = f"../results/ghypart_breakdown_RTX3090_{current_date}.csv"
# perf_breakdown = f"../results/ghypart_breakdown_RTX3090_2024-10-29.csv"
# perf_breakdown = f"../results/ghypart_breakdown_RTX3090_nowarmup_{current_date}.csv"
perf_breakdown = f"../results/overP2/kernel_percentage_all_overP2_warmup.csv"

def prof_ghypart_breakdown():
    cmd = f"cd ../build_1024 && cmake -DCMAKE_BUILD_TYPE=RELEASE .. && make -j "
    os.system(cmd)
    
    # with open(perf_breakdown, 'w') as out:
    #     out.write("id,dataset,coarsening,initial partitioning,refinement,\n")
    with open(perf_breakdown, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            if count == 0:
            # if value == "tran4":
            # if count >= 462 and count <= 480:
                out.write(str(count)+","+value+",")
                print(count, value)
                LOG = "run-ghypart.log"
                file_path = input.os.path.join(input.dir_path, key)
                cmd = f"../build_1024/gHyPart "
                cmd += f"{file_path} "
                cmd += f"-bp -wc 0 -useuvm 0 -sort_input 0 "
                cmd += f"-useSelection 1 "
                # cmd += f"-usenewkernel12 0 -newParBaseK12 1 "
                cmd += f"-useMemOpt 1 "
                cmd += f" > {LOG}"
                # cmd += f"-exp 63 "
                print(cmd)
                # os.system(cmd)
                input.subprocess.call(cmd, shell=True)
                
                with open(f'{LOG}', 'r') as file:
                    for line in file:
                        # 使用正则表达式匹配包含特定文本格式的行
                        match = re.search(r'Coarsening time: (\d+\.\d+) s.', line)
                        if match:
                            coarsen = float(match.group(1))
                            # break
                        match = re.search(r'Initial partition time: (\d+\.\d+) s.', line)
                        if match:
                            partition = float(match.group(1))
                        match = re.search(r'Refinement time: (\d+\.\d+) s.', line)
                        if match:
                            refine = float(match.group(1))
                print(f"{coarsen}, {partition}, {refine}")
                out.write(f"{coarsen},{partition},{refine},")
                out.flush()
                out.write("\n")
            count += 1


def prof_ghypart_kernel_breakdown():
    cmd = f"cd ../build_1024 && cmake -DCMAKE_BUILD_TYPE=RELEASE .. && make -j "
    os.system(cmd)
    
    with open(perf_breakdown, 'w') as out:
        out.write("id,dataset,matching,node merging,construction,total,matching %,merging %,construction %,others %,")
        out.write("# of HEs,# of pins,avgHEdegree,nodemerging in remaining,nodemerging in coarsen,matching in remaining,")
        out.write("coarsen %,Refine %,partition %,refine %,balance %,project %,edge cut,1-matching-merging-const-refine\n")
    
    count = 0
    for key, value in input.input_map.items():
        if count >= 0:
        # if value == "tran4":
        # if count >= 462 and count <= 480:
            with open(perf_breakdown, 'a') as out:
                out.write(str(count)+","+value+",")
            print(count, value)
            LOG = "run-ghypart.log"
            file_path = input.os.path.join(input.dir_path, key)
            cmd = f"../build_1024/gHyPart "
            cmd += f"{file_path} "
            cmd += f"-bp -wc 0 -useuvm 0 -sort_input 0 "
            cmd += f"-usenewkernel12 0 -newParBaseK12 1 "
            cmd += f"-exp 63 > {LOG}"
            print(cmd)
            input.subprocess.call(cmd, shell=True)
            
        count += 1
            

if __name__ == '__main__':
    
    start_time = time.time()
    prof_ghypart_results()
    # prof_ghypart_breakdown()
    # prof_ghypart_kernel_breakdown()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
