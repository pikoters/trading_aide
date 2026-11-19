// Command stock-market-desk serves the Go API and Vue dashboard.
package main

import (
	"errors"
	"log"
	"net/http"
	"os"
	"time"

	"pikoters.info.mytrading/internal/postgresstore"
	"pikoters.info.mytrading/web"
)

// main wires PostgreSQL and the HTTP router, then serves the API on PORT.
func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	store, err := postgresstore.OpenPostgresFromEnv()
	if err != nil {
		log.Fatalf("configure PostgreSQL: %v", err)
	}
	defer store.Close()

	router := web.NewRouterWithSavedDataStore(store)

	log.Printf("Starting Go stock API on :%s", port)
	server := newHTTPServer(port, router)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

// newHTTPServer configures bounded header, read, write, and idle timeouts for
// the API server. The longer write timeout accommodates bounded market-data
// requests.
func newHTTPServer(port string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              ":" + port,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      180 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}
}
