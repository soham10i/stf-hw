# Trustworthy maintenance T4: the Edge TPU half of `make edge` - TensorFlow's full-integer TFLite
# converter and Coral's edgetpu_compiler (x86-64 Linux only; runs emulated on Apple silicon).
# Coral's apt repository (packages.cloud.google.com) answers 403 since its shutdown; the compiler
# is taken from Coral's own repository, which ships it with its loader and libraries.
#   docker build --platform linux/amd64 -t stf-edgetpu stf-cad/hbw/edge/tpu
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && git clone --depth 1 --filter=blob:none --sparse https://github.com/google-coral/edgetpu.git /opt/coral \
 && git -C /opt/coral sparse-checkout set compiler \
 && chmod +x /opt/coral/compiler/x86_64/edgetpu_compiler /opt/coral/compiler/x86_64/edgetpu_compiler_bin/* \
 && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /opt/coral/.git
ENV PATH=/opt/coral/compiler/x86_64:$PATH
RUN pip install --no-cache-dir tensorflow-cpu==2.15.1 "numpy<2"
WORKDIR /work
