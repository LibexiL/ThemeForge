# COPR "make srpm" build: builds the source RPM straight from this git checkout.
# COPR runs:  make -f .copr/Makefile srpm outdir=<dir> spec=<spec>
SPEC := packaging/themeforge.spec
VERSION := $(shell sed -n 's/^Version:[[:space:]]*//p' $(SPEC))
outdir ?= $(CURDIR)

srpm:
	dnf -y install git rpm-build >/dev/null 2>&1 || true
	git config --global --add safe.directory "$(CURDIR)" || true
	mkdir -p "$(outdir)" build
	git archive --format=tar.gz --prefix="ThemeForge-$(VERSION)/" -o "build/ThemeForge-$(VERSION).tar.gz" HEAD
	rpmbuild -bs "$(SPEC)" --define "_sourcedir $(CURDIR)/build" --define "_srcrpmdir $(outdir)"
