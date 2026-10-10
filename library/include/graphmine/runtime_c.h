#pragma once

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int graphmine_runtime_abi_version(void);
// Returns 0 on successful allocation of a response. Algorithm/input failures
// are structured in the JSON response. Returns -1 for invalid output pointers
// or allocation failure. The caller owns *response and releases it with free.
int graphmine_runtime_request(const char* request, size_t length,
                             char** response, size_t* response_length);
void graphmine_runtime_free(void* response);

#ifdef __cplusplus
}
#endif
