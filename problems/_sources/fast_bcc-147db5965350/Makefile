# Main Makefile to build all subprojects

# List of all subdirectories containing Makefiles
SUBDIRS = \
	baselines/cpu/src \
	baselines/uvm \
	baselines/wk-bcc-2017 \
	baselines/wk-bcc-2018 \
	depth \
	external/streams \
	external/without_streams \
	gpu/with_filter \
	gpu/without_filter

# Default target: build all subprojects
.PHONY: all $(SUBDIRS)
all: $(SUBDIRS)

# Build each subdirectory
$(SUBDIRS):
	@echo "Building in $@..."
	@$(MAKE) -C $@

# Clean all subprojects
.PHONY: clean
clean:
	@echo "Cleaning all subprojects..."
	@for dir in $(SUBDIRS); do \
		echo "Cleaning $$dir..."; \
		$(MAKE) -C $$dir clean; \
	done

# Run all subprojects (if they have a run target)
.PHONY: run
run:
	@echo "Running all subprojects..."
	@for dir in $(SUBDIRS); do \
		echo "Running $$dir..."; \
		$(MAKE) -C $$dir run 2>/dev/null || echo "No run target in $$dir"; \
	done

# Help target
.PHONY: help
help:
	@echo "Available targets:"
	@echo "  all      - Build all subprojects (default)"
	@echo "  clean    - Clean all subprojects"
	@echo "  run      - Run all subprojects (if they have a run target)"
	@echo "  help     - Show this help message"
	@echo ""
	@echo "Subdirectories with Makefiles:"
	@for dir in $(SUBDIRS); do \
		echo "  - $$dir"; \
	done
