#pragma once
#include "graphmine/problems/validated_expansion.hpp"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <map>
#include <numeric>
#include <queue>
#include <set>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace graphmine::detail::isolated {
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
struct BackendError : std::runtime_error {
  StatusCode code;
  BackendError(StatusCode c, const std::string& s) : std::runtime_error(s), code(c) {}
};
inline void require(bool condition, const std::string& message) {
  if (!condition) throw std::invalid_argument(message);
}
inline void certify(bool condition, const std::string& message) {
  if (!condition) throw BackendError(StatusCode::correctness_mismatch, message);
}

struct TempDirectory {
  fs::path path;
  TempDirectory() {
    std::string name=(fs::temp_directory_path()/"graphmine-worker-XXXXXX").string();
    std::vector<char> buffer(name.begin(),name.end());buffer.push_back(0);
    const auto result=mkdtemp(buffer.data());
    if (!result) throw BackendError(StatusCode::execution_failed,"cannot create worker directory");
    path=result;
  }
  ~TempDirectory() { std::error_code ignored;fs::remove_all(path,ignored); }
};

inline std::string worker_path(const std::string& name, const IsolatedBackendOptions& options) {
  const auto filename="graphmine-worker-"+name;
  if (!options.worker_directory.empty()) return (fs::path(options.worker_directory)/filename).string();
  if (const char* dir=std::getenv("GRAPHMINE_WORKER_DIR")) return (fs::path(dir)/filename).string();
  char executable[4096];const auto size=readlink("/proc/self/exe",executable,sizeof(executable)-1);
  if (size>0) {
    executable[size]=0;
    const auto candidate=fs::path(executable).parent_path()/"../libexec/graphmine"/filename;
    if (fs::is_regular_file(candidate)) return candidate.string();
  }
  for (const auto& directory : {GRAPHMINE_WORKER_BUILD_DIR,GRAPHMINE_WORKER_INSTALL_DIR}) {
    const auto candidate=fs::path(directory)/filename;
    if (fs::is_regular_file(candidate)) return candidate.string();
  }
  throw BackendError(StatusCode::backend_unavailable,"worker is missing; install workers or set GRAPHMINE_WORKER_DIR");
}

inline std::string invoke_worker(const std::string& name, std::vector<std::string> arguments,
                          const IsolatedBackendOptions& options, const TempDirectory& temp,
                          const std::map<std::string,std::string>& overrides = {}) {
  arguments.insert(arguments.begin(),worker_path(name,options));
  std::vector<char*> argv;for (auto& arg:arguments) argv.push_back(arg.data());argv.push_back(nullptr);
  std::string visible=std::to_string(options.execution.device_ids[0]);
  if (const char* inherited=std::getenv("CUDA_VISIBLE_DEVICES")) {
    std::istringstream stream(inherited);std::vector<std::string> devices;std::string token;
    while (std::getline(stream,token,',')) devices.push_back(token);
    if (options.execution.device_ids[0]>=static_cast<int>(devices.size()))
      throw BackendError(StatusCode::execution_failed,"device id is outside CUDA_VISIBLE_DEVICES");
    visible=devices[options.execution.device_ids[0]];
  }
  std::vector<std::string> environment;
  for (char** entry=environ;*entry;++entry) {
    const std::string value(*entry);
    const auto key=value.substr(0,value.find('='));
    if (key!="CUDA_VISIBLE_DEVICES" && !overrides.count(key)) environment.push_back(value);
  }
  for (const auto& item:overrides) environment.push_back(item.first+"="+item.second);
  environment.push_back("CUDA_VISIBLE_DEVICES="+visible);
  std::vector<char*> env;for (auto& entry:environment) env.push_back(entry.data());env.push_back(nullptr);
  const auto logfile=(temp.path/"worker.log").string();
  posix_spawn_file_actions_t actions;posix_spawnattr_t attributes;
  if (posix_spawn_file_actions_init(&actions)!=0) throw BackendError(StatusCode::execution_failed,"cannot initialize worker file actions");
  int error=posix_spawn_file_actions_addopen(&actions,STDOUT_FILENO,logfile.c_str(),O_WRONLY|O_CREAT|O_TRUNC,0600);
  if (!error) error=posix_spawn_file_actions_adddup2(&actions,STDOUT_FILENO,STDERR_FILENO);
  if (!error) error=posix_spawn_file_actions_addopen(&actions,STDIN_FILENO,"/dev/null",O_RDONLY,0);
  if (error) {posix_spawn_file_actions_destroy(&actions);throw BackendError(StatusCode::execution_failed,"cannot configure worker output");}
  error=posix_spawnattr_init(&attributes);
  if (error) {posix_spawn_file_actions_destroy(&actions);throw BackendError(StatusCode::execution_failed,"cannot initialize worker attributes");}
  const char* inherit_group=std::getenv("GRAPHMINE_WORKER_INHERIT_PROCESS_GROUP");
  const bool own_group=!(inherit_group && std::strcmp(inherit_group,"1")==0);
  error=posix_spawnattr_setflags(&attributes,own_group ? POSIX_SPAWN_SETPGROUP : 0);
  if (!error && own_group) error=posix_spawnattr_setpgroup(&attributes,0);
  pid_t pid=-1;
  if (!error) error=posix_spawn(&pid,argv[0],&actions,&attributes,argv.data(),env.data());
  posix_spawn_file_actions_destroy(&actions);posix_spawnattr_destroy(&attributes);
  if (error) throw BackendError(StatusCode::backend_unavailable,"cannot start "+name+": "+std::strerror(error));
  const auto deadline=Clock::now()+std::chrono::seconds(options.timeout_seconds);
  int status=0;bool timeout=false,oversize=false;
  while (true) {
    const auto result=waitpid(pid,&status,WNOHANG);
    if (result==pid) break;
    if (result<0 && errno!=EINTR) {kill(own_group ? -pid : pid,SIGKILL);while(waitpid(pid,&status,0)<0 && errno==EINTR){};throw BackendError(StatusCode::execution_failed,"cannot wait for worker");}
    std::error_code ec;const auto bytes=fs::file_size(logfile,ec);
    timeout=Clock::now()>=deadline;oversize=!ec && bytes>64ULL*1024*1024;
    if (timeout || oversize) {kill(own_group ? -pid : pid,SIGKILL);while(waitpid(pid,&status,0)<0 && errno==EINTR){};break;}
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  if (timeout || oversize) throw BackendError(StatusCode::resource_exhausted,timeout?"GPU worker timed out":"GPU worker exceeded 64 MiB output limit");
  std::error_code ec;const auto bytes=fs::file_size(logfile,ec);
  if (ec || bytes>64ULL*1024*1024) throw BackendError(StatusCode::resource_exhausted,"worker output is missing or too large");
  std::ifstream input(logfile);std::string output((std::istreambuf_iterator<char>(input)),{});
  if (!WIFEXITED(status) || WEXITSTATUS(status)!=0)
    throw BackendError(StatusCode::execution_failed,name+" worker failed: "+output.substr(output.size()>2000?output.size()-2000:0));
  return output;
}

} // namespace graphmine::detail::isolated
