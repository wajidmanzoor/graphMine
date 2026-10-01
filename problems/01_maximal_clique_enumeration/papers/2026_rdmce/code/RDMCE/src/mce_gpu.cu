#include "mce_gpu.cuh"
#include "graph_gpu.cuh"
#include "context_gpu.cuh"
#include "kernels/BkPivotBitBalance.cuh"
#include "kernels/BkPivotBitBalanceMultiGPU.cuh"
#include <thread>
#include <vector>

MceGpuSolver::MceGpuSolver(Graph &g, int device_id) : g_(g), device_id_(device_id), mce_count_(0)
{
  CUDA_CHECK(cudaSetDevice(device_id_));
}

void MceGpuSolver::Solve()
{
  g_.ConvertToCsr();
  timer_.Start();
  auto res = BkSolverWrapper(g_, device_id_);
  timer_.Stop();
  std::cout << "\nMC numbers: " << res << std::endl;
  std::cout << "MCE GPU Time: " << timer_.Elapsed() << std::endl;
}


void GmceMultiGpuSolve(Graph &g, std::vector<int> device_ids){
  g.ConvertToCsr();
  acc_t* mc_num_dev;
  CUDA_CHECK(cudaMallocManaged((void **)&mc_num_dev, sizeof(acc_t)));
  CUDA_CHECK(cudaMemset(mc_num_dev, 0, sizeof(acc_t)));
  vid_t* cur_id_dev;
  CUDA_CHECK(cudaMallocManaged((void **)&cur_id_dev, sizeof(vid_t)));
  CUDA_CHECK(cudaMemset(cur_id_dev, 0, sizeof(vid_t)));

  std::vector<std::thread> threads;  // 声明threads变量
  Timer timer;
  timer.Start();
  for (size_t i = 0; i < device_ids.size(); ++i) {
    threads.emplace_back([&, i]() {  // 移除results变量的捕获
        Timer this_timer;
        this_timer.Start();
        CUDA_CHECK(cudaSetDevice(device_ids[i]));
        BkSolverWrapperMultiGPU(g, device_ids[i], cur_id_dev, mc_num_dev);
        this_timer.Stop();
        std::cout << device_ids[i] << ": " << this_timer.Elapsed() << std::endl;
    });
  }
  
  for (auto &thread : threads) {
    thread.join();
  }
  timer.Stop();
  std::cout << "MCE Multi GPU Time: " << timer.Elapsed() << std::endl;
  acc_t mc_num;
  CUDA_CHECK(cudaMemcpy(&mc_num, mc_num_dev, sizeof(acc_t), cudaMemcpyDeviceToHost));
  std::cout << "MCE Multi GPU MC numbers: " << mc_num << std::endl;

  CUDA_CHECK(cudaFree(mc_num_dev));
  CUDA_CHECK(cudaFree(cur_id_dev));
}