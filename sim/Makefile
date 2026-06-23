CC      := gcc
CFLAGS  := -Wall -Wextra -DHOST_SIM \
            -I sim/shims \
            -I sim \
            -I firmware/main \
            -g -O2 -pthread
LDLIBS  := -pthread -lm

OUT     := sim/build/phytosense_sim

SRCS    := firmware/main/gradient_mesh.c \
            sim/transport.c \
            sim/sensors_sim.c \
            sim/node_main.c

.PHONY: all clean

all: sim/build $(OUT)

sim/build:
	mkdir -p sim/build

# Libraries must come after the objects on the link line, or libm symbols
# (e.g. sin) referenced by sensors_sim.c stay unresolved.
$(OUT): $(SRCS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)
	@echo "Built: $@"

clean:
	rm -rf sim/build