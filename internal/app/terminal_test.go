package app

import (
	"strings"
	"testing"
)

func TestSelectedStyleContinuesAfterNestedStarStyle(t *testing.T) {
	line := styled(fit("● "+styled("☆", gray)+" Feed | Short", 30), reverse)
	if !strings.Contains(line, reset+reverse+" Feed | Short") {
		t.Fatalf("selected style was not restored after nested style: %q", line)
	}
	if visibleWidth(line) != 30 {
		t.Fatalf("visible width = %d, want 30", visibleWidth(line))
	}
}
