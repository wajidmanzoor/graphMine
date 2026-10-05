// Exercise the real CLI repeatedly in one CUDA context. No solver is defined here.
#define main kpar_cli_main
#include "main.cu"
#undef main
#include <sstream>

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    std::ifstream commands(argv[1]);
    std::ofstream results(argv[2]);
    std::string line;
    int case_id = 0;
    while (std::getline(commands, line)) {
        std::istringstream in(line);
        std::vector<std::string> args{"kpar"};
        for (std::string arg; in >> arg;) args.push_back(arg);
        std::vector<char*> raw;
        for (auto& arg : args) raw.push_back(arg.data());
        config = Config();
        int status = kpar_cli_main(raw.size(), raw.data());
        if (status) return status;
        if (config.action == QUERY) {
            std::vector<IndexType> sources;
            load_queries(sources);
            for (unsigned i = 0; i < std::min(config.query_size, (unsigned)sources.size()); ++i) {
                results << case_id << " " << config.graph_alias << " " << sources[i] << " "
                        << config.epsilon << " " << config.k << " " << config.highrrw_size;
                std::ifstream result(config.graph_location + "result/" + std::to_string(sources[i]) + ".txt");
                int vertex;
                double score;
                while (result >> vertex >> score) results << " " << vertex << ":" << std::setprecision(17) << score;
                results << "\n";
            }
            results.flush();
            ++case_id;
        }
    }
    CUDA_CHECK(cudaDeviceSynchronize());
    CUDA_CHECK(cudaDeviceReset());
    return 0;
}
