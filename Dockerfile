FROM node:22-bookworm-slim AS browser
WORKDIR /build/web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN npm ci
COPY web/ ./
COPY docs/showcase/ /build/docs/showcase/
RUN npm run build

FROM rust:1.90-bookworm AS native
WORKDIR /build
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
RUN cargo build --release --locked -p rslib-hydro

FROM python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY --from=browser /build/src/rslib/web/ src/rslib/web/
COPY --from=native /build/target/release/rslib-hydro /usr/local/bin/rslib-hydro
RUN pip install --no-cache-dir --no-deps . && useradd --create-home --uid 10001 rslib && mkdir /data && chown rslib:rslib /data
USER rslib
ENV RSLIB_DATA=/data
EXPOSE 8000
CMD ["rslib", "serve", "--host", "0.0.0.0", "--data", "/data"]
