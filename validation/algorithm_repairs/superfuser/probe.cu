#include "gpu_core.cuh"
#include <iomanip>
#include <iostream>
#include <fstream>

int main(){
    using namespace superfuser;
    std::string line;
    try {
        while(std::getline(std::cin,line)){
            std::istringstream in(line);std::string id,path,mode,oracle;
            Options options;int chars,partitions;
            if(!(in>>id>>std::quoted(path)>>options.seeds>>options.samples>>options.random_seed>>options.block_size>>chars>>partitions>>mode))return 3;
            options.char_sketch=chars;HostGraph graph=read_graph(path);std::vector<int> devices(partitions,0);
            std::cout<<std::setprecision(17);
            if(mode=="solve"){
                Result result=solve(graph,options,devices);
                std::cout<<"{\"name\":\""<<id<<"\",\"seeds\":[";
                for(size_t i=0;i<result.seeds.size();++i){if(i)std::cout<<',';std::cout<<result.seeds[i];}
                std::cout<<"],\"spread\":[";
                for(size_t i=0;i<result.spread.size();++i){if(i)std::cout<<',';std::cout<<result.spread[i];}
                std::cout<<"],\"training\":[";
                for(size_t i=0;i<result.training_spread.size();++i){if(i)std::cout<<',';std::cout<<result.training_spread[i];}
                std::cout<<"]}"<<std::endl;
            }else if(mode=="core"){
                if(!(in>>std::quoted(oracle)) || options.seeds>graph.n)return 4;
                std::ifstream expected(oracle,std::ios::binary);if(!expected)return 5;
                std::vector<std::unique_ptr<Shard>> shards;
                for(int s=0;s<partitions;++s){
                    uint32_t begin=static_cast<uint64_t>(options.samples)*s/partitions,end=static_cast<uint64_t>(options.samples)*(s+1)/partitions;
                    shards.push_back(std::make_unique<Shard>(graph,0,begin,end-begin,options));
                }
                uint64_t checks=0;
                for(uint32_t step=0;step<=options.seeds;++step){
                    std::vector<float> truth(static_cast<size_t>(graph.n)*options.samples);
                    if(!expected.read(reinterpret_cast<char*>(truth.data()),truth.size()*sizeof(float)))return 6;
                    for(auto& shard:shards){
                        shard->rebuild(options.char_sketch);auto values=shard->sketches();auto scores=shard->scores();
                        std::vector<uint32_t> active(shard->states);
                        SF_CUDA(cudaMemcpy(active.data(),shard->active.data(),active.size()*sizeof(uint32_t),cudaMemcpyDeviceToHost));
                        for(uint32_t v=0;v<graph.n;++v){
                            double sum=0;
                            for(uint32_t r=0;r<shard->samples;++r){
                                size_t pos=static_cast<size_t>(v)*shard->samples+r;
                                float wanted=truth[static_cast<size_t>(v)*options.samples+shard->start+r];
                                if(std::abs(values[pos]-wanted)>3e-6f*std::max(1.0f,std::abs(wanted)) || active[pos]!=(wanted<0))
                                    throw std::runtime_error(id+": wrong sketch or activation mask at step "+std::to_string(step)+", vertex "+std::to_string(v)+", sample "+std::to_string(r));
                                sum+=std::max(0.0f,wanted);++checks;
                            }
                            if(std::abs(sum-scores[v])>3e-6*std::max(1.0,sum))throw std::runtime_error(id+": wrong sketch reduction");
                        }
                        if(step<options.seeds)shard->cascade(step);
                    }
                }
                char extra;if(expected.read(&extra,1))return 7;
                std::cout<<"{\"name\":\""<<id<<"\",\"core_checks\":"<<checks<<"}"<<std::endl;
            }else return 8;
        }
    }catch(const std::exception& error){std::cerr<<"probe: "<<error.what()<<'\n';return 2;}
    return 0;
}
