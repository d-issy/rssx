package app

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode"
)

const (
	reset   = "\x1b[0m"
	bold    = "\x1b[1m"
	dim     = "\x1b[2m"
	reverse = "\x1b[7m"
	red     = "\x1b[31m"
	cyan    = "\x1b[36m"
	yellow  = "\x1b[33m"
	gray    = "\x1b[90m"
)

type Terminal struct {
	in       *bufio.Reader
	oldState string
}

func newTerminal() *Terminal { return &Terminal{in: bufio.NewReader(os.Stdin)} }

func (t *Terminal) enter() error {
	info, err := os.Stdin.Stat()
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeCharDevice == 0 {
		return fmt.Errorf("run rssx from an interactive terminal")
	}
	stateCommand := exec.Command("stty", "-g")
	stateCommand.Stdin = os.Stdin
	if state, err := stateCommand.Output(); err == nil {
		t.oldState = strings.TrimSpace(string(state))
		rawCommand := exec.Command("stty", "-echo", "cbreak")
		rawCommand.Stdin = os.Stdin
		if err := rawCommand.Run(); err != nil {
			return err
		}
	}
	fmt.Print("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
	return nil
}

func (t *Terminal) exit() {
	fmt.Print("\x1b[?25h\x1b[0m\x1b[?1049l")
	if t.oldState != "" {
		command := exec.Command("stty", t.oldState)
		command.Stdin = os.Stdin
		_ = command.Run()
	}
}

func (t *Terminal) showCursor() { fmt.Print("\x1b[?25h") }
func (t *Terminal) hideCursor() { fmt.Print("\x1b[?25l") }

func (t *Terminal) size() (int, int) {
	command := exec.Command("stty", "size")
	command.Stdin = os.Stdin
	if out, err := command.Output(); err == nil {
		parts := strings.Fields(string(out))
		if len(parts) == 2 {
			rows, _ := strconv.Atoi(parts[0])
			cols, _ := strconv.Atoi(parts[1])
			if rows > 0 && cols > 0 {
				return rows, cols
			}
		}
	}
	return 30, 100
}

func (t *Terminal) render(lines []string) {
	rows, cols := t.size()
	var b strings.Builder
	b.WriteString("\x1b[H")
	for i := 0; i < rows; i++ {
		line := ""
		if i < len(lines) {
			line = clipANSI(lines[i], cols)
		}
		b.WriteString(line)
		b.WriteString(reset + "\x1b[K")
		if i+1 < rows {
			b.WriteByte('\n')
		}
	}
	fmt.Print(b.String())
}

func (t *Terminal) readKey(timeout time.Duration) (string, error) {
	if timeout > 0 && !t.inputReady(timeout) {
		return "", nil
	}
	r, _, err := t.in.ReadRune()
	if err != nil {
		return "", err
	}
	switch r {
	case 3:
		return "ctrl_c", nil
	case '\r', '\n':
		return "enter", nil
	case '\t':
		return "tab", nil
	case 127, 8:
		return "backspace", nil
	case 27:
		if !t.inputReady(10 * time.Millisecond) {
			return "esc", nil
		}
		a, _ := t.in.ReadByte()
		if a != '[' {
			return "esc", nil
		}
		if !t.inputReady(10 * time.Millisecond) {
			return "esc", nil
		}
		b, _ := t.in.ReadByte()
		if key := map[byte]string{'A': "up", 'B': "down", 'C': "right", 'D': "left", 'H': "home", 'F': "end"}[b]; key != "" {
			return key, nil
		}
		if key := map[byte]string{'1': "home", '3': "delete", '4': "end", '7': "home", '8': "end"}[b]; key != "" && t.inputReady(10*time.Millisecond) {
			if suffix, _ := t.in.ReadByte(); suffix == '~' {
				return key, nil
			}
		}
		return "", nil
	}
	return string(r), nil
}

func (t *Terminal) inputReady(timeout time.Duration) bool {
	if t.in.Buffered() > 0 {
		return true
	}
	fd := int(os.Stdin.Fd())
	var readSet syscall.FdSet
	readSet.Bits[fd/64] |= 1 << (fd % 64)
	tv := syscall.NsecToTimeval(timeout.Nanoseconds())
	n, err := syscall.Select(fd+1, &readSet, nil, nil, &tv)
	return err == nil && n > 0
}

func styled(text, code string) string {
	return code + strings.ReplaceAll(text, reset, reset+code) + reset
}
func fit(text string, width int) string {
	n := visibleWidth(text)
	if n <= width {
		return text + strings.Repeat(" ", width-n)
	}
	plain := stripANSI(text)
	return clipText(plain, width)
}
func clipText(text string, width int) string {
	if width <= 0 {
		return ""
	}
	if visibleWidth(text) <= width {
		return text
	}
	var b strings.Builder
	n := 0
	for _, r := range text {
		w := runeWidth(r)
		if n+w > width-1 {
			break
		}
		b.WriteRune(r)
		n += w
	}
	return b.String() + "…"
}
func visibleWidth(text string) int {
	n := 0
	escaped := false
	for i := 0; i < len(text); {
		if text[i] == 27 && i+1 < len(text) && text[i+1] == '[' {
			escaped = true
			i += 2
			continue
		}
		if escaped {
			if text[i] == 'm' {
				escaped = false
			}
			i++
			continue
		}
		r, size := utf8Rune(text[i:])
		n += runeWidth(r)
		i += size
	}
	return n
}
func stripANSI(text string) string {
	var b strings.Builder
	escaped := false
	for i := 0; i < len(text); {
		if text[i] == 27 && i+1 < len(text) && text[i+1] == '[' {
			escaped = true
			i += 2
			continue
		}
		if escaped {
			if text[i] == 'm' {
				escaped = false
			}
			i++
			continue
		}
		r, size := utf8Rune(text[i:])
		b.WriteRune(r)
		i += size
	}
	return b.String()
}
func clipANSI(text string, width int) string {
	if visibleWidth(text) <= width {
		return text
	}
	return clipText(stripANSI(text), width)
}
func utf8Rune(s string) (rune, int) {
	r, size := rune(s[0]), 1
	if r >= 128 {
		for n := 2; n <= 4 && n <= len(s); n++ {
			rr := []rune(s[:n])
			if len(rr) == 1 && rr[0] != unicode.ReplacementChar {
				return rr[0], n
			}
		}
	}
	return r, size
}
func runeWidth(r rune) int {
	if unicode.Is(unicode.Mn, r) {
		return 0
	}
	if r >= 0x1100 && (r <= 0x115f || r == 0x2329 || r == 0x232a || (r >= 0x2e80 && r <= 0xa4cf) || (r >= 0xac00 && r <= 0xd7a3) || (r >= 0xf900 && r <= 0xfaff) || (r >= 0xfe10 && r <= 0xfe19) || (r >= 0xfe30 && r <= 0xfe6f) || (r >= 0xff00 && r <= 0xff60) || (r >= 0xffe0 && r <= 0xffe6) || (r >= 0x1f300 && r <= 0x1faff)) {
		return 2
	}
	return 1
}

func writeOSC52(value string) { fmt.Printf("\x1b]52;c;%s\x07", value) }

var _ io.Reader = os.Stdin
