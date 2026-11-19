package main

import (
	"net/http"
	"testing"
	"time"
)

func TestHTTPServerSetsConnectionTimeouts(t *testing.T) {
	server := newHTTPServer("8080", http.NotFoundHandler())
	if server.ReadHeaderTimeout != 5*time.Second ||
		server.ReadTimeout != 15*time.Second ||
		server.WriteTimeout != 180*time.Second ||
		server.IdleTimeout != 60*time.Second {
		t.Fatalf("unexpected HTTP server timeouts: %#v", server)
	}
	if server.MaxHeaderBytes != 1<<20 {
		t.Fatalf("expected 1 MiB header limit, got %d", server.MaxHeaderBytes)
	}
}
