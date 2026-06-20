from eval-harness:latest 

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# rustup wires PATH via shell profiles, but the harness runs phases through non-login
# `docker exec`, which never sources them. Set it on the image env so `cargo` is always found.
ENV PATH=/home/node/.cargo/bin:$PATH
