FROM alpine:latest

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
    git

WORKDIR /workspace

CMD ["/bin/sh"]
