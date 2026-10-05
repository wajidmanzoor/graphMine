#define GAMMA_NO_MAIN
#include "sm.cu"
#include <sstream>
#include <regex>

int main(int argc, char** argv) {
    if (argc < 3 || argc > 4) return 2;
    std::ifstream commands(argv[1]);
    std::ofstream results(argv[2]);
    const std::regex result_pattern("matching_embeddings: ([0-9]+)");
    std::string id,graph,query,mode;
    while (commands >> id >> graph >> query >> mode) {
        if (argc == 4) {
            void* dirty=nullptr;
            check_cuda_error(cudaMalloc(&dirty,64*1024*1024));
            check_cuda_error(cudaMemset(dirty,0xa5,64*1024*1024));
            check_cuda_error(cudaFree(dirty));
        }
        std::vector<std::string> args{"sm",graph,query,mode};
        std::vector<char*> raw;
        for (auto& s:args) raw.push_back(s.data());
        std::ostringstream captured;
        auto* previous=std::cout.rdbuf(captured.rdbuf());
        int status=gamma_match_main(raw.size(),raw.data());
        std::cout.rdbuf(previous);
        if (status) { std::cerr << id << " failed: " << captured.str(); return status; }
        std::smatch match;
        const std::string output=captured.str();
        if (!std::regex_search(output,match,result_pattern)) return 3;
        results << id << " " << match[1] << "\n";
        results.flush();
    }
    check_cuda_error(cudaDeviceSynchronize());
    check_cuda_error(cudaDeviceReset());
    return 0;
}
