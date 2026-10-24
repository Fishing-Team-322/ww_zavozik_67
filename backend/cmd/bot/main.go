// Command bot — Telegram-бот: привязка чата по одноразовой ссылке,
// утренняя сводка, тревоги о разрывах. Владелец: Бэк 3.
//
// TODO(Бэк 3): клиент Telegram Bot API, /start <token>, отправка через
// notify.Channels["telegram"]. Токен — TELEGRAM_BOT_TOKEN.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/config"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/logging"
)

func main() {
	cfg := config.Load()
	log := logging.New(cfg.LogLevel)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	log.Info("bot started (not implemented yet)")
	<-ctx.Done()
}
