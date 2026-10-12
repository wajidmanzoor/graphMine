import input_header as input
import time
import pandas as pd
import os
import re

nparts = [2, 3, 4]

# edgecut_output = "../results/mtkahypar_quality_xeon_4214R.csv"
edgecut_output = "../results/mtkahypar_all_quality_xeon_4214R.csv"

perf_results = "../results/mtkahypar_perf_xeon_4214R_24cores_t12_direct.csv"
# perf_results = "../results/taco_revision/mtkahypar_perf_xeon_4214R_24cores_t12_recursive.csv"


def prof_mtkahypar_results():

    # cmd = f"cd ../cpu_works/Mt-KaHyPar-SDet/build && rm -rf * && cmake -DCMAKE_BUILD_TYPE=Release .. && make MtKaHyPar -j "
    cmd = f"cd ../cpu_works/Mt-KaHyPar-SDet/build && make MtKaHyPar -j "
    os.system(cmd)
    
    # with open(perf_results, 'w') as out:
    #     out.write("id,dataset,k=2,k=3,k=4,\n")
    with open(perf_results, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            file_path = input.os.path.join(input.dir_path, key)
            # if value == "G67":
            if count >= 0:
            # if value == "tran5":
            # if count >= 462 and count <= 480:
                out.write(str(count)+","+value+",")
                print(count, value)
                for n in nparts:
                    LOG1 = "run-mtkahypar.log"
                    cmd = f"../cpu_works/Mt-KaHyPar-SDet/build/mt-kahypar/application/MtKaHyPar -h "
                    cmd += f"{file_path} "
                    cmd += f"-p ../cpu_works/Mt-KaHyPar-SDet/config/deterministic_preset.ini "
                    cmd += f"--instance-type=hypergraph "
                    cmd += f"-k {n} "
                    cmd += f"-e 0.05 -o cut -m direct -t 12 > {LOG1}"
                    print(cmd)
                    # os.system(cmd)
                    input.subprocess.call(cmd, shell=True)
                    # out.write(f"{total_average},{partitioning_time},")
                    
                    # with open(f'{LOG1}', 'r') as file:
                    #     for line in file:
                    #         # 使用正则表达式匹配包含特定文本格式的行
                    #         # match = re.search(r'Final Edge Cut,(\d+)', line)
                    #         match = re.search(r'Total time\(s\):,(\d+\.\d+)', line)
                    #         if match:
                    #             # bipart = int(match.group(1))
                    #             bipart = float(match.group(1))
                    #             break
                    mtkahypar = []
                    with open(LOG1, 'r') as file:
                        reader = input.csv.reader(file)
                        for row in reader:
                            if row and ('+ Preprocessing' in row[0] or '+ Coarsening' in row[0] or '+ Initial' in row[0] or '+ Refinement' in row[0] or '+ Postprocessing' in row[0]):
                                substr = row[0][48:]
                                result = substr[:len(substr)-2]
                                # print(result)
                                mtkahypar.append(float(result))
                    result2 = '{:.3f}'.format(input.math.fsum(mtkahypar))
                    print(f"n={n}, time={result2}")
                    out.write(str(result2)+",")
                    out.flush()
                out.write("\n")
            count += 1


def prof_mtkahypar_quality_results():
    # cmd = f"cd ../cpu_works/Mt-KaHyPar-SDet/build && rm -rf * && cmake -DCMAKE_BUILD_TYPE=Release .. && make MtKaHyPar -j "
    cmd = f"cd ../cpu_works/Mt-KaHyPar-SDet/build && make MtKaHyPar -j "
    os.system(cmd)
    
    # with open(edgecut_output, 'w') as out:
    #     out.write("id,dataset,part2_cut,part2_time,part3_cut,part3_time,part4_cut,part4_time\n")
        
    with open(edgecut_output, 'a') as out:
        count = 0
        for key, value in input.input_map.items():
            file_path = input.os.path.join(input.dir_path, key)
            # if value == "G67":
            if count >= 0:
            # if value == "tran5":
            # if count >= 462 and count <= 480:
            # if "ibm" in value or "dac" in value:
                out.write(str(count)+","+value+",")
                print(count, value)
                for n in nparts:
                    LOG1 = "run-mtkahypar.log"
                    cmd = f"../cpu_works/Mt-KaHyPar-SDet/build/mt-kahypar/application/MtKaHyPar -h "
                    cmd += f"{file_path} "
                    cmd += f"-p ../cpu_works/Mt-KaHyPar-SDet/config/deterministic_preset.ini "
                    cmd += f"--instance-type=hypergraph "
                    cmd += f"-k {n} "
                    cmd += f"-e 0.05 -o cut -m rb -t 12 > {LOG1}"
                    print(cmd)
                    os.system(cmd)

                    time = []
                    cut = []
                    with open(LOG1, 'r') as file:
                        reader = input.csv.reader(file)
                        for row in reader:
                            if row and ('+ Preprocessing' in row[0] or '+ Coarsening' in row[0] or '+ Initial' in row[0] or '+ Refinement' in row[0] or '+ Postprocessing' in row[0]):
                                substr = row[0][48:]
                                result = substr[:len(substr)-2]
                                time.append(float(result))
                            if row and "Hyperedge Cut" in row[0]:
                                cut.append(int(row[0][29:]))
                                
                    result2 = '{:.3f}'.format(input.math.fsum(time))
                    print(f"n={n}, cut={cut}, time={result2}")
                    out.write(f"{cut[0]},{result2},")
                    out.flush()
                out.write("\n")
            count += 1


if __name__ == '__main__':
    
    start_time = time.time()
    # prof_mtkahypar_results()
    prof_mtkahypar_quality_results()
    elapsed_time = time.time() - start_time  
    print(f"time: {elapsed_time} s, {elapsed_time / 3600} h")
