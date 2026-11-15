FROM alpine:3.21

# Install core networking, recon, and scripting tools without caching
RUN apk add --no-cache \
    nmap \
    nmap-scripts \
    curl \
    wget \
    netcat-openbsd \
    tcpdump \
    bind-tools \
    whois \
    openssl \
    python3 \
    py3-pip \
    git \
    && adduser -D -u 10001 runner

WORKDIR /workspace
USER runner

CMD ["/bin/sh"]
