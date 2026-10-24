FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -o /out/integration-server ./cmd/server

FROM alpine:3.22
RUN addgroup -S app && adduser -S -G app app
COPY --from=build /out/integration-server /usr/local/bin/integration-server
USER app
EXPOSE 8091
ENTRYPOINT ["/usr/local/bin/integration-server"]
