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

# Set up a non-root user for safer execution
RUN adduser -D secuser
USER secuser
WORKDIR /home/secuser

CMD ["/bin/sh"]
