#include <graphmine/runtime_c.h>
#include <stdio.h>
#include <string.h>
int main(void) {
 const char *request = "{\"command\":\"catalog\"}";
 char *response = NULL; size_t length = 0;
 int rc = graphmine_runtime_request(request, strlen(request), &response, &length);
 if (rc) return 2;
 fwrite(response, 1, length, stdout); graphmine_runtime_free(response); return 0;
}
