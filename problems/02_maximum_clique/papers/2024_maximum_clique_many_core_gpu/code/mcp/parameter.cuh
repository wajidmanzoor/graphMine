#pragma once

#define MAX_DEGEN 8192
#define MAX_TRAVERSE_LEVELS 4096
#define SZTH 10
#define SZFRONTIER 1

__constant__ uint PARTSIZE;
__constant__ uint NUMPART;
__constant__ uint MAXLEVEL;
__constant__ uint NUMDIVS;
__constant__ uint MAXDEG;
__constant__ uint MAXUNDEG;
__constant__ uint CBPSM;
__constant__ uint MSGCNT;
__constant__ uint CB;
__constant__ uint WARPS;

// This is for debug, not for release
// #define LOAD_BALANCE
// #define TIMER