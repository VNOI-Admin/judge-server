FROM dmoj/runtimes-tier1

ARG TAG=master

# Install scratch interpreter
RUN curl --location -o scratch-run.zip https://github.com/VNOI-Admin/scratch-run/releases/download/0.0.2/scratch-run_0.0.2_linux_amd64.zip && \
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
