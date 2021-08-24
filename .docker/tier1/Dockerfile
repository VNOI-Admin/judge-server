FROM dmoj/runtimes-tier1

ARG TAG=master

RUN apt-get update && \
    apt-get install -y --no-install-recommends unzip && \
    rm -rf /var/lib/apt/lists/*

# Install scratch interpreter
RUN curl --location -o scratch-run.zip $(curl -s https://api.github.com/repos/VNOI-Admin/scratch-run/releases/latest | grep -o -m 1 "https://github\.com.*.*linux_amd64\.zip") && \
	unzip scratch-run.zip && \
	mv scratch-run /usr/bin/scratch-run && \
	rm scratch-run.zip

RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/VNOI-Admin/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
	pip3 install -e . && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
	curl -L https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h -o /usr/include/testlib.h && \
	g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s /usr/include/testlib.h && \
	find /usr/include/ -name stdc++.h -exec g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s {} \;

ENTRYPOINT ["/judge/.docker/entry"]
