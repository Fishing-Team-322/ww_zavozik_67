// Package registry — общий реестр плагинов: источники, категоризаторы,
// сценарии, действия, каналы уведомлений регистрируются по имени в init().
package registry

import (
	"fmt"
	"sort"
	"sync"
)

type Registry[T any] struct {
	mu    sync.RWMutex
	items map[string]T
}

func New[T any]() *Registry[T] {
	return &Registry[T]{items: map[string]T{}}
}

// Register паникует на дубликате: это ошибка сборки, а не рантайма.
func (r *Registry[T]) Register(name string, v T) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.items[name]; ok {
		panic(fmt.Sprintf("registry: %q already registered", name))
	}
	r.items[name] = v
}

func (r *Registry[T]) Get(name string) (T, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	v, ok := r.items[name]
	return v, ok
}

func (r *Registry[T]) Names() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.items))
	for n := range r.items {
		names = append(names, n)
	}
	sort.Strings(names)
	return names
}
