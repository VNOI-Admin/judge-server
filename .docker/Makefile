GIT_TAG ?= master
TAG ?= latest

.PHONY: all judge-tier1 judge-tier1-local judge-tier2 judge-tier3 judge-tiervnoj judge-tiericpc

all: judge-tier1 judge-tier2 judge-tier3 judge-tiervnoj judge-tiericpc

judge-tier1:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier1 -t vnoj/judge-tier1:$(TAG) tier1

# Build from the local working tree instead of downloading a tarball from GitHub.
judge-tier1-local:
	docker build -f tier1/Dockerfile.local -t vnoj/judge-tier1 -t vnoj/judge-tier1:$(TAG) ..

judge-tier2:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier2 -t vnoj/judge-tier2:$(TAG) tier2

judge-tier3:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier3 -t vnoj/judge-tier3:$(TAG) tier3

judge-tiervnoj:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tiervnoj -t vnoj/judge-tiervnoj:$(TAG) tiervnoj

judge-tiericpc:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tiericpc -t vnoj/judge-tiericpc:$(TAG) tiericpc
