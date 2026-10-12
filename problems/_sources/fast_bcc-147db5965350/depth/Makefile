CXX = g++
CXXFLAGS = -std=c++17 -O3 -Wall -Wextra
TARGET = bfs
OBJS = main.o graph.o

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $(TARGET) $(OBJS)

main.o: main.cpp graph.hpp
	$(CXX) $(CXXFLAGS) -c main.cpp

graph.o: graph.cpp graph.hpp
	$(CXX) $(CXXFLAGS) -c graph.cpp

clean:
	rm -f $(OBJS) $(TARGET)

run: $(TARGET)
	./$(TARGET) datasets/edges.txt 0

.PHONY: all clean run
