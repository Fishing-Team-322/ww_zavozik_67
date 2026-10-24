package main

import (
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/demo"
	"os"
)

func main() { _ = json.NewEncoder(os.Stdout).Encode(demo.Build()) }
