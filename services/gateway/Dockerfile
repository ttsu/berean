# The trust boundary. Static binary, distroless runtime — nothing in this image
# needs a shell, and the smaller the image the shorter the list of things that
# can reach the network from inside it (SHARED §1).
FROM golang:1.24-alpine AS build
WORKDIR /src

# Module files first so dependency resolution caches independently of source.
COPY go.mod ./
RUN go mod download

COPY services/gateway ./services/gateway
ARG VERSION=0.0.0-dev
RUN CGO_ENABLED=0 go build \
        -ldflags "-s -w -X main.version=${VERSION}" \
        -o /out/berean ./services/gateway/cmd/berean

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/berean /usr/local/bin/berean
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/berean"]
CMD ["version"]
