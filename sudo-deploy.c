#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <sys/types.h>
#include <unistd.h>
#include <string.h>
#include <libgen.h>
#include <limits.h>
#include <stdlib.h>

int main(int argc, char** argv)
{
  uid_t e = geteuid();
  assert(e == 0); // Must be root
  if(argc != 2) {
    fprintf(stderr, "Usage: %s CONTAINER\n", argv[0]);
  }
  char *dir = realpath(dirname(argv[0]), NULL);
  char buf[strlen(dir)+32];
  strcpy(buf, dir);
  strcat(buf, "/web-app-dock.py");
  printf("exec %s\n", buf);
  execl(buf, buf, "deploy", "-v", "-c", argv[1], (char*)NULL);
  printf("Error: did not exec");
  return 1;
}
