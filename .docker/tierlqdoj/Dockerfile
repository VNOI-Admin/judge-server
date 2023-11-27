FROM dmoj/runtimes-tier3

ARG TAG=master

RUN apt-get update && \
    apt-get install -y python3-venv && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir /ScratchCLI && cd /ScratchCLI && \
    curl -L https://github.com/cuom1999/ScratchCLI/archive/master.tar.gz | tar -xz --strip-components=1 

RUN mkdir /judge /problems && cd /judge && \
    curl -L https://github.com/LQDJudge/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
    python3 -m venv --prompt=DMOJ /env && \
    /env/bin/pip3 install cython && \
    /env/bin/pip3 install -e . && \
    /env/bin/python3 setup.py develop && \
    HOME=~judge . ~judge/.profile && \
    runuser -u judge -w PATH -- /env/bin/dmoj-autoconf -V > /judge-runtime-paths.yml && \
    echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
    curl -L https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h -o /usr/include/testlib.h && \
    sed -i '/^#include <cstdio>/a#include <cstdint>' /usr/include/testlib.h && \
    g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s /usr/include/testlib.h && \
    curl -L https://raw.githubusercontent.com/skyvn97/testlib/customized-testlib/testlib_themis_cms.h -o /usr/include/testlib_themis_cms.h && \
    sed -i '/^#include <cstdio>/a#include <cstdint>' /usr/include/testlib_themis_cms.h && \
    g++ -std=c++17 -Wall -DONLINE_JUDGE -DTHEMIS -O2 -fmax-errors=5 -march=native -s /usr/include/testlib_themis_cms.h && \
    curl -L https://raw.githubusercontent.com/cuom1999/testlib/customized-testlib/testlib_modified.h -o /usr/include/testlib_modified.h && \
    sed -i '/^#include <cstdio>/a#include <cstdint>' /usr/include/testlib_modified.h && \
    g++ -std=c++17 -Wall -DONLINE_JUDGE -DTHEMIS -O2 -fmax-errors=5 -march=native -s /usr/include/testlib_modified.h && \
    find /usr/include/ -name stdc++.h -exec g++ -std=c++17 -Wall -DONLINE_JUDGE -O2 -fmax-errors=5 -march=native -s {} \;

RUN groupadd -r user && useradd -r -g user user

ENTRYPOINT ["/judge/.docker/entry"]
