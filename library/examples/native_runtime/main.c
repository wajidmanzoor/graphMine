#include <graphmine/runtime_c.h>
#include <stdio.h>
#include <string.h>

int main(void) {
  const char *request =
    "{\"command\":\"run\",\"operation\":\"k-core\",\"device\":\"cpu\","
    "\"parameters\":{\"requested_k\":2},\"graph\":{"
    "\"graph\":{\"id\":\"native-consumer\",\"directed\":false,\"allows_self_loops\":false,\"allows_parallel_edges\":false},"
    "\"vertices\":[{\"id\":0},{\"id\":1},{\"id\":2},{\"id\":3}],"
    "\"edges\":[{\"id\":0,\"source\":0,\"target\":1},{\"id\":1,\"source\":1,\"target\":2},{\"id\":2,\"source\":2,\"target\":0}]}}";
  char *response = NULL;
  size_t length = 0;
  if (graphmine_runtime_request(request, strlen(request), &response, &length)) return 2;
  fwrite(response, 1, length, stdout);
  graphmine_runtime_free(response);
  return 0;
}
