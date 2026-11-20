FROM node:22-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS api-build
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
COPY --from=frontend-build /frontend/dist ./frontend/dist
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /out/stock-market-desk .

FROM alpine:3.21
RUN apk add --no-cache ca-certificates \
    && addgroup -S -g 10001 app \
    && adduser -S -u 10001 -G app app
WORKDIR /app
COPY --from=api-build /out/stock-market-desk /usr/local/bin/stock-market-desk
COPY --from=api-build --chown=10001:10001 /src/frontend/dist ./frontend/dist
ENV PORT=8080
EXPOSE 8080
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/stock-market-desk"]