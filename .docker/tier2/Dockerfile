FROM dmoj/runtimes-tier2

ARG TAG=master
RUN apt-get update && apt-get install -y git cmake

# Install scratch compiler
RUN mkdir /scratch_compiler && cd /scratch_compiler && \
	curl -L https://github.com/scraterpreter/scrapec/archive/master.tar.gz | tar -xz --strip-components=1 && \
	pip3 install -e .

# Install scratch interpreter
RUN mkdir /scratch_interpreter && cd /scratch_interpreter && \
	curl -L https://github.com/khuebeo/scrape/archive/master.tar.gz | tar -xz --strip-components=1 && \
	mkdir build && \
	cd build && \
	cmake .. && \
	make install

RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/VNOI-Admin/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
	pip3 install -e . && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
	echo '  scrapec: /usr/local/bin/scrapec' >> /judge-runtime-paths.yml && \
	curl -L https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h -o /usr/include/testlib.h && \
	g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s /usr/include/testlib.h && \
	find /usr/include/ -name stdc++.h -exec g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s {} \;

ENTRYPOINT ["/judge/.docker/entry"]
