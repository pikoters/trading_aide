package marketdesk

import "errors"

// ErrNotFound indicates that a requested saved analysis does not exist.
var ErrNotFound = errors.New("saved analysis not found")
