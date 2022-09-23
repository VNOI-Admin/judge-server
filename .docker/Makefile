GIT_TAG ?= master
TAG ?= latest

.PHONY: all judge-tier1 judge-tier2 judge-tier3 judge-tiervnoj

all: judge-tier1 judge-tier2 judge-tier3 judge-tiervnoj judge-tierlqdoj

judge-tier1:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier1 -t vnoj/judge-tier1:$(TAG) tier1

judge-tier2:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier2 -t vnoj/judge-tier2:$(TAG) tier2

judge-tier3:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tier3 -t vnoj/judge-tier3:$(TAG) tier3

judge-tiervnoj:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tiervnoj -t vnoj/judge-tiervnoj:$(TAG) tiervnoj

judge-tierlqdoj-nocache:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tierlqdoj -t vnoj/judge-tierlqdoj:$(TAG) --no-cache tierlqdoj

judge-tierlqdoj:
	docker build --build-arg TAG="${GIT_TAG}" -t vnoj/judge-tierlqdoj -t vnoj/judge-tierlqdoj:$(TAG) tierlqdoj
