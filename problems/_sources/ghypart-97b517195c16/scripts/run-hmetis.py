import input_header as input
import time
import pandas as pd
import os
import re
import shlex
import signal

nparts = [2, 3, 4]

# edgecut_output = "../results/prof_hmetis_12coreCPU.csv"
# edgecut_output = "../results/prof_hmetis_xeon_4214R.csv"
edgecut_output = "../results/prof_hmetis_xeon_4214R_all.csv"

bipart_perf = '../results/bipart_perf_xeon_4214R_24cores_t12.csv'

data = pd.read_csv(bipart_perf)
bp2 = data['k=2']
bp3 = data['k=3']
bp4 = data['k=4']
print(max(bp2), max(bp3), max(bp4))
print(data.iloc[:, 2].max(), data.iloc[:, 3].max(), data.iloc[:, 4].max())

def prof_hmetis_results():
    # with open(edgecut_output, 'w') as out:
    #     out.write("id,dataset,part2_cut,part2_time,part3_cut,part3_time,part4_cut,part4_time\n")

    with open(edgecut_output, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            # if value == "G67":
            if count >= 0:
            # if count >= 462 and count <= 480:
            # if "ibm" in value or "dac" in value:
                out.write(str(count)+","+value+",")
                print(count, value)
                for n in nparts:
                    LOG = "run-hmetis.log"
                    file_path = input.os.path.join(input.dir_path, key)
                    cmd = f"../cpu_works/hmetis-1.5-linux/hmetis "
                    cmd += f"{file_path} "
                    cmd += f"{n} "  # nparts
                    cmd += f"5 "    # ubfactor
                    cmd += f"5 "   # niter
                    cmd += f"2 "    # CType
                    cmd += f"1 "    # RType
                    cmd += f"3 "    # Vcycle
                    cmd += f"1 "    # ReconstructHE
                    cmd += f"24 "   # Show all information about the multiple runs
                    # cmd += f"> {LOG}"
                    print(cmd)
                    # os.system(cmd)

                    timeout = data.iloc[:, n].max() * 5
                    print(f"timeout: {timeout}")
                    try:
                        # process = input.subprocess.call(cmd, shell=True, 
                        #                                 timeout=5 * data.iloc[n][count])
                        # result = input.subprocess.run(shlex.split(cmd), stdout=input.subprocess.PIPE, 
                        #                               stderr=input.subprocess.PIPE, timeout=5, check=True)
                        # text = result.stdout.decode("utf-8")
                        # print(text)
                        with open(LOG, "w") as log:
                            result = input.subprocess.run(shlex.split(cmd), stdout=log, 
                                                    stderr=input.subprocess.PIPE, timeout=timeout, check=True)
                            # print("result.returncode: ", result.returncode)
                            # if result.returncode != 0:
                            #     print("result.stderr: ", result.stderr.decode("utf-8"))
                            #     if result.returncode == -signal.SIGSEGV:
                            #         print("Segmentation fault occurred in the external program.")

                        with open(LOG, 'r') as file:
                            text = file.read()
                            
                        # 使用正则表达式找到所有 average 的值
                        pattern1 = r'average = (\d+\.\d+)'
                        average_values = re.findall(pattern1, text)
                        
                        pattern2 = r'Partitioning Time:\s+(\d+\.\d+)sec'
                        match = re.search(pattern2, text)
                        if match:
                            partitioning_time = float(match.group(1))
                            print(f"partitioning_time: {partitioning_time}")
                        # 将所有找到的 average 值转换为浮点数并求和
                        total_average = sum(float(value) for value in average_values)
                        
                        print(f"total_average: {total_average}")
                        out.write(f"{total_average},{partitioning_time},")

                    except input.subprocess.TimeoutExpired:
                        print("Process timed out")
                        # print(result.stderr.decode("utf-8"))
                        out.write(f"timeout,{timeout},")
                    except Exception as e:
                        if "Signals.SIGSEGV" in str(e):
                            print("Segmentation fault occurred in the external program!")
                            out.write(f"segfault,{timeout},")
                    out.flush()
                out.write("\n")
            count += 1
            
if __name__ == '__main__':
    
    start_time = time.time()
    prof_hmetis_results()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
