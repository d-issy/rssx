package app

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

type Config struct {
	DBPath             string
	StatePath          string
	Timezone           string
	MinIntervalMin     int
	MaxIntervalMin     int
	InitialIntervalMin int
	SchedulerTickMin   int
}

func loadConfig() (Config, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return Config{}, err
	}
	dataHome := envOr("XDG_DATA_HOME", filepath.Join(home, ".local", "share"))
	stateHome := envOr("XDG_STATE_HOME", filepath.Join(home, ".local", "state"))
	configHome := envOr("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	c := Config{
		DBPath:             filepath.Join(dataHome, "rssx", "rssx.db"),
		StatePath:          filepath.Join(stateHome, "rssx", "state.toml"),
		Timezone:           "local",
		MinIntervalMin:     10,
		MaxIntervalMin:     24 * 60,
		InitialIntervalMin: 30,
		SchedulerTickMin:   1,
	}
	f, err := os.Open(filepath.Join(configHome, "rssx", "config.toml"))
	if os.IsNotExist(err) {
		return c, nil
	}
	if err != nil {
		return Config{}, err
	}
	defer func() { _ = f.Close() }()

	section := ""
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(strings.SplitN(scanner.Text(), "#", 2)[0])
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") && strings.HasSuffix(line, "]") {
			section = strings.TrimSpace(line[1 : len(line)-1])
			continue
		}
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue
		}
		key, value := strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
		value = strings.Trim(value, `"'`)
		if section == "" {
			switch key {
			case "db_path":
				c.DBPath = expandHome(value, home)
			case "state_path":
				c.StatePath = expandHome(value, home)
			case "timezone":
				c.Timezone = value
			}
		} else if section == "fetch" {
			n, convErr := strconv.Atoi(value)
			if convErr != nil {
				continue
			}
			switch key {
			case "min_interval_min":
				c.MinIntervalMin = n
			case "max_interval_min":
				c.MaxIntervalMin = n
			case "initial_interval_min":
				c.InitialIntervalMin = n
			case "scheduler_tick_min":
				c.SchedulerTickMin = n
			}
		}
	}
	return c, scanner.Err()
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func expandHome(path, home string) string {
	if path == "~" {
		return home
	}
	if strings.HasPrefix(path, "~/") {
		return filepath.Join(home, path[2:])
	}
	return path
}
