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
    /env/bin/pip3 install cython setuptools && \
    /env/bin/pip3 install -e . && \
    /env/bin/python3 setup.py develop && \
    HOME=~judge . ~judge/.profile && \
    runuser -u judge -w PATH -- /env/bin/dmoj-autoconf -V > /judge-runtime-paths.yml && \
    echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml && \
    /judge/.docker/download_testlib_and_precompile

RUN groupadd -r user && useradd -r -g user user

ENTRYPOINT ["/judge/.docker/entry"]
