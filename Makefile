PREFIX ?= $(HOME)/.local
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra

.PHONY: all install clean

all: build/clawpod-import build/clawpod-verify

build/clawpod-import: src/clawpod-import.c
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ $< $$(pkg-config --cflags --libs libgpod-1.0 glib-2.0)

build/clawpod-verify: src/clawpod-verify.c
	mkdir -p build
	$(CC) $(CFLAGS) -o $@ $< $$(pkg-config --cflags --libs libgpod-1.0 glib-2.0)

install: all
	install -Dm755 clawpod.py $(PREFIX)/bin/clawpod
	install -Dm755 build/clawpod-import $(PREFIX)/libexec/clawpod/clawpod-import
	install -Dm755 build/clawpod-verify $(PREFIX)/libexec/clawpod/clawpod-verify

clean:
	rm -f build/clawpod-import build/clawpod-verify
