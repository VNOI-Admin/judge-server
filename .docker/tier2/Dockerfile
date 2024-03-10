FROM dmoj/runtimes-tier2

ARG TAG=master

RUN apt-get update && \
	apt-get install -y --no-install-recommends unzip && \
	rm -rf /var/lib/apt/lists/*

# Install scratch interpreter
RUN ARCH=$([ $(uname -m) = "x86_64" ] && echo "amd64" || echo "arm64") && \
	curl --location -o scratch-run.zip $(curl -s https://api.github.com/repos/VNOI-Admin/scratch-run/releases/latest | grep -o -m 1 "https://github\.com.*.*linux_$ARCH\.zip") && \
	unzip scratch-run.zip && \
	mv scratch-run /usr/bin/scratch-run && \
	rm scratch-run.zip

RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/VNOI-Admin/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
	python3 -m venv --prompt=DMOJ /env && \
	/env/bin/pip3 install cython && \
	/env/bin/pip3 install -e . && \
	/env/bin/python3 setup.py develop && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- /env/bin/dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
	/judge/.docker/download_testlib_and_precompile

ENTRYPOINT ["/usr/bin/tini", "--", "/judge/.docker/entry"]
