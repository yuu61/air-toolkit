package domain

import "path/filepath"

// ManualsEnv は変換結果の置き場を上書きする環境変数。
const ManualsEnv = "AIR_TOOLKIT_MANUALS"

// DefaultManualsDir は変換結果の置き場。$AIR_TOOLKIT_MANUALS → ~/.air-toolkit/manuals の順。
// 環境の読み方は引数で受け、この層から OS を触らない。
func DefaultManualsDir(getenv func(string) string, home string) string {
	if v := getenv(ManualsEnv); v != "" {
		return v
	}
	if home == "" {
		return ""
	}
	return filepath.Join(home, ".air-toolkit", "manuals")
}

// BookDir は冊子の変換結果の置き場 <manuals>/<train>/<book>。
func BookDir(manualsDir string, d Doc) string {
	return filepath.Join(manualsDir, d.Train, d.Book)
}
