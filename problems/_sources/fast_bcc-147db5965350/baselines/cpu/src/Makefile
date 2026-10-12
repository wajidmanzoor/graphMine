ifdef BREAKDOWN
BREAK = -DBREAKDOWN
endif

ifdef NLONG
INTN = -DNLONG
endif

ifdef ELONG
INTE = -DELONG
endif

ifdef N2LONG
INTN2 = -DN2LONG
endif

ifdef CLANG
CC = clang++
else
CC = g++
endif

CPPFLAGS = -std=c++17 -Wall -Wextra -Werror $(INTN) $(INTE) $(INTN2)

INCLUDE_PATH = -I../parlaylib/include/

ifdef CILKPLUS
CPPFLAGS += -DPARLAY_CILKPLUS -DCILK -fcilkplus
else ifdef OPENCILK
CPPFLAGS += -DPARLAY_OPENCILK -DCILK -fopencilk
else ifdef SERIAL
CPPFLAGS += -DPARLAY_SEQUENTIAL
else
CPPFLAGS += -pthread
endif

ifdef DEBUG
CPPFLAGS += -DDEBUG -Og
else
CPPFLAGS += -O3 -mcx16 -march=native
endif

ifdef STDALLOC
CPPFLAGS += -DPARLAY_USE_STD_ALLOC
endif


all: FAST_BCC

FAST_BCC: BCC.h BCC.cpp spanning_forest.h connectivity.h sparse_table.h LDD.h graph.h Graph_CSR.h
	$(CC) $(CPPFLAGS) $(INCLUDE_PATH) BCC.cpp -o FAST_BCC

clean:
	rm FAST_BCC 
