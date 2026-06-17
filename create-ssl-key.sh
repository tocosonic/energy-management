#!/bin/bash

# create root certificate and private key
openssl req -x509 -newkey rsa:4096 \
    -keyout key.pem \
    -out cert.pem \
    -days 825 \
    -nodes

# create server private key
openssl genrsa -out server.key 4096

# create server certificate signing request (CSR)
openssl req -new -key server.key -out server.csr -config server.cnf

# sign server certificate with root certificate
openssl x509 -req -in server.csr -CA cert.pem -CAkey key.pem \
    -CAcreateserial -out server.pem -days 825 -sha256 -extfile server.cnf -extensions req_ext

# clean up intermediate files
rm server.csr cert.srl

# prepare storage directory for SSL certificates
mkdir -p ~/.ssh/server
chmod 700 ~/.ssh/server

# move generated files to a secure directory
mv server.pem ~/.ssh/server/server-cert.pem
mv server.key ~/.ssh/server/server-key.pem
mv cert.pem ~/.ssh/server/root-cert.pem
mv key.pem ~/.ssh/server/root-key.pem
