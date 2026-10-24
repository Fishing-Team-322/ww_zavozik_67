package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateOutputPaths(t *testing.T) {
	dir := t.TempDir()
	flows := filepath.Join(dir, "flows.csv")
	if err := os.WriteFile(flows, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	relative, err := filepath.Rel(mustWorkingDir(t), flows)
	if err != nil {
		t.Fatal(err)
	}
	for _, transaction := range []string{flows, relative, flows + ".quality.json"} {
		if err := validateOutputPaths(flows, transaction); err == nil {
			t.Fatalf("accepted colliding output %q", transaction)
		}
	}
	for _, transaction := range []string{"", filepath.Join(dir, "events.csv"), filepath.Join(dir, "new", "events.csv")} {
		if err := validateOutputPaths(flows, transaction); err != nil {
			t.Fatalf("rejected distinct output: %v", err)
		}
	}
	got, err := os.ReadFile(flows)
	if err != nil || string(got) != "keep" {
		t.Fatal("validation changed existing output")
	}
}

func TestValidateOutputAliases(t *testing.T) {
	dir := t.TempDir()
	flows := filepath.Join(dir, "flows.csv")
	if err := os.WriteFile(flows, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	hardlink := filepath.Join(dir, "hard.csv")
	if err := os.Link(flows, hardlink); err != nil {
		t.Fatal(err)
	}
	symlink := filepath.Join(dir, "link.csv")
	if err := os.Symlink(flows, symlink); err != nil {
		t.Fatal(err)
	}
	aliasDir := filepath.Join(dir, "alias")
	if err := os.Symlink(dir, aliasDir); err != nil {
		t.Fatal(err)
	}
	for _, transaction := range []string{hardlink, symlink} {
		if err := validateOutputPaths(flows, transaction); err == nil {
			t.Fatalf("accepted alias %q", transaction)
		}
	}
	if err := validateOutputPaths(filepath.Join(dir, "new.csv"), filepath.Join(aliasDir, "new.csv")); err == nil {
		t.Fatal("accepted two nonexistent paths through a parent symlink")
	}
}

func TestValidateDanglingOutputSymlinks(t *testing.T) {
	for _, targetName := range []string{"flows.csv", "flows.csv.quality.json"} {
		for _, relative := range []bool{false, true} {
			dir := t.TempDir()
			flows := filepath.Join(dir, "flows.csv")
			transactions := filepath.Join(dir, "transactions.csv")
			target := filepath.Join(dir, targetName)
			linkTarget := target
			if relative {
				linkTarget = targetName
			}
			if err := os.Symlink(linkTarget, transactions); err != nil {
				t.Fatal(err)
			}
			if err := validateOutputPaths(flows, transactions); err == nil {
				t.Fatalf("accepted dangling symlink to %q (relative=%v)", targetName, relative)
			}
			if _, err := os.Stat(target); !os.IsNotExist(err) {
				t.Fatal("validation created dangling symlink target")
			}
		}
	}
}

func TestValidateSymlinkBeforeParentTraversal(t *testing.T) {
	for _, targetName := range []string{"flows.csv", "flows.csv.quality.json"} {
		for _, exists := range []bool{false, true} {
			dir := t.TempDir()
			real := filepath.Join(dir, "real")
			child := filepath.Join(real, "child")
			if err := os.MkdirAll(child, 0700); err != nil {
				t.Fatal(err)
			}
			link := filepath.Join(dir, "link")
			if err := os.Symlink(child, link); err != nil {
				t.Fatal(err)
			}
			flows := filepath.Join(real, "flows.csv")
			target := filepath.Join(real, targetName)
			transactions := link + "/../" + targetName // must not clean before symlink resolution
			if exists {
				if err := os.WriteFile(target, []byte("keep"), 0600); err != nil {
					t.Fatal(err)
				}
				a, errA := os.Stat(target)
				b, errB := os.Stat(transactions)
				if errA != nil || errB != nil || !os.SameFile(a, b) {
					t.Fatal("fixture paths must alias")
				}
			}
			if err := validateOutputPaths(flows, transactions); err == nil {
				t.Fatalf("accepted symlink/.. alias to %q (exists=%v)", targetName, exists)
			}
			if exists {
				if got, err := os.ReadFile(target); err != nil || string(got) != "keep" {
					t.Fatal("validation changed target")
				}
			} else if _, err := os.Stat(target); !os.IsNotExist(err) {
				t.Fatal("validation created target")
			}
			// Normal ../ paths to a distinct output remain supported.
			if err := validateOutputPaths(flows, child+"/../events.csv"); err != nil {
				t.Fatalf("rejected valid parent traversal: %v", err)
			}
		}
	}
}

func mustWorkingDir(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	return wd
}
