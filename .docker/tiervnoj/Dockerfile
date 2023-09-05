FROM dmoj/runtimes-tier1

ARG TAG=master

RUN apt-get update && \
	apt-get install -y --no-install-recommends openjdk-19-jdk-headless openjdk-19-jre-headless golang unzip jq && \
	rm -rf /var/lib/apt/lists/*

# Install scratch-run + pypy + kotlin + rust
RUN ARCH=$([ $(uname -m) = "x86_64" ] && echo "amd64" || echo "arm64") && \
	curl --location -o scratch-run.zip $(curl -s https://api.github.com/repos/VNOI-Admin/scratch-run/releases/latest | grep -o -m 1 "https://github\.com.*.*linux_$ARCH\.zip") && \
		unzip scratch-run.zip && \
		mv scratch-run /usr/bin/scratch-run && \
		rm scratch-run.zip && \
	if [ "$(arch)" = x86_64 ]; then PYPY_ARCH=linux64; else PYPY_ARCH="$(arch)"; fi && \
	mkdir /opt/pypy2 && curl -L "$(curl https://www.pypy.org/download.html | grep "/pypy2.*$PYPY_ARCH" | head -n1 | cut -d'"' -f4)" | \
		tar xj -C /opt/pypy2 --strip-components=1 && /opt/pypy2/bin/pypy -mcompileall && \
		chmod a+rx /opt/pypy2/lib /opt/pypy2/lib/*.so* && \
		rm -f /opt/pypy2/bin/python* && \
	mkdir /opt/pypy3 && curl -L "$(curl https://www.pypy.org/download.html | grep "/pypy3.*$PYPY_ARCH" | head -n1 | cut -d'"' -f4)" | \
		tar xj -C /opt/pypy3 --strip-components=1 && /opt/pypy3/bin/pypy -mcompileall && \
		rm -f /opt/pypy3/bin/python* && \
	curl -L -okotlin.zip "$(curl -s https://api.github.com/repos/JetBrains/kotlin/releases | \
		jq -r '[.[] | select(.prerelease | not) | .assets | flatten | .[] | select((.name | startswith("kotlin-compiler")) and (.name | endswith(".zip"))) | .browser_download_url][0]')" && \
		unzip kotlin.zip && mv kotlinc /opt/kotlin && rm kotlin.zip && \
	runuser judge -c 'curl https://sh.rustup.rs -sSf | sh -s -- -y' && \
		mkdir rust && ( \
			cd rust && \
			curl -sL https://raw.githubusercontent.com/DMOJ/judge/master/dmoj/executors/RUST.py | \
				sed '/^CARGO_TOML/,/^"""/!d;//d' > Cargo.toml && \
			mkdir src && \
			curl -sL https://raw.githubusercontent.com/DMOJ/judge/master/dmoj/executors/RUST.py | \
				sed '/^TEST_PROGRAM/,/^"""/!d;//d' > src/main.rs && \
			chown -R judge: . && \
			runuser -u judge /home/judge/.cargo/bin/cargo fetch \
		) && \
		rm -rf rust

ENV PATH="/opt/kotlin/bin:/opt/pypy2/bin:/opt/pypy3/bin:/home/judge/.cargo/bin:${PATH}"

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
