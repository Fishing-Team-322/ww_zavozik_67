// Package config — настройки из переменных окружения.
package config

import (
	"os"
	"time"
)

type Config struct {
	HTTPAddr    string        // HTTP_ADDR
	DatabaseURL string        // DATABASE_URL
	MLAddr      string        // ML_ADDR — gRPC Python-сервиса; пусто — только фолбэк
	MLTimeout   time.Duration // ML_TIMEOUT
	JWTSecret   string        // JWT_SECRET
	LogLevel    string        // LOG_LEVEL: debug | info | warn | error
}

func Load() Config {
	return Config{
		HTTPAddr:    env("HTTP_ADDR", ":8080"),
		DatabaseURL: env("DATABASE_URL", ""),
		MLAddr:      env("ML_ADDR", "localhost:50051"),
		MLTimeout:   duration("ML_TIMEOUT", 5*time.Second),
		JWTSecret:   env("JWT_SECRET", ""),
		LogLevel:    env("LOG_LEVEL", "info"),
	}
}

func env(k, def string) string {
	if v, ok := os.LookupEnv(k); ok {
		return v
	}
	return def
}

func duration(k string, def time.Duration) time.Duration {
	if d, err := time.ParseDuration(os.Getenv(k)); err == nil {
		return d
	}
	return def
}
