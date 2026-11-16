FROM alpine:3.20

# nftables  -> firewall / ACL (Module C)
# iproute2  -> routing + tc/netem impairment (Module A, E)
# tcpdump / tshark -> packet capture + retransmission counts (Module D)
RUN apk add --no-cache bash nftables iproute2 iproute2-tc tcpdump tshark iperf3 iputils

COPY router/router-init.sh router/impair.sh router/linkctl.sh router/capture.sh router/lib.sh /usr/local/bin/
RUN cd /usr/local/bin && chmod 755 router-init.sh impair.sh linkctl.sh capture.sh lib.sh \
 && ln -s impair.sh impair && ln -s linkctl.sh linkctl && ln -s capture.sh capture

ENTRYPOINT ["router-init.sh"]
