# The trust boundary. Static binary, distroless runtime — nothing in this image
# needs a shell, and the smaller the image the shorter the list of things that
# can reach the network from inside it (SHARED §1).
FROM golang:1.25-alpine AS build
WORKDIR /src

# Module files first so dependency resolution caches independently of source.
# go.sum comes along: without it the build re-resolves and writes its own, which
# means the image's dependency set is whatever the registry served that day.
COPY go.mod go.sum ./
RUN go mod download

# The generated stubs are committed (ADR-0022), so they are copied rather than
# generated: the image needs no `buf` and reaches no network beyond the base
# image, which is what makes `docker compose up` work on a clean clone.
COPY gen ./gen
COPY services/gateway ./services/gateway
ARG VERSION=0.0.0-dev
RUN CGO_ENABLED=0 go build \
        -ldflags "-s -w -X main.version=${VERSION}" \
        -o /out/berean ./services/gateway/cmd/berean

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/berean /usr/local/bin/berean

# The profile documents. `berean ask --profile pca` resolves `pca.yaml` from
# here, and the image is the right place for them: a profile is a doctrinal
# commitment that ships with the build rather than deployment configuration that
# varies per host, and this is the same trade catena's image makes by COPYing
# its source. Editing one therefore needs `make build`, which every target that
# runs a container already depends on.
COPY profiles /etc/berean/profiles
ENV BEREAN_PROFILE_DIR=/etc/berean/profiles

USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/berean"]
CMD ["version"]
