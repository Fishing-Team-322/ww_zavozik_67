package dadata

import (
	"sync"
	"time"
)

type cacheEntry struct {
	party     Party
	expiresAt time.Time
}

// Cache is a bounded process-local TTL cache. Persisted profiles belong in
// the hub's counterparty store, not in this request cache.
type Cache struct {
	mu      sync.Mutex
	ttl     time.Duration
	entries map[string]cacheEntry
}

func NewCache(ttl time.Duration) *Cache {
	if ttl <= 0 {
		ttl = 24 * time.Hour
	}
	return &Cache{ttl: ttl, entries: make(map[string]cacheEntry)}
}

func (c *Cache) get(id string) (Party, bool) {
	if c == nil {
		return Party{}, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	entry, ok := c.entries[id]
	if !ok || time.Now().After(entry.expiresAt) {
		delete(c.entries, id)
		return Party{}, false
	}
	return entry.party, true
}

func (c *Cache) put(id string, party Party) {
	if c == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.entries) >= 10_000 {
		for key, entry := range c.entries {
			if time.Now().After(entry.expiresAt) {
				delete(c.entries, key)
			}
		}
		if len(c.entries) >= 10_000 {
			for key := range c.entries {
				delete(c.entries, key)
				break
			}
		}
	}
	c.entries[id] = cacheEntry{party: party, expiresAt: time.Now().Add(c.ttl)}
}
