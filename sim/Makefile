CC      := gcc
CFLAGS  := -Wall -Wextra -DHOST_SIM \
            -I sim/shims \
            -I firmware/main \
            -g -O2 -pthread
LDFLAGS := -pthread -lm

OUT     := sim/build/phytosense_sim

SRCS    := firmware/main/gradient_mesh.c \
            sim/transport.c \
            sim/sensors_sim.c \
            sim/node_main.c

.PHONY: all clean

all: sim/build $(OUT)

sim/build:
	mkdir -p sim/build

# Compile all sources in a single shot – simple enough for four files
$(OUT): $(SRCS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $^
	@echo "Built: $@"

clean:
	rm -rf sim/build
