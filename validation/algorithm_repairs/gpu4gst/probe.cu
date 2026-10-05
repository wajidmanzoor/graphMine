// Exercise the production parser, allocation lifecycle, and GPU implementation
// repeatedly in one CUDA context. No CPU solver or substitute kernel is used.
#define main gpu4gst_cli_main
#include "GSTnonHop.cu"
#undef main
#include <iomanip>
int main() {
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream input(line);
        std::string id,path;
        int groups, count;
        if (!(input >> id >> std::quoted(path) >> groups >> count)) return 3;
        std::cout << "BEGIN " << id << std::endl;
        std::vector<std::string> words{"TrimCDP-WB","unused",path,"graph",std::to_string(groups),"0",std::to_string(count-1),"--witness"};
        std::vector<char*> args;
        for (auto& word : words) args.push_back(word.data());
        int code = gpu4gst_cli_main(args.size(),args.data());
        std::cout << "END " << id << ' ' << code << std::endl;
        if (code) return code;
    }
    return 0;
}
