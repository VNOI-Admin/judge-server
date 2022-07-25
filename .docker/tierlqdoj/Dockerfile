FROM dmoj/runtimes-tier1

ARG TAG=master

RUN apt-get update && \
    curl -sL https://deb.nodesource.com/setup_16.x | bash && \
    apt-get install -y nodejs npm && \
    mkdir /ScratchCLI && cd /ScratchCLI && \
    curl -L https://github.com/cuom1999/ScratchCLI/archive/master.tar.gz | tar -xz --strip-components=1 && \
    npm install . && npm install . -g

RUN ARCH=$([ $(uname -m) = "x86_64" ] && echo "amd64" || echo "arm64") && \
    if [ "$(arch)" = x86_64 ]; then PYPY_ARCH=linux64; else PYPY_ARCH="$(arch)"; fi && \
    mkdir /opt/pypy2 && curl -L "$(curl https://www.pypy.org/download.html | grep "/pypy2.*$PYPY_ARCH" | head -n1 | cut -d'"' -f4 | sed "s/-portable//")" | \
    tar xj -C /opt/pypy2 --strip-components=1 && /opt/pypy2/bin/pypy -mcompileall && \
    rm -f /opt/pypy2/bin/python* && \
    mkdir /opt/pypy3 && curl -L "$(curl https://www.pypy.org/download.html | grep "/pypy3.*$PYPY_ARCH" | head -n1 | cut -d'"' -f4 | sed "s/-portable//")" | \
    tar xj -C /opt/pypy3 --strip-components=1 && /opt/pypy3/bin/pypy -mcompileall && \
    rm -f /opt/pypy3/bin/python*

ENV PATH="/opt/pypy2/bin:/opt/pypy3/bin:${PATH}"


RUN mkdir /judge /problems && cd /judge && \
    curl -L https://github.com/LQDJudge/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
    pip3 install -e . && \
    python3 setup.py develop && \
    HOME=~judge . ~judge/.profile && \
    runuser -u judge -w PATH -- dmoj-autoconf -V > /judge-runtime-paths.yml && \
    echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
    curl -L https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h -o /usr/include/testlib.h && \
    g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s /usr/include/testlib.h && \
    curl -L https://raw.githubusercontent.com/skyvn97/testlib/customized-testlib/testlib_themis_cms.h -o /usr/include/testlib_themis_cms.h && \
    g++ -std=c++17 -Wall -DONLINE_JUDGE -DTHEMIS -O2 -fmax-errors=5 -march=native -s /usr/include/testlib_themis_cms.h && \
    find /usr/include/ -name stdc++.h -exec g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s {} \;

ENTRYPOINT ["/judge/.docker/entry"]
