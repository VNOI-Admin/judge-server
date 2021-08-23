FROM dmoj/runtimes-tier1

ARG TAG=master
RUN apt-get update && apt-get install -y npm 

# Install scratch interpreter
RUN mkdir /scratch_interpreter && cd /scratch_interpreter && \
	curl -L https://github.com/VNOI-Admin/scratch-run/archive/master.tar.gz | tar -xz --strip-components=1 && \
	npm install -g pkg && \
	npm install && \
	pkg index.js -t node12-linux-x64 && \
	mv index /usr/bin/scratch-run

RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/VNOI-Admin/judge-server/archive/scratch.tar.gz | tar -xz --strip-components=1 && \
	pip3 install -e . && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
	curl -L https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h -o /usr/include/testlib.h && \
	g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s /usr/include/testlib.h && \
	find /usr/include/ -name stdc++.h -exec g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s {} \;

ENTRYPOINT ["/judge/.docker/entry"]
