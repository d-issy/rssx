package main

import (
	"fmt"
	"os"

	"github.com/d-issy/rssx/internal/app"
)

func main() {
	if err := app.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "rssx:", err)
		os.Exit(1)
	}
}
