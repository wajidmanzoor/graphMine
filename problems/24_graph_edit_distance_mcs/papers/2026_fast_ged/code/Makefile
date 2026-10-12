# Directories
SRC_DIR = src
BUILD_DIR = build
BIN_DIR = bin
LIB_DIR = lib
GPU_DIR = gpu

# Java Compiler
JAVAC = javac
JAR = jar
JAVA_FILES = $(wildcard $(SRC_DIR)/*.java)
CLASS_FILES = $(JAVA_FILES:$(SRC_DIR)/%.java=$(BUILD_DIR)/%.class)
JAR_FILE = $(BIN_DIR)/FAS-ged.jar
MANUAL_SUPER_JAR_FILE = $(BIN_DIR)/graph-ged-super.jar

# Dynamic Classpath (Includes all JARs in ./lib)
CLASSPATH = $(LIB_DIR)/*

# CUDA Compiler
NVCC = nvcc
CUDA_FILE = $(GPU_DIR)/gpu_evaluation.cu
CUDA_PTX = $(GPU_DIR)/gpu_evaluation.ptx
CUDA_LIB = $(LIB_DIR)/libcuda_wrapper.so
CUDA_FLAGS = -arch=sm_60 -use_fast_math -shared -Xcompiler -fPIC -ptx

# Java Runtime
MAIN_CLASS = Main
JAVA_RUN_CMD = java -Djava.library.path=$(LIB_DIR) -cp $(JAR_FILE):$(CLASSPATH) $(MAIN_CLASS) 2 2 1 1 ./data/ggraph1.gxl ./data/ggraph2.gxl ./slurm_result/output.txt MUTA 50000

# Default target
all:clean compile_java compile_cuda jar

# Compile Java files with dynamic classpath
compile_java:
	@echo "🔹 Compiling Java files with classpath..."
	@mkdir -p $(BUILD_DIR)
	@$(JAVAC) -d $(BUILD_DIR) -cp "$(CLASSPATH)" $(JAVA_FILES)

# Compile CUDA file into PTX *only if it does not exist*
$(CUDA_PTX):
	@if [ ! -f $(CUDA_PTX) ]; then \
		echo "🔹 PTX file not found! Compiling CUDA PTX..."; \
		$(NVCC) -ptx $(CUDA_FILE) -o $(CUDA_PTX); \
	else \
		echo "✅ PTX file already exists. Skipping compilation."; \
	fi

# Compile CUDA shared library (only if PTX is compiled)
compile_cuda: $(CUDA_PTX)
	@echo "🔹 Compiling CUDA shared library..."
	@mkdir -p $(LIB_DIR)
#   @$(NVCC) $(CUDA_FLAGS) -o $(CUDA_LIB) $(CUDA_FILE)

# Package Java classes into a JAR
jar: compile_java
	@echo "🔹 Creating JAR file..."
	@mkdir -p $(BIN_DIR)
	@$(JAR) cf $(JAR_FILE) -C $(BUILD_DIR) .

# Create a fat JAR (with all dependencies)

	@echo "🔹 Creating super JAR manually by merging dependencies..."
	@mkdir -p $(BIN_DIR)
	@mkdir -p tmp_jar
	@for jar in $(LIB_DIR)/*.jar; do \
		unzip -qo $$jar -d tmp_jar; \
	done
	@unzip -qo $(JAR_FILE) -d tmp_jar
	@$(JAR) cfe $(MANUAL_SUPER_JAR_FILE) $(MAIN_CLASS) -C tmp_jar .
# Clean up the temporary directory used for creating the super JAR
	@rm -rf tmp_jar

# Run the program
run: all
	@echo "🚀 Running the program... "
	@$(JAVA_RUN_CMD)

# Run the super JAR file
run-super: jar
	@echo "🚀 Running the super JAR..."
	@echo "Current directory: $(shell pwd)"
	@java -jar $(MANUAL_SUPER_JAR_FILE) 2 2 1 1 ./data/ggraph1.gxl ./data/ggraph2.gxl t.txt MUTA 50000
# Clean build artifacts
clean:
	@echo "🧹 Cleaning up..."
	@rm -rf $(BUILD_DIR) $(BIN_DIR) 
