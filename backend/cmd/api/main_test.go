package main

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

func buildAPI(t *testing.T) string {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "api")
	if runtime.GOOS == "windows" {
		bin += ".exe"
	}
	cmd := exec.Command("go", "build", "-o", bin, ".")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("go build: %v\n%s", err, out)
	}
	return bin
}

// Отказ старта HTTP-сервера — ошибка, а не успешное завершение.
func TestExitsNonzeroOnListenFailure(t *testing.T) {
	cmd := exec.Command(buildAPI(t))
	cmd.Env = []string{"ML_ADDR=", "HTTP_ADDR=bad"}
	out, err := cmd.CombinedOutput()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() == 0 {
		t.Fatalf("want nonzero exit, got %v\n%s", err, out)
	}
	if strings.Contains(string(out), "api stopped") {
		t.Errorf("failed startup must not report a clean stop:\n%s", out)
	}
}

// Штатный SIGTERM остаётся успешным завершением.
func TestExitsZeroOnSigterm(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows does not support Unix SIGTERM delivery")
	}
	logPath := filepath.Join(t.TempDir(), "api.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		t.Fatal(err)
	}
	defer logFile.Close()

	cmd := exec.Command(buildAPI(t))
	cmd.Env = []string{"ML_ADDR=", "HTTP_ADDR=127.0.0.1:0"}
	cmd.Stdout, cmd.Stderr = logFile, logFile
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = cmd.Process.Kill() }()

	deadline := time.Now().Add(10 * time.Second)
	for {
		log, _ := os.ReadFile(logPath)
		if strings.Contains(string(log), "api listening") {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("api did not start:\n%s", log)
		}
		time.Sleep(10 * time.Millisecond)
	}
	if err := cmd.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err != nil {
		log, _ := os.ReadFile(logPath)
		t.Fatalf("SIGTERM must exit cleanly: %v\n%s", err, log)
	}
}
