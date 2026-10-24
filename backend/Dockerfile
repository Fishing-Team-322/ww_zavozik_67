# Один образ на все команды: CMD выбирает, что собрать (api, worker, bot).
FROM golang:1.26.10-alpine AS build
WORKDIR /src
COPY backend/go.mod backend/go.sum ./backend/
COPY integrations/go.mod ./integrations/go.mod
WORKDIR /src/backend
RUN go mod download
COPY integrations /src/integrations
COPY backend .
ARG CMD=api
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app ./cmd/${CMD}

FROM gcr.io/distroless/static-debian12:nonroot
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA
ENV APP_BUILD_SHA=$GIT_SHA
COPY --from=build /out/app /app
COPY ml/reports/metrics /data/model-reports
ENV MODEL_REPORTS_DIR=/data/model-reports
USER nonroot
ENTRYPOINT ["/app"]
